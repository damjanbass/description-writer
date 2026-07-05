"""Views for the batches app: the customer-facing upload / review / publish
UI over the domain in `models.py` / `bridge.py` / `tasks.py`.

Every view inherits `LoginRequiredMixin` + `OrgMembershipRequiredMixin`
(`common.org`) in that order, and every queryset filters by `self.org` --
that is the tenancy boundary for this whole app. `common.org` returns a 404
(not 403) for a non-member, so a user from another organization gets an
identical "not found" response whether the batch/item/credential exists in
their own org or not, which is what the tenancy tests assert.

No bulk-approve anywhere, deliberately: `ItemApproveView` / `ItemRejectView`
operate on exactly one `ReviewItem` per request, under `select_for_update()`,
mirroring the one-decision-at-a-time review discipline `pipeline.review`'s
own DESIGN NOTES describe.
"""
from __future__ import annotations

from datetime import timedelta

from common.org import OrgMembershipRequiredMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, DetailView, FormView, ListView, View
from django_ratelimit.decorators import ratelimit

from .bridge import export_descriptions_csv, export_review_queue_json
from .demo import seed_demo_batch
from .dispatch import dispatch
from .forms import BatchPublishForm, BatchUploadForm
from .models import AuditLog, Batch, ReviewItem

# The artifact "kinds" ArtifactDownloadView can generate (both built from
# ReviewItem rows via bridge.py). Kept as one lookup so the view's dispatch
# and BatchDetailView's "which links to show" logic can't silently drift.
_ARTIFACT_KINDS = {"csv", "queue"}


class BatchListView(LoginRequiredMixin, OrgMembershipRequiredMixin, ListView):
    """All batches for the current org, newest first, paginated 20."""

    model = Batch
    template_name = "batches/batch_list.html"
    context_object_name = "batches"
    paginate_by = 20

    def get_queryset(self):
        return Batch.objects.filter(organization=self.org).order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["org"] = self.org
        return context


