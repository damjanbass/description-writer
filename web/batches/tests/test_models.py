"""Tests for batches.models: ReviewItem status-guard semantics (mirroring
pipeline.review.ReviewQueue's approve/reject/mark_published guards) and the
append-only AuditLog trail each transition writes.
"""
from __future__ import annotations

from accounts.models import Organization
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from batches.models import AuditLog, Batch, ReviewItem

User = get_user_model()


def _make_org(slug="acme"):
    return Organization.objects.create(name="Acme", slug=slug)


def _make_user(username="reviewer"):
    return User.objects.create_user(username=username, password="pw")


def _make_batch(org, **kwargs):
    kwargs.setdefault("name", "Test batch")
    kwargs.setdefault("source_file", "orgs/acme/batches/test.csv")
    return Batch.objects.create(organization=org, **kwargs)


def _make_item(batch, product_id="p1", status=ReviewItem.Status.PENDING, **kwargs):
    kwargs.setdefault("cirilica", "Ћирилица опис")
    kwargs.setdefault("latinica", "Latinica opis")
    return ReviewItem.objects.create(
        batch=batch, product_id=product_id, status=status, **kwargs
    )


class ReviewItemApproveTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.user = _make_user()
        self.batch = _make_batch(self.org)

    def test_approve_from_pending_sets_status_and_audit_log(self):
        item = _make_item(self.batch)
        item.approve(self.user)
        item.refresh_from_db()
        self.assertEqual(item.status, ReviewItem.Status.APPROVED)
        self.assertEqual(item.decided_by, self.user)
        self.assertIsNotNone(item.decided_at)

        log = AuditLog.objects.get(action=AuditLog.Action.APPROVE)
        self.assertEqual(log.organization, self.org)
        self.assertEqual(log.actor, self.user)
        self.assertEqual(log.batch, self.batch)
        self.assertEqual(log.product_id, item.product_id)

    def test_approve_clears_prior_reason_and_publish_error(self):
        item = _make_item(
            self.batch,
            status=ReviewItem.Status.REJECTED,
            reason="Bad copy",
            publish_error="boom: connection refused",
        )
        item.approve(self.user)
        item.refresh_from_db()
        self.assertEqual(item.reason, "")
        self.assertEqual(item.publish_error, "")

    def test_approve_from_rejected_is_allowed(self):
        item = _make_item(self.batch, status=ReviewItem.Status.REJECTED, reason="x")
        item.approve(self.user)  # should not raise
        item.refresh_from_db()
        self.assertEqual(item.status, ReviewItem.Status.APPROVED)

    def test_approve_on_published_raises_and_leaves_state_untouched(self):
        item = _make_item(self.batch, status=ReviewItem.Status.PUBLISHED)
        with self.assertRaises(ValidationError):
            item.approve(self.user)
        item.refresh_from_db()
        self.assertEqual(item.status, ReviewItem.Status.PUBLISHED)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.APPROVE).exists())


class ReviewItemRejectTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.user = _make_user()
        self.batch = _make_batch(self.org)

    def test_reject_requires_non_empty_reason(self):
        item = _make_item(self.batch)
        with self.assertRaises(ValidationError):
            item.reject(self.user, "")
        with self.assertRaises(ValidationError):
            item.reject(self.user, "   ")
        item.refresh_from_db()
        self.assertEqual(item.status, ReviewItem.Status.PENDING)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.REJECT).exists())

    def test_reject_with_reason_sets_status_and_audit_log(self):
        item = _make_item(self.batch)
        item.reject(self.user, "Missing attributes")
        item.refresh_from_db()
        self.assertEqual(item.status, ReviewItem.Status.REJECTED)
        self.assertEqual(item.reason, "Missing attributes")
        self.assertEqual(item.decided_by, self.user)

        log = AuditLog.objects.get(action=AuditLog.Action.REJECT)
        self.assertEqual(log.detail, {"reason": "Missing attributes"})
        self.assertEqual(log.organization, self.org)

    def test_reject_on_published_raises(self):
        item = _make_item(self.batch, status=ReviewItem.Status.PUBLISHED)
        with self.assertRaises(ValidationError):
            item.reject(self.user, "too late")


class ReviewItemMarkPublishedTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.batch = _make_batch(self.org)

    def test_mark_published_from_pending_raises(self):
        item = _make_item(self.batch, status=ReviewItem.Status.PENDING)
        with self.assertRaises(ValidationError):
            item.mark_published()
        item.refresh_from_db()
        self.assertEqual(item.status, ReviewItem.Status.PENDING)

    def test_mark_published_from_rejected_raises(self):
        item = _make_item(self.batch, status=ReviewItem.Status.REJECTED)
        with self.assertRaises(ValidationError):
            item.mark_published()

    def test_mark_published_from_approved_succeeds_and_audit_logs(self):
        item = _make_item(self.batch, status=ReviewItem.Status.APPROVED)
        item.mark_published()
        item.refresh_from_db()
        self.assertEqual(item.status, ReviewItem.Status.PUBLISHED)
        self.assertIsNotNone(item.published_at)

        log = AuditLog.objects.get(action=AuditLog.Action.PUBLISH)
        self.assertEqual(log.organization, self.org)
        self.assertEqual(log.batch, self.batch)
        self.assertEqual(log.product_id, item.product_id)

    def test_mark_published_from_published_raises(self):
        item = _make_item(self.batch, status=ReviewItem.Status.PUBLISHED)
        with self.assertRaises(ValidationError):
            item.mark_published()


class ReviewItemUniqueConstraintTests(TestCase):
    def test_unique_batch_product_id(self):
        org = _make_org()
        batch = _make_batch(org)
        _make_item(batch, product_id="dup")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                _make_item(batch, product_id="dup")

    def test_same_product_id_in_different_batch_is_allowed(self):
        org = _make_org()
        batch_a = _make_batch(org, name="A")
        batch_b = _make_batch(org, name="B")
        _make_item(batch_a, product_id="shared")
        _make_item(batch_b, product_id="shared")  # should not raise


class BatchModelTests(TestCase):
    def test_default_status_and_ordering(self):
        org = _make_org()
        batch = _make_batch(org, name="First")
        self.assertEqual(batch.status, Batch.Status.UPLOADED)
        # Ordering is asserted on Meta directly (not by comparing timestamps
        # of two batches created microseconds apart, which is flaky under
        # sqlite's timestamp resolution).
        self.assertEqual(Batch._meta.ordering, ["-created_at"])
