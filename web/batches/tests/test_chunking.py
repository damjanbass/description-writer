"""Tests for chunked/resumable execution in batches.tasks -- the serverless
execution model where a task runs against a wall-clock budget per
invocation and dispatches its own continuation
(settings.KORPUS_TASK_TIME_BUDGET_SECONDS; None = single pass, the dev/VPS
behavior the rest of the suite runs under).

A zero budget forces "expired before the first product", making chunk
boundaries deterministic without patching time. CAUTION baked into every
zero-budget test: `batches.tasks.dispatch` MUST be patched alongside it --
dev's sync dispatch would otherwise recurse into the task forever.
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


def _make_uploaded_batch(org, user=None, content=_CSV_CONTENT, **kwargs):
    kwargs.setdefault("provider", Batch.Provider.FAKE)
    batch = Batch.objects.create(
        organization=org, name="Test batch", created_by=user, **kwargs
    )
    batch.source_file.save("catalog.csv", ContentFile(content), save=True)
    return batch


class _MediaTmpMixin:
    """Per-test MEDIA_ROOT tempdir, mirroring test_tasks.py's setup."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(MEDIA_ROOT=Path(self._tmp.name))
        override.enable()
        self.addCleanup(override.disable)

        self.org = _make_org()
        self.user = _make_user()


class RunGenerationChunkingTests(_MediaTmpMixin, TestCase):
    def test_zero_budget_dispatches_continuation_before_first_product(self):
        batch = _make_uploaded_batch(self.org, self.user)
        with override_settings(KORPUS_TASK_TIME_BUDGET_SECONDS=0):
            with mock.patch("batches.tasks.dispatch") as dispatch:
                tasks.run_generation(batch.pk)

        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.RUNNING)
        self.assertEqual(batch.items.count(), 0)
        # The progress denominator is set before the loop, so the status
        # endpoint can render "obrađeno 0 od 2" from the very first chunk.
        self.assertEqual(batch.total_count, 2)
        self.assertIsNotNone(batch.last_progress_at)
        dispatch.assert_called_once_with("batches.tasks.run_generation", batch.pk)

    def test_continuation_completes_the_batch(self):
        batch = _make_uploaded_batch(self.org, self.user)
        with override_settings(KORPUS_TASK_TIME_BUDGET_SECONDS=0):
            with mock.patch("batches.tasks.dispatch"):
                tasks.run_generation(batch.pk)

        # The continuation (dev default: no budget) finishes the job.
        tasks.run_generation(batch.pk)

        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        self.assertEqual(batch.items.count(), 2)
        self.assertEqual(batch.total_count, 2)
        self.assertIsNotNone(batch.finished_at)
        self.assertEqual(
            batch.needs_review_count,
            batch.items.filter(needs_review=True).count(),
        )
        # Exactly ONE audit row despite two invocations: only the runner
        # that wins the RUNNING -> COMPLETED CAS writes it.
        self.assertEqual(
            AuditLog.objects.filter(
                action=AuditLog.Action.GENERATE, batch=batch
            ).count(),
            1,
        )

    def test_resume_skips_already_generated_products(self):
        batch = _make_uploaded_batch(self.org, self.user)
        # Simulate a crashed chunk that had already generated product "1":
        # rows exist, batch left RUNNING, no continuation ever dispatched.
        ReviewItem.objects.create(
            batch=batch,
            product_id="1",
            cirilica="Постојећи опис.",
            latinica="Postojeći opis.",
            needs_review=False,
        )
        Batch.objects.filter(pk=batch.pk).update(status=Batch.Status.RUNNING)

        tasks.run_generation(batch.pk)

        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        items = {item.product_id: item for item in batch.items.all()}
        self.assertEqual(set(items), {"1", "2"})
        # The pre-existing row was skipped, not regenerated.
        self.assertEqual(items["1"].latinica, "Postojeći opis.")

    def test_duplicate_product_ids_first_record_wins(self):
        content = (
            b"id;name;brand\n"
            b"1;Prva;Acme\n"
            b"1;Druga;Acme\n"
            b"2;Crna jakna;Acme\n"
        )
        batch = _make_uploaded_batch(self.org, self.user, content=content)

        tasks.run_generation(batch.pk)

        batch.refresh_from_db()
        # The old all-at-once bulk_create would have FAILED the whole batch
        # on this input (IntegrityError); chunked creation dedupes instead.
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        self.assertEqual(batch.items.count(), 2)
        self.assertEqual(batch.total_count, 2)
        self.assertEqual(
            batch.items.get(product_id="1").attributes.get("name"), "Prva"
        )


class _AlwaysOkConnector:
    """Fake WooCommerceConnector that succeeds for every product."""

    def __init__(self, *, base_url=None, consumer_key=None, consumer_secret=None):
        pass

    def push_description(self, product_id, dual, *, publish_script=Script.LATINICA):
        pass


class PublishBatchChunkingTests(TestCase):
    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"KORPUS_FERNET_KEY": _FERNET_KEY})
        patcher.start()
        self.addCleanup(patcher.stop)

        self.org = _make_org()
        self.user = _make_user()
        self.batch = Batch.objects.create(organization=self.org, name="Publish batch")
        for product_id in ("a-1", "a-2"):
            ReviewItem.objects.create(
                batch=self.batch,
                product_id=product_id,
                cirilica="Ћ",
                latinica="L",
                status=ReviewItem.Status.APPROVED,
            )

        self.credential = ConnectorCredential.objects.create(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Shop",
            base_url="https://shop.example.com",
        )
        self.credential.set_consumer_key("ck")
        self.credential.set_consumer_secret("cs")
        self.credential.save()

    def test_zero_budget_dispatches_continuation_without_publishing(self):
        with override_settings(KORPUS_TASK_TIME_BUDGET_SECONDS=0):
            with mock.patch("batches.tasks.dispatch") as dispatch:
                with mock.patch.object(
                    tasks, "WooCommerceConnector", _AlwaysOkConnector
                ):
                    result = tasks.publish_batch(
                        self.batch.pk, self.credential.pk, "latinica", self.user.pk
                    )

        self.assertEqual(result["published"], 0)
        dispatch.assert_called_once_with(
            "batches.tasks.publish_batch",
            self.batch.pk,
            self.credential.pk,
            "latinica",
            self.user.pk,
        )
        self.assertEqual(
            self.batch.items.filter(status=ReviewItem.Status.APPROVED).count(), 2
        )

    def test_continuation_publishes_remaining_items(self):
        with override_settings(KORPUS_TASK_TIME_BUDGET_SECONDS=0):
            with mock.patch("batches.tasks.dispatch"):
                with mock.patch.object(
                    tasks, "WooCommerceConnector", _AlwaysOkConnector
                ):
                    tasks.publish_batch(
                        self.batch.pk, self.credential.pk, "latinica", self.user.pk
                    )

        # The continuation (no budget) re-queries what is still APPROVED and
        # finishes -- nothing was lost by the early chunk boundary.
        with mock.patch.object(tasks, "WooCommerceConnector", _AlwaysOkConnector):
            result = tasks.publish_batch(
                self.batch.pk, self.credential.pk, "latinica", self.user.pk
            )

        self.assertEqual(result["published"], 2)
        self.assertEqual(
            self.batch.items.filter(status=ReviewItem.Status.PUBLISHED).count(), 2
        )