@method_decorator(
    ratelimit(key="user", rate="10/h", method="POST", block=False), name="post"
)
class BatchUploadView(LoginRequiredMixin, OrgMembershipRequiredMixin, CreateView):
    """Upload a catalog file, kicking off `batches.tasks.run_generation`.

    POST is rate-limited per user (10 uploads/hour): each upload can trigger
    one LLM call per product, so upload frequency is a spend boundary, not
    just a UX nicety. The per-batch product cap lives in `tasks.py`.
    """

    model = Batch
    form_class = BatchUploadForm
    template_name = "batches/batch_upload.html"

    def post(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            messages.error(
                request,
                "Previše otpremanja u kratkom periodu. Pokušajte ponovo kasnije.",
            )
            return redirect(
                reverse("batches:list", kwargs={"org_slug": self.org.slug})
            )
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["org"] = self.org
        return context

    def form_valid(self, form):
        form.instance.organization = self.org
        form.instance.created_by = self.request.user
        response = super().form_valid(form)  # sets self.object, saves the Batch
        AuditLog.objects.create(
            organization=self.org,
            actor=self.request.user,
            action=AuditLog.Action.UPLOAD,
            batch=self.object,
        )
        dispatch("batches.tasks.run_generation", self.object.pk)
        messages.success(
            self.request, "Serija je otpremljena. Generisanje opisa je pokrenuto."
        )
        return response

    def get_success_url(self):
        return reverse(
            "batches:detail", kwargs={"org_slug": self.org.slug, "pk": self.object.pk}
        )


class DemoSeedView(LoginRequiredMixin, OrgMembershipRequiredMixin, View):
    """One-click demo batch: real pipeline run (fake provider) + a
    demonstrative status mix, so a fresh org can explore every screen
    without preparing a file. Also handy in sales demos.
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        batch = seed_demo_batch(self.org, request.user)
        messages.success(
            request,
            "Demo serija je učitana — slobodno istražite i probajte odobravanje.",
        )
        return redirect("batches:detail", org_slug=self.org.slug, pk=batch.pk)


class BatchDetailView(LoginRequiredMixin, OrgMembershipRequiredMixin, DetailView):
    """One batch: status, per-status counts, item table, artifacts, publish."""

    model = Batch
    template_name = "batches/batch_detail.html"
    context_object_name = "batch"

    def get_object(self, queryset=None):
        return get_object_or_404(Batch, pk=self.kwargs["pk"], organization=self.org)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        batch = self.object

        counts = batch.items.aggregate(
            total=Count("id"),
            pending=Count("id", filter=Q(status=ReviewItem.Status.PENDING)),
            approved=Count("id", filter=Q(status=ReviewItem.Status.APPROVED)),
            rejected=Count("id", filter=Q(status=ReviewItem.Status.REJECTED)),
            published=Count("id", filter=Q(status=ReviewItem.Status.PUBLISHED)),
            needs_review=Count("id", filter=Q(needs_review=True)),
        )

        status_filter = self.request.GET.get("status")
        if status_filter not in ReviewItem.Status.values:
            status_filter = None

        items = batch.items.all()
        if status_filter:
            items = items.filter(status=status_filter)

        needs_review_only = self.request.GET.get("pregled") == "1"
        if needs_review_only:
            items = items.filter(needs_review=True)

        context.update(
            {
                "org": self.org,
                "counts": counts,
                "items": items.order_by("product_id"),
                "status_filter": status_filter,
                "needs_review_only": needs_review_only,
                "status_choices": ReviewItem.Status.choices,
                "can_publish": counts["approved"] > 0,
                "artifacts_ready": batch.status == Batch.Status.COMPLETED,
            }
        )
        return context


class ReviewItemDetailView(LoginRequiredMixin, OrgMembershipRequiredMixin, DetailView):
    """The flagship review screen: one product's dual-script copy side by
    side, its provenance/claims detail, and the approve/reject action bar.
    """

    model = ReviewItem
    template_name = "batches/review_item_detail.html"
    context_object_name = "item"
    pk_url_kwarg = "item_pk"

    def get_queryset(self):
        return ReviewItem.objects.filter(
            batch_id=self.kwargs["pk"], batch__organization=self.org
        ).select_related("batch")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = self.object
        batch = item.batch

        status_filter = self.request.GET.get("status")
        if status_filter not in ReviewItem.Status.values:
            status_filter = None

        siblings = batch.items.all()
        if status_filter:
            siblings = siblings.filter(status=status_filter)
        ordered_ids = list(siblings.order_by("product_id").values_list("pk", flat=True))

        prev_id = next_id = None
        if item.pk in ordered_ids:
            idx = ordered_ids.index(item.pk)
            if idx > 0:
                prev_id = ordered_ids[idx - 1]
            if idx < len(ordered_ids) - 1:
                next_id = ordered_ids[idx + 1]

        provenance = item.provenance or {}
        context.update(
            {
                "batch": batch,
                "org": self.org,
                "status_filter": status_filter,
                "prev_item_id": prev_id,
                "next_item_id": next_id,
                "provenance_entries": provenance.get("entries", []),
                "provenance_is_clean": provenance.get("is_clean"),
                "attributes": sorted(item.attributes.items()) if item.attributes else [],
            }
        )
        return context


class _ItemDecisionView(LoginRequiredMixin, OrgMembershipRequiredMixin, View):
    """Shared plumbing for the approve/reject POST-only endpoints: re-fetch
    the item under a row lock scoped to `self.org`, call the model-level
    transition, and bounce back to the item detail screen either way.
    """

    http_method_names = ["post"]

    def _redirect_to_item(self):
        url = reverse(
            "batches:item",
            kwargs={
                "org_slug": self.org.slug,
                "pk": self.kwargs["pk"],
                "item_pk": self.kwargs["item_pk"],
            },
        )
        status_filter = self.request.POST.get("status_filter")
        if status_filter:
            url = f"{url}?status={status_filter}"
        return redirect(url)

    def _locked_item(self):
        return get_object_or_404(
            ReviewItem.objects.select_for_update(),
            pk=self.kwargs["item_pk"],
            batch_id=self.kwargs["pk"],
            batch__organization=self.org,
        )


class ItemApproveView(_ItemDecisionView):
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            item = self._locked_item()
            try:
                item.approve(request.user)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(request, f"Stavka {item.product_id} je odobrena.")
        return self._redirect_to_item()


class ItemRejectView(_ItemDecisionView):
    def post(self, request, *args, **kwargs):
        reason = request.POST.get("reason", "")
        with transaction.atomic():
            item = self._locked_item()
            try:
                item.reject(request.user, reason)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(request, f"Stavka {item.product_id} je odbijena.")
        return self._redirect_to_item()


class BatchPublishView(LoginRequiredMixin, OrgMembershipRequiredMixin, FormView):
    """Publish every APPROVED item in a batch via one of the org's store
    credentials, running `batches.tasks.publish_batch` as a background task.
    """

    form_class = BatchPublishForm
    template_name = "batches/batch_publish.html"

    def get(self, request, *args, **kwargs):
        self.batch = get_object_or_404(Batch, pk=kwargs["pk"], organization=self.org)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.batch = get_object_or_404(Batch, pk=kwargs["pk"], organization=self.org)
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["org"] = self.org
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["org"] = self.org
        context["batch"] = self.batch
        context["approved_count"] = self.batch.items.filter(
            status=ReviewItem.Status.APPROVED
        ).count()
        return context

    def form_valid(self, form):
        credential = form.cleaned_data["credential"]
        # Belt-and-braces re-assertion: the form's queryset is already scoped
        # to self.org, so this should be unreachable, but a credential from
        # another org must never be trusted against this batch.
        if credential.organization_id != self.org.id:
            form.add_error("credential", "Nevažeći nalog za ovu organizaciju.")
            return self.form_invalid(form)

        dispatch(
            "batches.tasks.publish_batch",
            self.batch.pk,
            credential.pk,
            form.cleaned_data["publish_script"],
            self.request.user.pk,
        )
        messages.info(self.request, "Objavljivanje je pokrenuto.")
        return redirect(
            "batches:detail", org_slug=self.org.slug, pk=self.batch.pk
        )


class ArtifactDownloadView(LoginRequiredMixin, OrgMembershipRequiredMixin, View):
    """Serve a completed batch's downloadable artifacts.

    Both kinds are generated from the `ReviewItem` rows on the fly (see
    bridge.export_descriptions_csv / export_review_queue_json) -- the DB is
    the source of truth for generated copy, and serverless deployments have
    no filesystem artifacts to read anyway. Streaming through the view (not
    MEDIA_URL) keeps the org-membership check on `self.org` in front of
    every download.
    """

    def get(self, request, *args, **kwargs):
        batch = get_object_or_404(Batch, pk=kwargs["pk"], organization=self.org)
        kind = kwargs["kind"]
        if kind not in _ARTIFACT_KINDS:
            raise Http404("Unknown artifact kind.")

        if kind == "csv":
            # Only offered once the batch is terminal-complete: mid-run the
            # rows exist incrementally, and a partial CSV would silently
            # look like the whole catalog.
            if batch.status != Batch.Status.COMPLETED:
                raise Http404("descriptions.csv not yet available.")
            payload = export_descriptions_csv(batch)
            response = HttpResponse(payload, content_type="text/csv")
            response["Content-Disposition"] = (
                'attachment; filename="descriptions.csv"'
            )
            return response

        # kind == "queue"
        payload = export_review_queue_json(batch)
        response = HttpResponse(payload, content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="review_queue.json"'
        return response


# How long a RUNNING batch may go without a progress heartbeat before the
# status endpoint assumes its chunk crashed (never dispatched a
# continuation) and re-kicks it. Generous vs. the per-product LLM latency,
# small vs. a human noticing a stuck batch.
_STALL_AFTER_RUNNING = timedelta(minutes=2)
# How long a batch may sit UPLOADED (dispatch lost before any chunk ran)
# before the same backstop re-dispatches the initial run.
_STALL_AFTER_UPLOADED = timedelta(minutes=1)


class BatchStatusView(LoginRequiredMixin, OrgMembershipRequiredMixin, View):
    """Machine-readable progress for the batch detail page's poller.

    Doubles as the stall backstop that makes chunked execution self-healing
    without any cron: if generation looks stuck -- RUNNING with a stale
    `last_progress_at` heartbeat, or UPLOADED for longer than a dispatch
    could plausibly take -- re-dispatch `run_generation`. Safe to fire
    spuriously: the task's status CAS and per-product idempotency make a
    duplicate runner harmless (see tasks.py's module docstring).
    """

    def get(self, request, *args, **kwargs):
        batch = get_object_or_404(Batch, pk=kwargs["pk"], organization=self.org)

        rekicked = False
        now = timezone.now()
        if batch.status == Batch.Status.RUNNING:
            heartbeat = batch.last_progress_at or batch.created_at
            if heartbeat < now - _STALL_AFTER_RUNNING:
                dispatch("batches.tasks.run_generation", batch.pk)
                rekicked = True
        elif batch.status == Batch.Status.UPLOADED:
            if batch.created_at < now - _STALL_AFTER_UPLOADED:
                dispatch("batches.tasks.run_generation", batch.pk)
                rekicked = True

        return JsonResponse(
            {
                "status": batch.status,
                "total_count": batch.total_count,
                "done": batch.items.count(),
                "needs_review_count": batch.items.filter(needs_review=True).count(),
                "has_errors": bool(batch.error_log),
                "rekicked": rekicked,
            }
        )
