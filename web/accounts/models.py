"""Models for the accounts app.

Organization / Membership are the org-scoping backbone for the rest of the
project. The FK field names on Membership (`user`, `organization`) are a
FIXED CONTRACT relied on by `common.org.OrgMembershipRequiredMixin`, which
resolves them by name via `Membership.objects.filter(user=..., organization=...)`.
Do not rename them.
"""
from django.conf import settings
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        MEMBER = "member", "Član"
        ADMIN = "admin", "Administrator"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.MEMBER
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"], name="unique_user_organization"
            )
        ]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"
