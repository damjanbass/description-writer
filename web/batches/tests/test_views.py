"""Tests for batches.views: tenancy isolation, the upload -> generate flow,
approve/reject decisions, publish credential scoping, and artifact downloads.

Every URL is exercised as two personas: a member of the owning organization
(allowed) and a member of a *different* organization (must get 404 -- never
403, so org existence is not revealed; see common/org.py).
"""
from __future__ import annotations

import json
import tempfile
from unittest import mock

from accounts.models import Membership, Organization
from connections.models import ConnectorCredential
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from batches.models import Batch, ReviewItem

_FERNET_KEY = Fernet.generate_key().decode("ascii")

User = get_user_model()

_CSV_CONTENT = (
    b"id;name;brand\n"
    b"1;Bela majica;Acme\n"
    b"2;Crna jakna;Acme\n"
)

_TMP_MEDIA = tempfile.mkdtemp(prefix="korpus-test-media-")


def _org(slug, name=None):
    return Organization.objects.create(name=name or slug.title(), slug=slug)


def _member(org, username):
    user = User.objects.create_user(username=username, password="pw")
    Membership.objects.create(user=user, organization=org)
    return user


def _batch(org, user=None, with_file=True, **kwargs):
    kwargs.setdefault("provider", Batch.Provider.FAKE)
    batch = Batch.objects.create(
        organization=org, name="Test batch", created_by=user, **kwargs
    )
    if with_file:
        batch.source_file.save("catalog.csv", ContentFile(_CSV_CONTENT), save=True)
    return batch


def _item(batch, product_id="p-1", **kwargs):
    kwargs.setdefault("cirilica", "Бела мајица.")
    kwargs.setdefault("latinica", "Bela majica.")
    return ReviewItem.objects.create(batch=batch, product_id=product_id, **kwargs)


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class _ViewTestBase(TestCase):
    def setUp(self):
        self.org = _org("acme", "Acme")
        self.other_org = _org("umbrella", "Umbrella")
        self.member = _member(self.org, "member")
        self.outsider = _member(self.other_org, "outsider")
        self.batch = _batch(self.org, self.member)
        self.item = _item(self.batch)

    def url(self, name, **extra):
        kwargs = {"org_slug": self.org.slug, **extra}
        return reverse(f"batches:{name}", kwargs=kwargs)


class TenancyTests(_ViewTestBase):
    """A user from another organization gets 404 on every batches URL."""

    def _all_urls(self):
        return [
            ("get", self.url("list")),
            ("get", self.url("upload")),
            ("get", self.url("detail", pk=self.batch.pk)),
            ("get", self.url("item", pk=self.batch.pk, item_pk=self.item.pk)),
            ("post", self.url("item-approve", pk=self.batch.pk, item_pk=self.item.pk)),
            ("post", self.url("item-reject", pk=self.batch.pk, item_pk=self.item.pk)),
            ("get", self.url("publish", pk=self.batch.pk)),
            ("get", self.url("artifact", pk=self.batch.pk, kind="queue")),
        ]

    def test_outsider_gets_404_everywhere(self):
        self.client.force_login(self.outsider)
        for method, url in self._all_urls():
            response = getattr(self.client, method)(url)
            self.assertEqual(response.status_code, 404, f"{method.upper()} {url}")

    def test_member_can_reach_read_views(self):
        self.client.force_login(self.member)
        for name, kwargs in [
            ("list", {}),
            ("upload", {}),
            ("detail", {"pk": self.batch.pk}),
            ("item", {"pk": self.batch.pk, "item_pk": self.item.pk}),
            ("publish", {"pk": self.batch.pk}),
        ]:
            response = self.client.get(self.url(name, **kwargs))
            self.assertEqual(response.status_code, 200, name)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url("list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/app/login/", response["Location"])


