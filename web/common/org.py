"""
Shared org-scoping helpers for class-based views.

`accounts.models` (Organization, Membership) is owned by task 3B and is
being built in parallel, so this module must not import it at module load
time — that would create an import-order race between apps. Models are
resolved lazily via django.apps.apps.get_model() inside dispatch(), once
Django's app registry is fully populated.
"""
from django.apps import apps
from django.http import Http404
from django.shortcuts import get_object_or_404


class OrgMembershipRequiredMixin:
    """
    Mixin for class-based views that live under an `org_slug` URL kwarg.

    On dispatch, resolves `org_slug` to an `Organization` (404 if it doesn't
    exist), then checks that the requesting user is allowed to see it:
    either `request.user.is_staff`, or an `accounts.Membership` linking the
    user to that org exists. If neither holds, raises `Http404` (NOT
    `PermissionDenied`/403) — we don't want to leak the existence of an org
    slug to users who aren't members of it.

    On success, sets `self.org` to the resolved Organization so subclasses
    can use it directly (e.g. in get_queryset / get_context_data).

    Usage:

        class LeadListView(OrgMembershipRequiredMixin, ListView):
            model = Lead

            def get_queryset(self):
                # self.org is set by OrgMembershipRequiredMixin.dispatch()
                # before get_queryset() ever runs.
                return super().get_queryset().filter(organization=self.org)

    Combine with `LoginRequiredMixin` (put it first in the MRO) so
    anonymous users get redirected to login rather than hitting the 404
    membership check as an unauthenticated user:

        class LeadListView(LoginRequiredMixin, OrgMembershipRequiredMixin, ListView):
            ...
    """

    org_slug_url_kwarg = "org_slug"

    def dispatch(self, request, *args, **kwargs):
        Organization = apps.get_model("accounts", "Organization")
        Membership = apps.get_model("accounts", "Membership")

        org_slug = kwargs.get(self.org_slug_url_kwarg)
        self.org = get_object_or_404(Organization, slug=org_slug)

        is_member = request.user.is_staff or Membership.objects.filter(
            user=request.user, organization=self.org
        ).exists()
        if not is_member:
            # 404, not 403: don't reveal that this org slug exists to
            # non-members.
            raise Http404("No organization found matching the query")

        return super().dispatch(request, *args, **kwargs)
