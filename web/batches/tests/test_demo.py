"""Tests for the one-click demo data: batches.demo, the seed_demo command,
and DemoSeedView."""
from __future__ import annotations

import tempfile
from io import StringIO
from pathlib import Path

from accounts.models import Membership, Organization
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from batches.demo import SAMPLE_CSV_PATH, seed_demo_batch
from batches.models import AuditLog, Batch, ReviewItem

User = get_user_model()

_TMP_MEDIA = tempfile.mkdtemp(prefix="korpus-test-demo-media-")


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class SeedDemoBatchTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.user = User.objects.create_user(username="member", password="pw")
        Membership.objects.create(user=self.user, organization=self.org)

    def test_creates_full_status_mix(self):
        batch = seed_demo_batch(self.org, self.user)

        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        self.assertGreaterEqual(batch.items.count(), 8)

        by_status = {
            status: batch.items.filter(status=status).count()
            for status in ReviewItem.Status.values
        }
        self.assertEqual(by_status["approved"], 2)
        self.assertEqual(by_status["rejected"], 1)
        self.assertEqual(by_status["published"], 1)
        self.assertGreaterEqual(by_status["pending"], 4)

        published = batch.items.get(status=ReviewItem.Status.PUBLISHED)
        self.assertIsNotNone(published.published_at)

        rejected = batch.items.get(status=ReviewItem.Status.REJECTED)
        self.assertIn("Primer odbijene stavke", rejected.reason)

        flagged = batch.items.filter(
            status=ReviewItem.Status.PENDING, needs_review=True
        )
        self.assertTrue(flagged.exists())
        entries = flagged.first().provenance["entries"]
        self.assertTrue(any(not entry["supported"] for entry in entries))

    def test_audit_rows_exist_for_every_transition(self):
        batch = seed_demo_batch(self.org, self.user)
        actions = set(
            AuditLog.objects.filter(batch=batch).values_list("action", flat=True)
        )
        self.assertLessEqual({"generate", "approve", "reject", "publish"}, actions)

    def test_source_file_matches_downloadable_sample(self):
        batch = seed_demo_batch(self.org, self.user)
        with batch.source_file.open("rb") as stored:
            self.assertEqual(stored.read(), SAMPLE_CSV_PATH.read_bytes())

    def test_repeated_seeding_gets_unique_names(self):
        first = seed_demo_batch(self.org, self.user)
        second = seed_demo_batch(self.org, self.user)
        self.assertNotEqual(first.name, second.name)

    def test_management_command(self):
        User.objects.create_superuser("root", "root@x.rs", "pw")
        out = StringIO()
        call_command("seed_demo", self.org.slug, stdout=out)
        self.assertIn("Demo serija", out.getvalue())
        self.assertTrue(Batch.objects.filter(organization=self.org).exists())

    def test_sample_csv_is_in_static(self):
        self.assertTrue(SAMPLE_CSV_PATH.exists())
        self.assertEqual(SAMPLE_CSV_PATH.name, "korpus-primer.csv")
        self.assertIn("samples", SAMPLE_CSV_PATH.parts)
        self.assertEqual(Path(SAMPLE_CSV_PATH).suffix, ".csv")


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class DemoSeedViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.other_org = Organization.objects.create(name="Umbrella", slug="umbrella")
        self.member = User.objects.create_user(username="member", password="pw")
        Membership.objects.create(user=self.member, organization=self.org)
        self.outsider = User.objects.create_user(username="outsider", password="pw")
        Membership.objects.create(user=self.outsider, organization=self.other_org)
        self.url = reverse("batches:demo", kwargs={"org_slug": self.org.slug})

    def test_member_post_creates_batch_and_redirects(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url)
        batch = Batch.objects.get(organization=self.org)
        self.assertRedirects(
            response,
            reverse(
                "batches:detail",
                kwargs={"org_slug": self.org.slug, "pk": batch.pk},
            ),
            fetch_redirect_response=False,
        )

    def test_outsider_gets_404(self):
        self.client.force_login(self.outsider)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Batch.objects.filter(organization=self.org).exists())

    def test_get_not_allowed(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
