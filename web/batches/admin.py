"""Admin registrations for the batches domain.

House rule for this whole app: admin is a browsing/audit surface, not an
authoring one. Batches are created by uploading a catalog through the app UI
(batches/views.py), which also kicks off the background run (batches/tasks.py).
A ReviewItem's status only ever moves via its guard methods
(``approve``/``reject``/``mark_published``, see models.py), which enforce the
PENDING -> APPROVED/REJECTED -> PUBLISHED contract and write a matching
AuditLog row inside the same transaction. Admin must never be a second write
path for either of those state machines, so:

- ``BatchAdmin`` cannot add batches.
- ``ReviewItemAdmin`` can only ever view items; every field is readonly and
  ``save_model`` is a hard no-op.
- ``AuditLogAdmin`` is fully append-only: no add, change, or delete.
"""
from __future__ import annotations

from django.contrib import admin

from .models import AuditLog, Batch, ReviewItem


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "status",
        "provider",
        "total_count",
        "needs_review_count",
        "created_at",
    )
    list_filter = ("status", "provider", "organization")
    search_fields = ("name",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "created_at",
        "finished_at",
        "total_count",
        "needs_review_count",
        "error_log",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("organization", "created_by")

    def has_add_permission(self, request):
        # Batches are created by uploading a catalog through the app UI
        # (batches/views.py) — there is no valid "blank" batch to author
        # here, and admin-created rows would have no source_file to run.
        return False


@admin.register(ReviewItem)
class ReviewItemAdmin(admin.ModelAdmin):
    """Read-mostly: the detail page renders, but nothing on it is writable.

    Status transitions (PENDING -> APPROVED/REJECTED -> PUBLISHED) are only
    ever valid through ``ReviewItem.approve``/``reject``/``mark_published``
    (models.py), invoked from the app's review-queue UI, which also write the
    corresponding ``AuditLog`` row. Making every field readonly here — and
    ``save_model`` a no-op as a second line of defense — means a POST to the
    admin change form can never move an item's status.
    """

    list_display = (
        "product_id",
        "batch",
        "status",
        "needs_review",
        "decided_by",
        "published_at",
    )
    list_filter = ("status", "needs_review", "batch__organization")
    search_fields = ("product_id",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("batch", "batch__organization", "decided_by")
        )

    def get_readonly_fields(self, request, obj=None):
        # Every model field, always — this is a view-only detail page.
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # True only so the change *page* renders (as a fully read-only
        # detail view — see get_readonly_fields above) instead of 403ing.
        # save_model below refuses to persist anything regardless of what a
        # POST carries.
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        # No-op. Every field is readonly (get_readonly_fields), so the form
        # never binds a change to persist — this makes the "admin cannot
        # mutate a ReviewItem" guarantee explicit rather than incidental.
        return


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Append-only trail: view and search only, never add/change/delete."""

    list_display = (
        "created_at",
        "organization",
        "actor",
        "action",
        "batch",
        "product_id",
    )
    list_filter = ("action", "organization")
    search_fields = ("product_id",)
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("organization", "actor", "batch")
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
