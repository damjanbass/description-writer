from common.org import OrgMembershipRequiredMixin
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.views.generic import View

from .models import Membership, Organization

User = get_user_model()


class MembershipUniquenessTests(TestCase):
    def test_duplicate_user_organization_raises_integrity_error(self):
        user = User.objects.create_user(username="alice", password="pw12345!")
        org = Organization.objects.create(name="Acme", slug="acme")
        Membership.objects.create(user=user, organization=org)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(user=user, organization=org)


class _ProbeView(OrgMembershipRequiredMixin, View):
    """Throwaway view used to exercise OrgMembershipRequiredMixin.dispatch()
    directly, without needing a full ListView/TemplateView + URLconf."""

    def dispatch(self, request, *args, **kwargs):
        super().dispatch(request, *args, **kwargs)
        return HttpResponse(f"org={self.org.slug}")


class OrgMembershipRequiredMixinTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.org = Organization.objects.create(name="Acme", slug="acme")

    def _call(self, user):
        request = self.factory.get(f"/whatever/{self.org.slug}/")
        request.user = user
        return _ProbeView.as_view()(request, org_slug=self.org.slug)

    def test_member_gets_200_and_org_set(self):
        user = User.objects.create_user(username="member", password="pw12345!")
        Membership.objects.create(user=user, organization=self.org)

        response = self._call(user)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "org=acme")

    def test_non_member_gets_404(self):
        user = User.objects.create_user(username="stranger", password="pw12345!")

        with self.assertRaises(Http404):
            self._call(user)

    def test_staff_non_member_gets_200(self):
        user = User.objects.create_user(
            username="staffer", password="pw12345!", is_staff=True
        )

        response = self._call(user)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "org=acme")

    def test_unknown_org_slug_gets_404(self):
        user = User.objects.create_user(
            username="staffer2", password="pw12345!", is_staff=True
        )
        request = self.factory.get("/whatever/does-not-exist/")
        request.user = user

        with self.assertRaises(Http404):
            _ProbeView.as_view()(request, org_slug="does-not-exist")


class HomeViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme Corp", slug="acme-corp")

    def test_member_sees_their_org(self):
        user = User.objects.create_user(username="member", password="pw12345!")
        Membership.objects.create(user=user, organization=self.org)
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Acme Corp")

    def test_staff_sees_all_orgs(self):
        Organization.objects.create(name="Other Org", slug="other-org")
        staff = User.objects.create_user(
            username="staff", password="pw12345!", is_staff=True
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Acme Corp")
        self.assertContains(response, "Other Org")

    def test_user_with_no_orgs_sees_empty_state(self):
        user = User.objects.create_user(username="lonely", password="pw12345!")
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Nemate još nijednu organizaciju. Kontaktirajte administratora."
        )
        self.assertNotContains(response, "Acme Corp")


class MembershipAdminInviteActionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.admin_user = User.objects.create_superuser(
            username="root", password="pw12345!", email="root@example.com"
        )
        self.target_user = User.objects.create_user(
            username="invitee", password="pw12345!", email="invitee@example.com"
        )
        self.membership = Membership.objects.create(
            user=self.target_user, organization=self.org
        )
        self.client.force_login(self.admin_user)

    def test_send_password_setup_link_sends_one_email(self):
        response = self.client.post(
            reverse("admin:accounts_membership_changelist"),
            {
                "action": "send_password_setup_link",
                "_selected_action": [str(self.membership.pk)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("invitee@example.com", mail.outbox[0].to)

    def test_user_without_email_is_skipped(self):
        no_email_user = User.objects.create_user(username="noemail", password="pw12345!")
        no_email_user.email = ""
        no_email_user.save()
        membership = Membership.objects.create(
            user=no_email_user, organization=self.org
        )

        response = self.client.post(
            reverse("admin:accounts_membership_changelist"),
            {
                "action": "send_password_setup_link",
                "_selected_action": [str(membership.pk)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
