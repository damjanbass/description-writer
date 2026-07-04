"""Views for the accounts app."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from .models import Organization


class HomeView(LoginRequiredMixin, TemplateView):
    """Landing page after login: lists the organizations the user belongs
    to (or every organization, for staff users).

    A non-staff user with exactly one organization skips this screen and
    lands directly in that org's batch list -- the org picker only earns
    its place when there is actually a choice to make.
    """

    template_name = "home.html"

    def get(self, request, *args, **kwargs):
        if not request.user.is_staff:
            slugs = list(
                request.user.memberships.values_list("organization__slug", flat=True)
            )
            if len(slugs) == 1:
                return redirect("batches:list", org_slug=slugs[0])
        return super().get(request, *args, **kwargs)

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
