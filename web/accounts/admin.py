from django.contrib import admin, messages
from django.contrib.auth.forms import PasswordResetForm

from .models import Membership, Organization


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "organization")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "created_at"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organization", "role"]
    list_filter = ["role", "organization"]
    autocomplete_fields = ["user", "organization"]
    search_fields = ["user__username", "user__email", "organization__name"]
    actions = ["send_password_setup_link"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "organization")

    @admin.action(description="Pošalji link za postavljanje lozinke")
    def send_password_setup_link(self, request, queryset):
        sent = 0
        skipped = 0
        seen_user_ids = set()
        for membership in queryset.select_related("user"):
            user = membership.user
            if user.pk in seen_user_ids:
                continue
            seen_user_ids.add(user.pk)

            if not user.email:
                skipped += 1
                continue

            form = PasswordResetForm(data={"email": user.email})
            if form.is_valid():
                form.save(request=request, use_https=request.is_secure())
                sent += 1
            else:
                skipped += 1

        if sent:
            self.message_user(request, f"Poslato {sent} link(ova) za postavljanje lozinke.")
        if skipped:
            self.message_user(
                request,
                f"Preskočeno {skipped} korisnik(a) bez validne e-pošte.",
                level=messages.WARNING,
            )
