"""One end-to-end test driving the full customer journey through the Django
test client: login -> upload -> generate -> review -> approve/reject ->
publish -> download artifacts -> org isolation.

This is deliberately the ONLY test in this module. Its job is not to
re-cover what test_views.py / test_tasks.py already cover in isolation --
it's to prove the pieces still fit together end to end, the way a real
customer session would exercise them. House-style helpers/fixtures below
mirror test_views.py and test_tasks.py: a real Fernet key for
ConnectorCredential (django's test runner forces DEBUG=False, so
connections/crypto.py's DEBUG-only dev key fallback does not apply), a
`;`-delimited CSV consumed by the FAKE provider, and a class-level recording
fake standing in for batches.tasks.WooCommerceConnector (dev's Q_CLUSTER is
sync, so `async_task(...)` calls run inline within the request, and the
locally-scoped connector instance publish_batch creates is otherwise
unreachable from the test).
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from accounts.models import Membership, Organization
from connections.models import ConnectorCredential
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from batches.models import AuditLog, Batch, ReviewItem
from pipeline.types import Script

# See test_views.py / test_tasks.py: a real key is required because the test
# runner forces DEBUG=False, so the DEBUG-only dev Fernet-key fallback in
# connections/crypto.py never applies here.
_FERNET_KEY = Fernet.generate_key().decode("ascii")

User = get_user_model()

_CSV_CONTENT = (
    b"id;name;brand\n"
    b"1;Bela majica;Acme\n"
    b"2;Crna jakna;Acme\n"
    b"3;Siva kapa;Acme\n"
)


class _RecordingConnector:
    """Fake WooCommerceConnector: no network, records every push_description
    call at the CLASS level.

    `batches.tasks.publish_batch` instantiates the connector itself and
    discards it when done, so an instance-level `.calls` list would be
    unreachable from the test -- the class-level list is how this test
    inspects what was actually pushed once the request has returned.
    """

    calls: list[tuple[str, object, str]] = []

    def __init__(self, *, base_url=None, consumer_key=None, consumer_secret=None):
        self.base_url = base_url
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret

    def push_description(self, product_id, dual, *, publish_script=Script.LATINICA):
        type(self).calls.append((product_id, dual, publish_script))


class BatchJourneyE2ETest(TestCase):
    """The whole customer journey, front to back, as one test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(MEDIA_ROOT=Path(self._tmp.name))
        override.enable()
        self.addCleanup(override.disable)

        env_patcher = mock.patch.dict("os.environ", {"KORPUS_FERNET_KEY": _FERNET_KEY})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.other_org = Organization.objects.create(name="Umbrella", slug="umbrella")

        self.password = "korpus-test-pw-1!"
        self.user = User.objects.create_user(username="member", password=self.password)
        Membership.objects.create(user=self.user, organization=self.org)
        self.outsider = User.objects.create_user(username="outsider", password=self.password)
        Membership.objects.create(user=self.outsider, organization=self.other_org)

        _RecordingConnector.calls = []

    def url(self, name, **extra):
        kwargs = {"org_slug": self.org.slug, **extra}
        return reverse(f"batches:{name}", kwargs=kwargs)

    def _parse_csv(self, content: bytes) -> list[dict[str, str]]:
        # descriptions.csv passes every untrusted cell through
        # pipeline.fsio.neutralize_csv_cell, which prefixes a leading `'` to
        # any cell whose first character could start a spreadsheet formula --
        # strip it here the way a reviewer's own tooling would.
        text = content.decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        for row in rows:
            for key, value in row.items():
                if value.startswith("'"):
                    row[key] = value[1:]
        return rows

    def test_full_customer_journey(self):
        # -- 1. Login -----------------------------------------------------
        login_response = self.client.post(
            reverse("login"), {"username": "member", "password": self.password}
        )
        self.assertEqual(login_response.status_code, 302)

        # -- 2. Upload a catalog -> generation runs inline (dev queue is
        #       sync) -> redirect to the batch detail screen.
        upload = SimpleUploadedFile("katalog.csv", _CSV_CONTENT, content_type="text/csv")
        upload_response = self.client.post(
            self.url("upload"),
            {
                "name": "Jesenja kolekcija",
                "source_file": upload,
                "source_script": Batch.SourceScript.LATINICA,
                "provider": Batch.Provider.FAKE,
                "model": "",
            },
        )
        batch = Batch.objects.get()
        self.assertRedirects(upload_response, self.url("detail", pk=batch.pk))

        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        items = {item.product_id: item for item in ReviewItem.objects.filter(batch=batch)}
        self.assertEqual(set(items), {"1", "2", "3"})

        detail_response = self.client.get(self.url("detail", pk=batch.pk))
        self.assertEqual(detail_response.status_code, 200)
        counts = detail_response.context["counts"]
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["pending"], 3)
        self.assertEqual(counts["approved"], 0)
        self.assertEqual(counts["rejected"], 0)
        self.assertEqual(counts["published"], 0)

        self.assertTrue(
            AuditLog.objects.filter(batch=batch, action=AuditLog.Action.UPLOAD).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(batch=batch, action=AuditLog.Action.GENERATE).exists()
        )

        # -- 3. Open one item's review screen: both scripts must render.
        approve_item = items["1"]
        item_response = self.client.get(
            self.url("item", pk=batch.pk, item_pk=approve_item.pk)
        )
        self.assertEqual(item_response.status_code, 200)
        self.assertContains(item_response, approve_item.cirilica)
        self.assertContains(item_response, approve_item.latinica)

        # -- 4. Approve one item, reject another, leave the third pending.
        approve_response = self.client.post(
            self.url("item-approve", pk=batch.pk, item_pk=approve_item.pk)
        )
        self.assertEqual(approve_response.status_code, 302)

        reject_item = items["2"]
        reject_response = self.client.post(
            self.url("item-reject", pk=batch.pk, item_pk=reject_item.pk),
            {"reason": "Pogrešan rod prideva."},
        )
        self.assertEqual(reject_response.status_code, 302)

        pending_item = items["3"]

        approve_item.refresh_from_db()
        reject_item.refresh_from_db()
        pending_item.refresh_from_db()
        self.assertEqual(approve_item.status, ReviewItem.Status.APPROVED)
        self.assertEqual(approve_item.decided_by, self.user)
        self.assertEqual(reject_item.status, ReviewItem.Status.REJECTED)
        self.assertEqual(reject_item.reason, "Pogrešan rod prideva.")
        self.assertEqual(pending_item.status, ReviewItem.Status.PENDING)

        self.assertTrue(
            AuditLog.objects.filter(
                batch=batch, action=AuditLog.Action.APPROVE, product_id="1"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                batch=batch, action=AuditLog.Action.REJECT, product_id="2"
            ).exists()
        )

        # -- 5. Create an org-scoped connector credential and publish the
        #       approved item through a monkeypatched (no-network) connector.
        credential = ConnectorCredential(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Prodavnica RS",
            base_url="https://shop.example.rs",
        )
        credential.set_consumer_key("ck_test")
        credential.set_consumer_secret("cs_test")
        credential.save()

        with mock.patch("batches.tasks.WooCommerceConnector", _RecordingConnector):
            publish_response = self.client.post(
                self.url("publish", pk=batch.pk),
                {
                    "credential": credential.pk,
                    "publish_script": Batch.SourceScript.LATINICA,
                },
            )
        self.assertRedirects(publish_response, self.url("detail", pk=batch.pk))

        approve_item.refresh_from_db()
        reject_item.refresh_from_db()
        pending_item.refresh_from_db()
        self.assertEqual(approve_item.status, ReviewItem.Status.PUBLISHED)
        self.assertIsNotNone(approve_item.published_at)
        # Publishing is scoped to APPROVED items only -- reject/pending must
        # be entirely untouched by the publish run.
        self.assertEqual(reject_item.status, ReviewItem.Status.REJECTED)
        self.assertEqual(pending_item.status, ReviewItem.Status.PENDING)

        self.assertTrue(
            AuditLog.objects.filter(
                batch=batch, action=AuditLog.Action.PUBLISH, product_id="1"
            ).exists()
        )

        self.assertEqual(len(_RecordingConnector.calls), 1)
        called_product_id, called_dual, called_script = _RecordingConnector.calls[0]
        self.assertEqual(called_product_id, "1")
        self.assertEqual(called_dual.latinica, approve_item.latinica)
        self.assertEqual(called_dual.cirilica, approve_item.cirilica)
        self.assertEqual(called_script, Script.LATINICA)

        # -- 6. Download both artifacts.
        csv_response = self.client.get(self.url("artifact", pk=batch.pk, kind="csv"))
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("attachment", csv_response["Content-Disposition"])
        self.assertIn("descriptions.csv", csv_response["Content-Disposition"])
        csv_rows = self._parse_csv(b"".join(csv_response.streaming_content))
        self.assertEqual({row["product_id"] for row in csv_rows}, {"1", "2", "3"})

        queue_response = self.client.get(self.url("artifact", pk=batch.pk, kind="queue"))
        self.assertEqual(queue_response.status_code, 200)
        self.assertIn("attachment", queue_response["Content-Disposition"])
        self.assertIn("review_queue.json", queue_response["Content-Disposition"])
        queue_payload = json.loads(queue_response.content)
        status_by_id = {entry["product_id"]: entry["status"] for entry in queue_payload["items"]}
        self.assertEqual(
            status_by_id,
            {
                "1": ReviewItem.Status.PUBLISHED,
                "2": ReviewItem.Status.REJECTED,
                "3": ReviewItem.Status.PENDING,
            },
        )

        # -- 7. Org isolation, end to end: a member of a different
        #       organization gets 404 on this batch, not a peek at its data.
        self.client.logout()
        self.client.login(username="outsider", password=self.password)
        outsider_response = self.client.get(self.url("detail", pk=batch.pk))
        self.assertEqual(outsider_response.status_code, 404)