class UploadTests(_ViewTestBase):
    def test_valid_upload_creates_batch_and_generates(self):
        self.client.force_login(self.member)
        upload = SimpleUploadedFile(
            "katalog.csv", _CSV_CONTENT, content_type="text/csv"
        )
        response = self.client.post(
            self.url("upload"),
            {
                "name": "Jesenja kolekcija",
                "source_file": upload,
                "source_script": Batch.SourceScript.LATINICA,
                "provider": Batch.Provider.FAKE,
                "model": "",
            },
        )
        batch = Batch.objects.exclude(pk=self.batch.pk).get()
        self.assertRedirects(
            response, self.url("detail", pk=batch.pk), fetch_redirect_response=False
        )
        # Dev queue is synchronous, so generation already ran.
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        self.assertEqual(batch.items.count(), 2)
        self.assertTrue(
            batch.audit_logs.filter(action="upload").exists()
        )

    def test_oversize_file_rejected(self):
        # The HTTP client re-encodes multipart bodies, so a spoofed .size can't
        # cross the request boundary -- exercise the form's own 50 MB cap, which
        # is the validation the view runs.
        from batches.forms import BatchUploadForm

        upload = SimpleUploadedFile("big.csv", _CSV_CONTENT, content_type="text/csv")
        upload.size = 51 * 1024 * 1024
        form = BatchUploadForm(
            data={
                "source_script": Batch.SourceScript.LATINICA,
                "provider": Batch.Provider.FAKE,
            },
            files={"source_file": upload},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("prevelik", str(form.errors["source_file"]))
        self.assertEqual(Batch.objects.exclude(pk=self.batch.pk).count(), 0)

    def test_bad_extension_rejected(self):
        self.client.force_login(self.member)
        upload = SimpleUploadedFile("data.txt", b"x", content_type="text/plain")
        response = self.client.post(
            self.url("upload"),
            {
                "source_file": upload,
                "source_script": Batch.SourceScript.LATINICA,
                "provider": Batch.Provider.FAKE,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Batch.objects.exclude(pk=self.batch.pk).count(), 0)


class DecisionTests(_ViewTestBase):
    def test_approve_sets_status_and_actor(self):
        self.client.force_login(self.member)
        response = self.client.post(
            self.url("item-approve", pk=self.batch.pk, item_pk=self.item.pk)
        )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ReviewItem.Status.APPROVED)
        self.assertEqual(self.item.decided_by, self.member)

    def test_approve_published_item_fails_gracefully(self):
        self.item.status = ReviewItem.Status.PUBLISHED
        self.item.save(update_fields=["status"])
        self.client.force_login(self.member)
        response = self.client.post(
            self.url("item-approve", pk=self.batch.pk, item_pk=self.item.pk),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ReviewItem.Status.PUBLISHED)

    def test_reject_requires_reason(self):
        self.client.force_login(self.member)
        response = self.client.post(
            self.url("item-reject", pk=self.batch.pk, item_pk=self.item.pk),
            {"reason": ""},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ReviewItem.Status.PENDING)

    def test_reject_with_reason(self):
        self.client.force_login(self.member)
        self.client.post(
            self.url("item-reject", pk=self.batch.pk, item_pk=self.item.pk),
            {"reason": "Pogrešan rod prideva."},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ReviewItem.Status.REJECTED)
        self.assertEqual(self.item.reason, "Pogrešan rod prideva.")


class PublishViewTests(_ViewTestBase):
    def setUp(self):
        super().setUp()
        # crypto.get_fernet reads the env var (not a Django setting); the test
        # runner forces DEBUG=False so the dev fallback key does not apply.
        env_patcher = mock.patch.dict(
            "os.environ", {"KORPUS_FERNET_KEY": _FERNET_KEY}
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.credential = self._credential(self.org, "Prodavnica RS")
        self.other_credential = self._credential(self.other_org, "Tudja prodavnica")
        self.item.approve(self.member)

    def _credential(self, org, label):
        credential = ConnectorCredential(
            organization=org,
            connector_type="woocommerce",
            label=label,
            base_url="https://shop.example.rs",
        )
        credential.set_consumer_key("ck_test")
        credential.set_consumer_secret("cs_test")
        credential.save()
        return credential

    def test_form_shows_only_own_org_credentials(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url("publish", pk=self.batch.pk))
        self.assertContains(response, "Prodavnica RS")
        self.assertNotContains(response, "Tudja prodavnica")

    def test_other_org_credential_id_rejected(self):
        self.client.force_login(self.member)
        response = self.client.post(
            self.url("publish", pk=self.batch.pk),
            {
                "credential": self.other_credential.pk,
                "publish_script": Batch.SourceScript.LATINICA,
            },
        )
        # Not a valid choice -> re-rendered form with errors, nothing enqueued.
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ReviewItem.Status.APPROVED)


class ArtifactTests(_ViewTestBase):
    def test_csv_404_before_generation(self):
        self.client.force_login(self.member)
        response = self.client.get(
            self.url("artifact", pk=self.batch.pk, kind="csv")
        )
        self.assertEqual(response.status_code, 404)

    def test_queue_json_downloads_and_parses(self):
        self.client.force_login(self.member)
        response = self.client.get(
            self.url("artifact", pk=self.batch.pk, kind="queue")
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("review_queue.json", response["Content-Disposition"])
        payload = json.loads(response.content)
        ids = [item["product_id"] for item in payload["items"]]
        self.assertIn(self.item.product_id, ids)

    def test_unknown_kind_404(self):
        self.client.force_login(self.member)
        response = self.client.get(
            self.url("artifact", pk=self.batch.pk, kind="tajna")
        )
        self.assertEqual(response.status_code, 404)


class StatusFilterTests(_ViewTestBase):
    def setUp(self):
        super().setUp()
        self.approved_item = _item(self.batch, "p-2")
        self.approved_item.approve(self.member)

    def test_filter_returns_only_matching_items(self):
        self.client.force_login(self.member)
        response = self.client.get(
            self.url("detail", pk=self.batch.pk), {"status": "approved"}
        )
        items = list(response.context["items"])
        self.assertEqual(items, [self.approved_item])

    def test_invalid_status_value_ignored(self):
        self.client.force_login(self.member)
        response = self.client.get(
            self.url("detail", pk=self.batch.pk), {"status": "nesto-cudno"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["items"]), 2)
