"""Background tasks for the batches app, run via django_q2 `async_task`.

Both functions below are plain, synchronously-callable Python functions —
that is django_q2's contract for a task. Dev settings run them inline
(`Q_CLUSTER["sync"] = True` in config/settings/dev.py), so calling
`run_generation(batch.pk)` directly (as the tests do) is identical to what
`async_task("batches.tasks.run_generation", batch.pk)` does in views.py. This
is the only place `batches` drives the stdlib pipeline engine end to end for
a saved `Batch`; the model<->dataclass field mapping itself lives in
`bridge.py`.
"""
from __future__ import annotations

import logging
import os

from connections.models import ConnectorCredential
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from connectors.woocommerce import WooCommerceConnector
from pipeline.generation import DEFAULT_MODEL, AnthropicProvider, FakeProvider
from pipeline.ingest import read_products
from pipeline.runner import BatchProcessingError, run_batch, write_outputs
from pipeline.types import DualScript, Script

from .bridge import build_review_items
from .models import AuditLog, Batch, ReviewItem

logger = logging.getLogger(__name__)

# Canned offline response for provider="fake" -- mirrors pipeline/cli.py's
# own `_FAKE_RESPONSE`: no numbers or attribute echoes, so a demo/test run
# never spuriously flags a claims/provenance issue regardless of catalog
# content. Ćirilica, matching the pipeline's own source-script convention for
# generated copy (pipeline/types.py) -- this is engine-facing generated
# content, not app-facing UI copy, so it follows the engine's script
# convention rather than the web app's Serbian-latinica UI convention.
_FAKE_RESPONSE = (
    "Ово је демо опис производа, генерисан у режиму fake провајдера без позива ка АИ моделу."
)

# Caps on how much text lands in persisted error/detail fields. A second line
# of defense (alongside never interpolating credential/API-key values into
# these strings in the first place) against a pathological error message or a
# huge BatchProcessingError failure list bloating a text column.
_ERROR_LOG_MAX_CHARS = 10_000
_PUBLISH_ERROR_MAX_CHARS = 1_000


def _max_products_per_batch() -> int:
    """Per-batch product cap: bounds LLM spend from a single upload.

    Env-overridable so an enterprise catalog run can raise it deliberately;
    the default matches the largest pilot-tier batch (20k SKU).
    """
    return int(os.environ.get("KORPUS_MAX_PRODUCTS_PER_BATCH", "20000"))


def run_generation(batch_id: int) -> None:
    """Ingest -> generate -> correct -> write artifacts -> ReviewItems.

    Guard: only runs from `Batch.Status.UPLOADED`; any other status (already
    running/completed/failed) is a no-op, so calling this twice on the same
    batch is safe. On success: writes `descriptions.csv` +
    `provenance/*.json` under `batch.artifacts_dir`, bulk-creates one
    `ReviewItem` per product (via bridge.build_review_items), sets
    total_count/needs_review_count, and marks the batch COMPLETED. A partial
    failure (`BatchProcessingError`) still completes the batch using
    whatever `partial_results` succeeded, recording the per-product failures
    into `error_log`. Any other, unexpected exception marks the batch FAILED
    with a safe (no-secrets) error message -- the batch is left in a
    consistent, terminal DB state either way; nothing is re-raised.
    """
    try:
        batch = Batch.objects.select_related("organization").get(pk=batch_id)
    except Batch.DoesNotExist:
        logger.warning("run_generation: Batch %s does not exist.", batch_id)
        return

    # Atomic compare-and-swap on the status: a plain read-check-then-save
    # would let two concurrent runs (double enqueue, django_q retry) both see
    # UPLOADED and both generate -- double LLM spend and an IntegrityError on
    # the second bulk_create. The single UPDATE ... WHERE status='uploaded'
    # guarantees exactly one runner wins.
    claimed = Batch.objects.filter(
        pk=batch_id, status=Batch.Status.UPLOADED
    ).update(status=Batch.Status.RUNNING)
    if not claimed:
        logger.info(
            "run_generation: Batch %s is %s, not uploaded; skipping.",
            batch_id,
            batch.status,
        )
        return
    batch.status = Batch.Status.RUNNING

    error_log = ""
    try:
        records = read_products(batch.source_file.path)

        if len(records) > _max_products_per_batch():
            raise ValueError(
                f"Batch has {len(records)} products, over the "
                f"{_max_products_per_batch()} per-batch limit "
                "(KORPUS_MAX_PRODUCTS_PER_BATCH). Split the catalog into "
                "smaller files."
            )

        if batch.provider == Batch.Provider.ANTHROPIC:
            # api_key is intentionally omitted: AnthropicProvider falls back
            # to the ANTHROPIC_API_KEY env var, so the key is never read into
            # a local variable here, let alone stored or logged.
            provider = AnthropicProvider(model=batch.model or DEFAULT_MODEL)
        else:
            provider = FakeProvider(_FAKE_RESPONSE)

        source_script = Script(batch.source_script)

        try:
            results = run_batch(records, provider, source_script=source_script)
        except BatchProcessingError as exc:
            results = exc.partial_results
            error_log = "\n".join(
                f"{failure.record.product_id}: {failure.error}" for failure in exc.failures
            )[:_ERROR_LOG_MAX_CHARS]

        write_outputs(results, batch.artifacts_dir)
        ReviewItem.objects.bulk_create(build_review_items(batch, results))

        batch.total_count = len(results)
        batch.needs_review_count = sum(1 for result in results if result.needs_review)
        batch.status = Batch.Status.COMPLETED
        batch.error_log = error_log
        batch.finished_at = timezone.now()
        batch.save(
            update_fields=[
                "status", "total_count", "needs_review_count", "error_log", "finished_at",
            ]
        )
        AuditLog.objects.create(
            organization=batch.organization,
            actor=batch.created_by,
            action=AuditLog.Action.GENERATE,
            batch=batch,
            detail={
                "total_count": batch.total_count,
                "needs_review_count": batch.needs_review_count,
            },
        )
    except Exception as exc:  # noqa: BLE001 - a bad batch must not crash the task runner
        logger.exception("run_generation: Batch %s failed.", batch_id)
        batch.status = Batch.Status.FAILED
        batch.error_log = str(exc)[:_ERROR_LOG_MAX_CHARS]
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "error_log", "finished_at"])


