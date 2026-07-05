"""Background tasks for the batches app, handed off via `batches.dispatch`.

Both functions below are plain, synchronously-callable Python functions --
that is the contract every dispatch mode shares. Dev settings run them
inline (`KORPUS_TASK_DISPATCH = "sync"`), so calling
`run_generation(batch.pk)` directly (as the tests do) is identical to what
`dispatch("batches.tasks.run_generation", batch.pk)` does in views.py. This
is the only place `batches` drives the stdlib pipeline engine end to end for
a saved `Batch`; the model<->dataclass field mapping itself lives in
`bridge.py`.

CHUNKED EXECUTION. Serverless platforms cap one invocation at a few
minutes, while a real batch is hours of sequential LLM calls. Both tasks
therefore run against a wall-clock budget
(`settings.KORPUS_TASK_TIME_BUDGET_SECONDS`; None = unlimited, the VPS/dev
single-pass behavior): when the budget runs out with work left, the task
persists progress and dispatches a continuation of itself, and each
continuation resumes exactly where the DB says work stopped. Recovery from
a crashed chunk -- one that died before dispatching its continuation -- is
the status endpoint's stall backstop (views.BatchStatusView), keyed off
`Batch.last_progress_at`.

Idempotency over locking: `ReviewItem`'s (batch, product_id) unique
constraint makes per-product creation naturally idempotent, so a rare
duplicate runner (double delivery, a retry racing a slow chunk) wastes at
most a few duplicate LLM calls and never corrupts state. That is
deliberately preferred over a lease/token protocol here.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from connections.models import ConnectorCredential
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from connectors.woocommerce import WooCommerceConnector
from pipeline.generation import DEFAULT_MODEL, AnthropicProvider, FakeProvider
from pipeline.ingest import read_products
from pipeline.runner import process_product
from pipeline.types import DualScript, Script

from .bridge import review_item_kwargs_from_result
from .dispatch import dispatch
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
# huge failure list bloating a text column.
_ERROR_LOG_MAX_CHARS = 10_000
_PUBLISH_ERROR_MAX_CHARS = 1_000


def _max_products_per_batch() -> int:
    """Per-batch product cap: bounds LLM spend from a single upload.

    Env-overridable so an enterprise catalog run can raise it deliberately;
    the default matches the largest pilot-tier batch (20k SKU).
    """
    return int(os.environ.get("KORPUS_MAX_PRODUCTS_PER_BATCH", "20000"))


def _load_records(batch: Batch):
    """Copy `batch.source_file` to a local temp path and ingest it.

    `pipeline.ingest.read_products` takes a filesystem path only -- it
    dispatches on the file extension and opens the csv/zip itself -- while
    the configured storage may be non-filesystem (batches.dbstorage on
    serverless). Copying through a NamedTemporaryFile keeps the engine
    stdlib-pure and works identically on every storage backend. The suffix
    must survive the copy because ingest dispatches on it.
    """
    suffix = Path(batch.source_file.name).suffix or ".csv"
    with batch.source_file.open("rb") as source:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            shutil.copyfileobj(source, tmp)
            tmp_path = tmp.name
    try:
        return read_products(tmp_path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


def run_generation(batch_id: int) -> None:
    """Ingest -> generate -> correct -> ReviewItems, in resumable chunks.

    Guard: a first entry only proceeds from `Batch.Status.UPLOADED` -- the
    atomic compare-and-swap to RUNNING below means a double enqueue can't
    double-claim -- and a continuation entry only proceeds from RUNNING.
    COMPLETED/FAILED batches are a no-op, so calling this any number of
    times is safe.

    Every product that generates successfully becomes a `ReviewItem`
    immediately (not batched at the end), which is what makes the run
    resumable: a continuation just skips product_ids that already have
    rows. First record wins for duplicate product_ids within one catalog;
    later duplicates are skipped (the old all-at-once bulk_create would
    have failed the whole batch on that input). Per-product engine failures
    append to `error_log` (bounded) and never abort the run -- the same
    "never abort on one bad record" contract `pipeline.runner.run_batch`
    has. On budget exhaustion a continuation is dispatched; on completion
    the batch flips RUNNING -> COMPLETED via a second CAS, so exactly one
    runner writes the final counts and the single GENERATE audit row. Any
    unexpected exception marks the batch FAILED with a safe (no-secrets)
    message -- the batch lands in a consistent, terminal DB state either
    way; nothing is re-raised.
    """
    try:
        batch = Batch.objects.select_related("organization").get(pk=batch_id)
    except Batch.DoesNotExist:
        logger.warning("run_generation: Batch %s does not exist.", batch_id)
        return

    claimed = Batch.objects.filter(
        pk=batch_id, status=Batch.Status.UPLOADED
    ).update(status=Batch.Status.RUNNING, last_progress_at=timezone.now())
    if not claimed and batch.status != Batch.Status.RUNNING:
        logger.info(
            "run_generation: Batch %s is %s, not uploaded/running; skipping.",
            batch_id,
            batch.status,
        )
        return
    batch.status = Batch.Status.RUNNING

    started = time.monotonic()
    budget = settings.KORPUS_TASK_TIME_BUDGET_SECONDS
    # A continuation picks the log up where the previous chunk left it.
    error_log = batch.error_log

    try:
        records = _load_records(batch)

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

        # First record wins per product_id (see docstring).
        unique_records = []
        seen: set[str] = set()
        for record in records:
            if record.product_id in seen:
                continue
            seen.add(record.product_id)
            unique_records.append(record)

        # Progress denominator for the status endpoint. Snapped to the
        # actually-generated item count at completion (failures excluded),
        # preserving the pre-chunking total_count semantics.
        if batch.total_count != len(unique_records):
            Batch.objects.filter(pk=batch_id).update(
                total_count=len(unique_records)
            )

        done_ids = set(batch.items.values_list("product_id", flat=True))
        remaining = [r for r in unique_records if r.product_id not in done_ids]

        for record in remaining:
            if budget is not None and time.monotonic() - started >= budget:
                Batch.objects.filter(pk=batch_id).update(
                    error_log=error_log, last_progress_at=timezone.now()
                )
                dispatch("batches.tasks.run_generation", batch_id)
                logger.info(
                    "run_generation: Batch %s chunk budget reached; "
                    "continuation dispatched.",
                    batch_id,
                )
                return

            try:
                result = process_product(
                    record, provider, source_script=source_script
                )
            except Exception as exc:  # noqa: BLE001 - one bad record must not abort the batch
                line = f"{record.product_id}: {exc}"
                error_log = (
                    f"{error_log}\n{line}" if error_log else line
                )[:_ERROR_LOG_MAX_CHARS]
            else:
                try:
                    ReviewItem.objects.create(
                        **review_item_kwargs_from_result(batch, result)
                    )
                except IntegrityError:
                    # A duplicate runner (double delivery / retry racing a
                    # slow chunk) generated this product concurrently and
                    # its row won; nothing to record.
                    pass
            Batch.objects.filter(pk=batch_id).update(
                error_log=error_log, last_progress_at=timezone.now()
            )

        total = batch.items.count()
        needs_review = batch.items.filter(needs_review=True).count()
        completed = Batch.objects.filter(
            pk=batch_id, status=Batch.Status.RUNNING
        ).update(
            status=Batch.Status.COMPLETED,
            total_count=total,
            needs_review_count=needs_review,
            error_log=error_log,
            finished_at=timezone.now(),
        )
        if completed:
            AuditLog.objects.create(
                organization=batch.organization,
                actor=batch.created_by,
                action=AuditLog.Action.GENERATE,
                batch=batch,
                detail={
                    "total_count": total,
                    "needs_review_count": needs_review,
                },
            )
    except Exception as exc:  # noqa: BLE001 - a bad batch must not crash the task runner
        logger.exception("run_generation: Batch %s failed.", batch_id)
        Batch.objects.filter(pk=batch_id).update(
            status=Batch.Status.FAILED,
            error_log=str(exc)[:_ERROR_LOG_MAX_CHARS],
            finished_at=timezone.now(),
        )


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
    `pipeline.runner.run_batch` and the CLI's `publish` command use. That
    per-item design is also what makes chunking safe: on budget exhaustion
    a continuation is dispatched with identical arguments, and it simply
    re-queries what is still APPROVED.

    Returns `{"published": n, "failed": n, "skipped": n}` **for this chunk
    only** (informational -- nothing consumes it); `skipped` counts items
    that were not APPROVED when this chunk started.
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

    started = time.monotonic()
    budget = settings.KORPUS_TASK_TIME_BUDGET_SECONDS

    published = 0
    failed = 0
    skipped = batch.items.exclude(status=ReviewItem.Status.APPROVED).count()
    approved_ids = list(
        batch.items.filter(status=ReviewItem.Status.APPROVED).values_list("pk", flat=True)
    )

    for item_id in approved_ids:
        if budget is not None and time.monotonic() - started >= budget:
            dispatch(
                "batches.tasks.publish_batch",
                batch_id,
                credential_id,
                publish_script,
                actor_id,
            )
            logger.info(
                "publish_batch: Batch %s chunk budget reached; "
                "continuation dispatched.",
                batch_id,
            )
            break

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
