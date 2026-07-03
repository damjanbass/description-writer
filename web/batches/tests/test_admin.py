"""Tests for batches/admin.py.

Covers the "admin is a browsing/audit surface, not an authoring one"
contract laid out in admin.py's module docstring: Batch/AuditLog can't be
added from admin, ReviewItem's change page renders but can never actually
move a status (that's exclusively the job of ReviewItem.approve/reject/
mark_published), AuditLog can't be changed or deleted, and the Korpus brand
pass on admin/base_site.html is present.
"""
from __future__ import annotations

from accounts.models import Membership, Organization
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from batches.models import AuditLog, Batch, ReviewItem

User = get_user_model()


def _make_org(slug="acme"):
    return Organization.objects.create(name="Acme", slug=slug)


def _make_batch(org, **kwargs):
    kwargs.setdefault("name", "Test batch")
    kwargs.setdefault("source_file", "orgs/acme/batches/test.csv")
    return Batch.objects.create(organization=org, **kwargs)


def _make_item(batch, product_id="p1", **kwargs):
    kwargs.setdefault("cirilica", "Ћирилица опис")
    kwargs.setdefault("latinica", "Latinica opis")
    kwargs.setdefault("status", ReviewItem.Status.PENDING)
    return ReviewItem.objects.create(batch=batch, product_id=product_id, **kwargs)


class BatchAdminTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.staff = User.objects.create_superuser(
            username="staff", password="pw12345!", email="staff@example.com"
        )
        self.client.force_login(self.staff)

    def test_changelist_200(self):
        _make_batch(self.org)
        response = self.client.get(reverse("admin:batches_batch_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_add_view_is_403(self):
        response = self.client.get(reverse("admin:batches_batch_add"))
        self.assertEqual(response.status_code, 403)


class ReviewItemAdminTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.staff = User.objects.create_superuser(
            username="staff", password="pw12345!", email="staff@example.com"
        )
        self.client.force_login(self.staff)
        self.batch = _make_batch(self.org)
        self.item = _make_item(self.batch)

    def test_change_page_is_200(self):
        response = self.client.get(
            reverse("admin:batches_reviewitem_change", args=[self.item.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_post_to_change_page_does_not_alter_status(self):
        url = reverse("admin:batches_reviewitem_change", args=[self.item.pk])
        response = self.client.post(
            url,
            {
                "status": ReviewItem.Status.PUBLISHED,
                "needs_review": "on",
                "product_id": "hijacked",
            },
        )
        # Whatever the response looks like, the underlying row must be
        # untouched -- that's the actual guarantee under test.
        self.assertNotEqual(response.status_code, 500)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ReviewItem.Status.PENDING)
        self.assertEqual(self.item.product_id, "p1")
        self.assertFalse(self.item.needs_review)

    def test_add_view_is_403(self):
        response = self.client.get(reverse("admin:batches_reviewitem_add"))
        self.assertEqual(response.status_code, 403)

    def test_delete_view_is_403(self):
        response = self.client.get(
            reverse("admin:batches_reviewitem_delete", args=[self.item.pk])
        )
        self.assertEqual(response.status_code, 403)


class AuditLogAdminTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.staff = User.objects.create_superuser(
            username="staff", password="pw12345!", email="staff@example.com"
        )
        self.client.force_login(self.staff)
        self.batch = _make_batch(self.org)
        self.log = AuditLog.objects.create(
            organization=self.org,
            action=AuditLog.Action.UPLOAD,
            batch=self.batch,
            product_id="p1",
        )

    def test_changelist_200(self):
        response = self.client.get(reverse("admin:batches_auditlog_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_add_view_is_403(self):
        response = self.client.get(reverse("admin:batches_auditlog_add"))
        self.assertEqual(response.status_code, 403)

    def test_delete_view_is_403(self):
        response = self.client.get(
            reverse("admin:batches_auditlog_delete", args=[self.log.pk])
        )
        self.assertEqual(response.status_code, 403)


class AdminBrandingTests(TestCase):
    def test_korpus_brand_on_admin_index(self):
        staff = User.objects.create_superuser(
            username="staff", password="pw12345!", email="staff@example.com"
        )
        self.client.force_login(staff)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Korpus admin")


class NonStaffOrgUserAdminAccessTests(TestCase):
    def test_non_staff_user_redirected_to_admin_login(self):
        org = _make_org()
        user = User.objects.create_user(username="member", password="pw12345!")
        Membership.objects.create(user=user, organization=org)
        self.client.force_login(user)

        response = self.client.get(reverse("admin:batches_batch_changelist"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)