def publish_batch(
    batch_id: int, credential_id: int, publish_script: str, actor_id: int | None
) -> dict[str, int]:
    """Push every APPROVED `ReviewItem` in `batch` to a store connector.

    Only `ConnectorType.WOOCOMMERCE` is functional (see doc/CLAUDE.md's Phase
    2 notes: `connectors.selltico`/`connectors.tau_commerce` are named
    placeholders with no real API docs, every method `NotImplementedError`).
    Any other connector type fails loudly and cheaply -- one AuditLog
    `publish_failed` row -- rather than calling those placeholders per item.
    A credential that does not belong to `batch.organization` is refused the
    same way (never trust a caller-supplied credential id against a
    different org's batch).

    Each approved item is processed in its own `transaction.atomic()` block
    with `select_for_update()`, so a crash partway through a batch never
    loses the fact that earlier items already published, and a per-item push
    failure (`publish_error` + an audit row) never aborts the rest of the
    run -- the same "never abort on one bad record" contract
    `pipeline.runner.run_batch` and the CLI's `publish` command use.

    Returns `{"published": n, "failed": n, "skipped": n}`; `skipped` counts
    items that were never APPROVED (pending/rejected/already-published) and
    so were never touched.
    """
    batch = Batch.objects.select_related("organization").get(pk=batch_id)

    actor = None
    if actor_id is not None:
        actor = get_user_model().objects.filter(pk=actor_id).first()

    def _log_failure(detail: dict) -> None:
        AuditLog.objects.create(
            organization=batch.organization,
            actor=actor,
            action=AuditLog.Action.PUBLISH_FAILED,
            batch=batch,
            detail=detail,
        )

    try:
        credential = ConnectorCredential.objects.get(pk=credential_id)
    except ConnectorCredential.DoesNotExist:
        _log_failure({"reason": "credential not found"})
        return {"published": 0, "failed": 0, "skipped": 0}

    if credential.organization_id != batch.organization_id:
        _log_failure({"reason": "credential org mismatch"})
        return {"published": 0, "failed": 0, "skipped": 0}

    if credential.connector_type != ConnectorCredential.ConnectorType.WOOCOMMERCE:
        _log_failure(
            {"reason": "connector not implemented", "connector_type": credential.connector_type}
        )
        return {"published": 0, "failed": 0, "skipped": 0}

    connector = WooCommerceConnector(
        base_url=credential.base_url,
        consumer_key=credential.consumer_key,
        consumer_secret=credential.consumer_secret,
    )
    script = Script(publish_script)

    published = 0
    failed = 0
    skipped = batch.items.exclude(status=ReviewItem.Status.APPROVED).count()
    approved_ids = list(
        batch.items.filter(status=ReviewItem.Status.APPROVED).values_list("pk", flat=True)
    )

    for item_id in approved_ids:
        with transaction.atomic():
            item = ReviewItem.objects.select_for_update().filter(pk=item_id).first()
            if item is None or item.status != ReviewItem.Status.APPROVED:
                # Re-checked under the row lock: another worker may have
                # already changed this item between the outer query above
                # and this item's own transaction.
                continue

            dual = DualScript(cirilica=item.cirilica, latinica=item.latinica)
            try:
                connector.push_description(item.product_id, dual, publish_script=script)
            except Exception as exc:  # noqa: BLE001 - one bad product must not abort the batch
                item.publish_error = str(exc)[:_PUBLISH_ERROR_MAX_CHARS]
                item.save(update_fields=["publish_error"])
                AuditLog.objects.create(
                    organization=batch.organization,
                    actor=actor,
                    action=AuditLog.Action.PUBLISH_FAILED,
                    batch=batch,
                    product_id=item.product_id,
                    detail={"error": item.publish_error},
                )
                failed += 1
                continue

            item.mark_published()
            published += 1

    return {"published": published, "failed": failed, "skipped": skipped}
