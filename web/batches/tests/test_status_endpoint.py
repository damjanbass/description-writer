"""Tests for BatchStatusView (GET /app/<org>/batches/<pk>/status.json):
the batch detail page's progress feed, and -- more importantly -- the stall
backstop that makes chunked execution self-healing without any cron: a
RUNNING batch with a stale progress heartbeat, or an UPLOADED batch whose
initial dispatch evidently got lost, is re-dispatched server-side on any
poll.

Timestamps are backdated via queryset .update() (created_at is
auto_now_add; last_progress_at is task-managed) -- no freezegun dependency.
"""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from accounts.models import Membership, Organization
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from batches.models import Batch, ReviewItem

User = get_user_model()


class BatchStatusEndpointTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.other_org = Organization.objects.create(name="Umbrella", slug="umbrella")
        self.member = User.objects.create_user(username="member", password="pw")
        Membership.objects.create(user=self.member, organization=self.org)
        self.outsider = User.objects.create_user(username="outsider", password="pw")
        Membership.objects.create(user=self.outsider, organization=self.other_org)

        self.batch = Batch.objects.create(
            organization=self.org, name="Test batch", total_count=5
        )

    def _url(self):
        return reverse(
            "batches:status", kwargs={"org_slug": self.org.slug, "pk": self.batch.pk}
        )

    def _get(self):
        return self.client.get(self._url())

    def _backdate(self, **fields):
        Batch.objects.filter(pk=self.batch.pk).update(**fields)

    # ---- auth / tenancy -------------------------------------------------

    def test_anonymous_is_redirected_to_login(self):
        response = self._get()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/app/login/", response["Location"])

    def test_non_member_gets_404(self):
        # 404, never 403: org existence is not revealed (common/org.py).
        self.client.force_login(self.outsider)
        self.assertEqual(self._get().status_code, 404)

    # ---- payload ---------------------------------------------------------

    def test_payload_shape(self):
        ReviewItem.objects.create(
            batch=self.batch,
            product_id="1",
            cirilica="Ћ",
            latinica="L",
            needs_review=True,
        )
        self._backdate(status=Batch.Status.COMPLETED)
        self.client.force_login(self.member)

        data = self._get().json()

        self.assertEqual(
            data,
            {
                "status": "completed",
                "total_count": 5,
                "done": 1,
                "needs_review_count": 1,
                "has_errors": False,
                "rekicked": False,
            },
        )

    # ---- stall backstop --------------------------------------------------

    def test_stale_running_batch_is_rekicked(self):
        self._backdate(
            status=Batch.Status.RUNNING,
            last_progress_at=timezone.now() - timedelta(minutes=3),
        )
        self.client.force_login(self.member)

        with mock.patch("batches.views.dispatch") as dispatch:
            data = self._get().json()

        self.assertTrue(data["rekicked"])
        dispatch.assert_called_once_with(
            "batches.tasks.run_generation", self.batch.pk
        )

    def test_fresh_running_batch_is_not_rekicked(self):
        self._backdate(
            status=Batch.Status.RUNNING, last_progress_at=timezone.now()
        )
        self.client.force_login(self.member)

        with mock.patch("batches.views.dispatch") as dispatch:
            data = self._get().json()

        self.assertFalse(data["rekicked"])
        dispatch.assert_not_called()

    def test_running_without_heartbeat_falls_back_to_created_at(self):
        # A chunk that crashed before its first progress write leaves
        # last_progress_at NULL; staleness is then judged off created_at.
        self._backdate(
            status=Batch.Status.RUNNING,
            last_progress_at=None,
            created_at=timezone.now() - timedelta(minutes=3),
        )
        self.client.force_login(self.member)

        with mock.patch("batches.views.dispatch") as dispatch:
            data = self._get().json()

        self.assertTrue(data["rekicked"])
        dispatch.assert_called_once()

    def test_stale_uploaded_batch_is_rekicked(self):
        # The initial dispatch got lost (e.g. QStash publish failed after
        # the upload response): any poll resurrects the run.
        self._backdate(created_at=timezone.now() - timedelta(minutes=2))
        self.client.force_login(self.member)

        with mock.patch("batches.views.dispatch") as dispatch:
            data = self._get().json()

        self.assertTrue(data["rekicked"])
        dispatch.assert_called_once_with(
            "batches.tasks.run_generation", self.batch.pk
        )

    def test_fresh_uploaded_batch_is_not_rekicked(self):
        # Just uploaded: the legitimate first dispatch is still in flight.
        self.client.force_login(self.member)

        with mock.patch("batches.views.dispatch") as dispatch:
            data = self._get().json()

        self.assertFalse(data["rekicked"])
        dispatch.assert_not_called()

    def test_completed_batch_is_never_rekicked(self):
        self._backdate(
            status=Batch.Status.COMPLETED,
            created_at=timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.member)

        with mock.patch("batches.views.dispatch") as dispatch:
            data = self._get().json()

        self.assertFalse(data["rekicked"])
        dispatch.assert_not_called()
