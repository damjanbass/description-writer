from django.contrib import admin

from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "company", "created_at")
    search_fields = ("name", "email", "company", "message")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    # Leads are captured, not authored: make every field read-only in the
    # change view (viewing/searching/deleting is still fully supported).
    readonly_fields = (
        "name",
        "email",
        "company",
        "message",
        "source",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Allow opening the change view (read-only, via readonly_fields)
        # but block actually saving edits.
        return True

    def has_delete_permission(self, request, obj=None):
        return True
