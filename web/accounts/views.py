"""Views for the accounts app."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .models import Organization


class HomeView(LoginRequiredMixin, TemplateView):
    """Landing page after login: lists the organizations the user belongs
    to (or every organization, for staff users)."""

    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user = self.request.user
        role_by_org_id = {
            membership.organization_id: membership.role
            for membership in user.memberships.all()
        }

        if user.is_staff:
            orgs = list(Organization.objects.all())
        else:
            orgs = list(
                Organization.objects.filter(id__in=role_by_org_id.keys())
            )

        for org in orgs:
            org.user_role = role_by_org_id.get(org.id)

        context["orgs"] = orgs
        return context
