"""Models for the batches app: uploaded catalogs, their generated review
items, and an append-only audit trail.

This is the Django-side persistence layer bridging to the stdlib pipeline
engine at the repo root (``pipeline/``, ``connectors/``) — see
``batches/bridge.py`` for the field/dataclass mapping and ``batches/tasks.py``
for the background jobs that drive a ``Batch`` through
UPLOADED -> RUNNING -> COMPLETED/FAILED, and a ``ReviewItem`` through
PENDING -> APPROVED/REJECTED -> PUBLISHED.

MODEL CONTRACT (fixed — other agents, incl. views/forms/admin, code against
exactly this). Field names, choices values, and method signatures below must
not change without coordinating across agents.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


def batch_upload_path(instance: Batch, filename: str) -> str:
    """Storage path for an uploaded catalog file, scoped by organization."""
    return f"orgs/{instance.organization.slug}/batches/{filename}"


class Batch(models.Model):
    """One uploaded catalog file and the run state of generating from it."""

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # Values match `pipeline.types.Script` 1:1 ("cirilica"/"latinica"), so the
    # engine boundary conversion is just `Script(batch.source_script)` — see
    # batches/tasks.py. Kept as a plain CharField (not the pipeline enum
    # itself) so this module never imports pipeline at the model layer.
    class SourceScript(models.TextChoices):
        LATINICA = "latinica", "Latinica"
        CIRILICA = "cirilica", "Ćirilica"

    class Provider(models.TextChoices):
        FAKE = "fake", "Fake"
        ANTHROPIC = "anthropic", "Anthropic"

    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="batches"
    )
    name = models.CharField(max_length=200)
    source_file = models.FileField(upload_to=batch_upload_path)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPLOADED
    )
    source_script = models.CharField(
        max_length=20, choices=SourceScript.choices, default=SourceScript.LATINICA
    )
    provider = models.CharField(
        max_length=20, choices=Provider.choices, default=Provider.FAKE
    )
    model = models.CharField(max_length=100, blank=True)
    total_count = models.IntegerField(default=0)
    needs_review_count = models.IntegerField(default=0)
    error_log = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Bumped as chunked generation makes progress (see tasks.run_generation).
    # Lets the status endpoint detect a stalled RUNNING batch — a chunk that
    # crashed without dispatching its continuation — and re-kick it. NULL on
    # batches that never started running.
    last_progress_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class ReviewItem(models.Model):
    """One product's place in a batch's human review/approval queue.

    Status values are EXACTLY `pipeline.review.ReviewStatus`'s values
    ("pending"/"approved"/"rejected"/"published") so batches/bridge.py can
    round-trip a ReviewItem queryset through the engine's ReviewQueue with a
    trivial 1:1 value mapping. The approve/reject/mark_published guard
    semantics below deliberately mirror `pipeline.review.ReviewQueue`'s
    approve/reject/mark_published (see that module's DESIGN NOTES): approving
    or rejecting an already-PUBLISHED item is refused (publishing is
    terminal), and mark_published is only valid from APPROVED. Nothing here
    auto-approves.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PUBLISHED = "published", "Published"

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="items")
    product_id = models.CharField(max_length=200)
    cirilica = models.TextField()
    latinica = models.TextField()
    needs_review = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    reason = models.TextField(blank=True)
    provenance = models.JSONField(default=dict, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    publish_error = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "product_id"], name="unique_batch_product_id"
            )
        ]
        ordering = ["product_id"]

    def __str__(self) -> str:
        return f"{self.product_id} ({self.status})"

    def approve(self, actor) -> None:
        """Mark this item APPROVED. Valid from any status except PUBLISHED.

        Clears any prior rejection `reason` and any stale `publish_error` —
        a fresh approval is what makes a previously-failed publish attempt
        retryable. The save and the resulting AuditLog row are written in one
        `transaction.atomic()` block so a review decision is never partially
        recorded.
        """
        if self.status == self.Status.PUBLISHED:
            raise ValidationError("Cannot approve an item that is already published.")
        with transaction.atomic():
            self.status = self.Status.APPROVED
            self.reason = ""
            self.publish_error = ""
            self.decided_by = actor
            self.decided_at = timezone.now()
            self.save(
                update_fields=[
                    "status", "reason", "publish_error", "decided_by", "decided_at",
                ]
            )
            AuditLog.objects.create(
                organization=self.batch.organization,
                actor=actor,
                action=AuditLog.Action.APPROVE,
                batch=self.batch,
                product_id=self.product_id,
            )

    def reject(self, actor, reason: str) -> None:
        """Mark this item REJECTED. Requires a non-empty `reason`.

        Same status-validity guard as `approve` (refused once PUBLISHED).
        """
        if self.status == self.Status.PUBLISHED:
            raise ValidationError("Cannot reject an item that is already published.")
        if not reason or not reason.strip():
            raise ValidationError("A rejection reason is required.")
        with transaction.atomic():
            self.status = self.Status.REJECTED
            self.reason = reason
            self.decided_by = actor
            self.decided_at = timezone.now()
            self.save(update_fields=["status", "reason", "decided_by", "decided_at"])
            AuditLog.objects.create(
                organization=self.batch.organization,
                actor=actor,
                action=AuditLog.Action.REJECT,
                batch=self.batch,
                product_id=self.product_id,
                detail={"reason": reason},
            )

    def mark_published(self) -> None:
        """Mark this item PUBLISHED. Only valid when currently APPROVED."""
        if self.status != self.Status.APPROVED:
            raise ValidationError(
                f"Cannot publish an item that is not approved (status: {self.status})."
            )
        with transaction.atomic():
            self.status = self.Status.PUBLISHED
            self.published_at = timezone.now()
            self.save(update_fields=["status", "published_at"])
            AuditLog.objects.create(
                organization=self.batch.organization,
                action=AuditLog.Action.PUBLISH,
                batch=self.batch,
                product_id=self.product_id,
            )


class AuditLog(models.Model):
    """Append-only record of every batch/review-item state transition.

    Append-only by CONVENTION only — nothing here enforces immutability at
    the DB layer; that enforcement (e.g. locking it down in admin) is another
    task's job. Callers must never create a row via anything but
    `AuditLog.objects.create(...)` and must never update/delete a row.
    """

    class Action(models.TextChoices):
        UPLOAD = "upload", "Upload"
        GENERATE = "generate", "Generate"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        PUBLISH = "publish", "Publish"
        PUBLISH_FAILED = "publish_failed", "Publish failed"

    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="audit_logs"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    batch = models.ForeignKey(
        Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs"
    )
    product_id = models.CharField(max_length=200, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class StoredFile(models.Model):
    """One uploaded file's bytes, backing `batches.dbstorage.DatabaseStorage`.

    Serverless deployments have no persistent filesystem, so the default
    file storage there keeps uploads in Postgres instead of on disk. Rows
    stay small by platform fiat — Vercel caps request bodies at ~4.5 MB,
    well under the 50 MB form-level cap — and only `Batch.source_file` uses
    the default storage. `name` is the storage-visible identifier: exactly
    the string the FileField persists in its own column (the
    `batch_upload_path` shape, e.g. "orgs/<slug>/batches/<filename>").
    """

    name = models.CharField(max_length=500, unique=True)
    content = models.BinaryField()
    size = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name
