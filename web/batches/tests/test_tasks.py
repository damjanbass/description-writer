"""Tests for batches.tasks: run_generation and publish_batch, the two
django_q2 background jobs. Dev settings run tasks synchronously
(Q_CLUSTER["sync"] = True), so calling these functions directly is exactly
what `async_task("batches.tasks.run_generation", batch.pk)` would do.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from accounts.models import Organization
from connections.models import ConnectorCredential
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from batches import tasks
from batches.models import AuditLog, Batch, ReviewItem
from pipeline.types import Script

# django's test runner forces settings.DEBUG = False regardless of
# config.settings.dev, so ConnectorCredential's DEBUG-only dev Fernet-key
# fallback (see connections/crypto.py) does not apply here. Tests that create
# a ConnectorCredential supply a real key via KORPUS_FERNET_KEY instead,
# mirroring connections/tests.py's own pattern.
_FERNET_KEY = Fernet.generate_key().decode("ascii")

User = get_user_model()

_CSV_CONTENT = (
    b"id;name;brand\n"
    b"1;Bela majica;Acme\n"
    b"2;Crna jakna;Acme\n"
)


def _make_org(slug="acme"):
    return Organization.objects.create(name="Acme", slug=slug)


def _make_user(username="uploader"):
    return User.objects.create_user(username=username, password="pw")


def _make_uploaded_batch(org, user=None, **kwargs):
    kwargs.setdefault("provider", Batch.Provider.FAKE)
    batch = Batch.objects.create(
        organization=org, name="Test batch", created_by=user, **kwargs
    )
    batch.source_file.save("catalog.csv", ContentFile(_CSV_CONTENT), save=True)
    return batch


class RunGenerationTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(MEDIA_ROOT=Path(self._tmp.name))
        override.enable()
        self.addCleanup(override.disable)

        self.org = _make_org()
        self.user = _make_user()

    def test_run_generation_completes_and_creates_review_items(self):
        batch = _make_uploaded_batch(self.org, self.user)

        tasks.run_generation(batch.pk)

        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        self.assertEqual(batch.total_count, 2)
        self.assertEqual(batch.error_log, "")
        self.assertIsNotNone(batch.finished_at)

        items = list(ReviewItem.objects.filter(batch=batch).order_by("product_id"))
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertTrue(item.cirilica.strip())
            self.assertTrue(item.latinica.strip())
            self.assertIn("is_clean", item.provenance)
            self.assertIn("entries", item.provenance)
            self.assertTrue(item.attributes)  # grounded attributes carried through
            self.assertEqual(item.status, ReviewItem.Status.PENDING)

        self.assertEqual(
            batch.needs_review_count, sum(1 for item in items if item.needs_review)
        )

        artifacts_dir = batch.artifacts_dir
        self.assertTrue((artifacts_dir / "descriptions.csv").exists())
        provenance_dir = artifacts_dir / "provenance"
        self.assertTrue(provenance_dir.exists())
        self.assertEqual(len(list(provenance_dir.glob("*.json"))), 2)

        log = AuditLog.objects.get(action=AuditLog.Action.GENERATE, batch=batch)
        self.assertEqual(log.actor, self.user)
        self.assertEqual(log.detail["total_count"], 2)

    def test_run_generation_bad_file_marks_failed_without_crashing(self):
        batch = Batch.objects.create(
            organization=self.org, name="Bad batch", provider=Batch.Provider.FAKE
        )
        batch.source_file.save(
            "catalog.unsupported", ContentFile(b"not a real catalog"), save=True
        )

        tasks.run_generation(batch.pk)  # must not raise

        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.FAILED)
        self.assertTrue(batch.error_log)
        self.assertIsNotNone(batch.finished_at)
        self.assertEqual(ReviewItem.objects.filter(batch=batch).count(), 0)

    def test_run_generation_no_secrets_in_error_log(self):
        # provider="fake" never touches an API key at all; assert the
        # structural guarantee holds even so.
        batch = Batch.objects.create(
            organization=self.org, name="Bad batch", provider=Batch.Provider.FAKE
        )
        batch.source_file.save(
            "catalog.unsupported", ContentFile(b"not a real catalog"), save=True
        )
        tasks.run_generation(batch.pk)
        batch.refresh_from_db()
        self.assertNotIn("ANTHROPIC_API_KEY", batch.error_log)
        self.assertNotIn("sk-ant-", batch.error_log)

    def test_run_generation_twice_second_call_is_a_noop(self):
        batch = _make_uploaded_batch(self.org, self.user)
        tasks.run_generation(batch.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        finished_at_first = batch.finished_at
        item_count_first = ReviewItem.objects.filter(batch=batch).count()

        tasks.run_generation(batch.pk)  # no-op: batch is no longer UPLOADED

        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        self.assertEqual(batch.finished_at, finished_at_first)
        self.assertEqual(ReviewItem.objects.filter(batch=batch).count(), item_count_first)


class _RecordingConnector:
    """Fake WooCommerceConnector: succeeds for one product_id, raises for
    another ("fail-1"), and records every push_description call. Used to
    monkeypatch `tasks.WooCommerceConnector` -- no network, no real store.
    """

    def __init__(self, *, base_url=None, consumer_key=None, consumer_secret=None):
        self.base_url = base_url
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.calls = []

    def push_description(self, product_id, dual, *, publish_script=Script.LATINICA):
        self.calls.append((product_id, dual, publish_script))
        if product_id == "fail-1":
            raise RuntimeError("store returned 500")


class PublishBatchTests(TestCase):
    def setUp(self):
        # patch.dict as a class decorator only wraps test_* methods, not
        # setUp -- and credential creation (which encrypts) happens here, so
        # patch the env manually and restore it via addCleanup instead.
        patcher = mock.patch.dict("os.environ", {"KORPUS_FERNET_KEY": _FERNET_KEY})
        patcher.start()
        self.addCleanup(patcher.stop)

        self.org = _make_org()
        self.other_org = _make_org(slug="other")
        self.user = _make_user()
        self.batch = Batch.objects.create(organization=self.org, name="Publish batch")

        self.approved_ok = ReviewItem.objects.create(
            batch=self.batch,
            product_id="ok-1",
            cirilica="Ћирилица",
            latinica="Latinica",
            status=ReviewItem.Status.APPROVED,
        )
        self.approved_fail = ReviewItem.objects.create(
            batch=self.batch,
            product_id="fail-1",
            cirilica="Ћирилица2",
            latinica="Latinica2",
            status=ReviewItem.Status.APPROVED,
        )
        self.pending = ReviewItem.objects.create(
            batch=self.batch,
            product_id="pending-1",
            cirilica="C",
            latinica="L",
            status=ReviewItem.Status.PENDING,
        )
        self.rejected = ReviewItem.objects.create(
            batch=self.batch,
            product_id="rejected-1",
            cirilica="C",
            latinica="L",
            status=ReviewItem.Status.REJECTED,
            reason="no",
        )

        self.credential = ConnectorCredential.objects.create(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Shop",
            base_url="https://shop.example.com",
        )
        self.credential.set_consumer_key("ck-plaintext")
        self.credential.set_consumer_secret("s3cr3t-consumer-secret")
        self.credential.save()

    def test_publish_batch_mixed_success_and_failure(self):
        with mock.patch.object(tasks, "WooCommerceConnector", _RecordingConnector):
            result = tasks.publish_batch(
                self.batch.pk, self.credential.pk, "latinica", self.user.pk
            )

        self.assertEqual(result, {"published": 1, "failed": 1, "skipped": 2})

        self.approved_ok.refresh_from_db()
        self.assertEqual(self.approved_ok.status, ReviewItem.Status.PUBLISHED)
        self.assertIsNotNone(self.approved_ok.published_at)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.PUBLISH, product_id="ok-1", batch=self.batch
            ).exists()
        )

        self.approved_fail.refresh_from_db()
        self.assertEqual(self.approved_fail.status, ReviewItem.Status.APPROVED)
        self.assertTrue(self.approved_fail.publish_error)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.PUBLISH_FAILED,
                product_id="fail-1",
                batch=self.batch,
            ).exists()
        )

        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, ReviewItem.Status.PENDING)
        self.rejected.refresh_from_db()
        self.assertEqual(self.rejected.status, ReviewItem.Status.REJECTED)

    def test_publish_batch_credential_org_mismatch(self):
        other_credential = ConnectorCredential.objects.create(
            organization=self.other_org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Other shop",
            base_url="https://other.example.com",
        )
        other_credential.set_consumer_key("ck")
        other_credential.save()

        with mock.patch.object(tasks, "WooCommerceConnector", _RecordingConnector):
            result = tasks.publish_batch(
                self.batch.pk, other_credential.pk, "latinica", self.user.pk
            )

        self.assertEqual(result["published"], 0)
        self.approved_ok.refresh_from_db()
        self.assertEqual(self.approved_ok.status, ReviewItem.Status.APPROVED)
        log = AuditLog.objects.get(action=AuditLog.Action.PUBLISH_FAILED, batch=self.batch)
        self.assertEqual(log.detail, {"reason": "credential org mismatch"})

    def test_publish_batch_selltico_connector_not_implemented(self):
        selltico_credential = ConnectorCredential.objects.create(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.SELLTICO,
            label="Selltico store",
            base_url="https://selltico.example.com",
        )
        selltico_credential.set_consumer_key("ck")
        selltico_credential.save()

        with mock.patch.object(tasks, "WooCommerceConnector", _RecordingConnector):
            result = tasks.publish_batch(
                self.batch.pk, selltico_credential.pk, "latinica", self.user.pk
            )

        self.assertEqual(result, {"published": 0, "failed": 0, "skipped": 0})
        self.approved_ok.refresh_from_db()
        self.assertEqual(self.approved_ok.status, ReviewItem.Status.APPROVED)
        logs = AuditLog.objects.filter(action=AuditLog.Action.PUBLISH_FAILED, batch=self.batch)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().detail["reason"], "connector not implemented")

    def test_publish_batch_no_secrets_leak_into_audit_or_publish_error(self):
        with mock.patch.object(tasks, "WooCommerceConnector", _RecordingConnector):
            tasks.publish_batch(self.batch.pk, self.credential.pk, "latinica", self.user.pk)

        secret = "s3cr3t-consumer-secret"
        for log in AuditLog.objects.filter(batch=self.batch):
            self.assertNotIn(secret, str(log.detail))
        self.approved_fail.refresh_from_db()
        self.assertNotIn(secret, self.approved_fail.publish_error)

    def test_publish_batch_credential_not_found(self):
        with mock.patch.object(tasks, "WooCommerceConnector", _RecordingConnector):
            result = tasks.publish_batch(self.batch.pk, 999_999, "latinica", self.user.pk)

        self.assertEqual(result, {"published": 0, "failed": 0, "skipped": 0})
        self.approved_ok.refresh_from_db()
        self.assertEqual(self.approved_ok.status, ReviewItem.Status.APPROVED)
