"""The engine boundary: mapping between Django's batches models and the
stdlib pipeline engine (`pipeline.review`, `pipeline.types`) at the repo
root.

This is the ONLY place batches translates between the two worlds. `tasks.py`
composes these helpers with the pipeline stage functions (ingest / generation
/ runner); it must never shape a pipeline dataclass (or reach into a Django
model to build one) inline — that mapping logic belongs in exactly one place,
here, so the two schemas can never silently drift apart.
"""
from __future__ import annotations

from pipeline.review import ReviewItem as PipelineReviewItem
from pipeline.review import ReviewQueue, ReviewStatus, review_queue_to_json
from pipeline.types import DualScript, ProductResult

from .models import Batch
from .models import ReviewItem as DjangoReviewItem


def export_review_queue_json(batch: Batch) -> str:
    """Render `batch`'s ReviewItems as the downloadable compliance artifact.

    Builds a `pipeline.review.ReviewQueue` from the batch's `ReviewItem` rows
    (in `ReviewItem.Meta.ordering` — by product_id) and returns
    `review_queue_to_json(...)` verbatim, so the file this produces is
    byte-for-byte interchangeable with a `review_queue.json` the pipeline
    CLI's own `generate`/`review` subcommands would have written for the same
    data. Statuses map 1:1 by value — `batches.ReviewItem.Status` and
    `pipeline.review.ReviewStatus` share the exact same string values.
    """
    queue = ReviewQueue(
        items=tuple(
            PipelineReviewItem(
                product_id=item.product_id,
                dual_script=DualScript(cirilica=item.cirilica, latinica=item.latinica),
                needs_review=item.needs_review,
                status=ReviewStatus(item.status),
                reason=item.reason or None,
            )
            for item in batch.items.all()
        )
    )
    return review_queue_to_json(queue)


def review_item_kwargs_from_result(batch: Batch, result: ProductResult) -> dict:
    """Map one engine `ProductResult` to `ReviewItem` constructor kwargs.

    Mirrors `pipeline.review.build_review_queue`: every item starts PENDING
    regardless of `needs_review` — see that module's DESIGN NOTES for why
    nothing auto-approves here either. `needs_review` is carried through
    unchanged as a triage signal only, never a publish gate.

    `provenance` stores the full sentence-level `ProvenanceReport` (the same
    shape `pipeline.provenance.provenance_to_json` writes to disk) so the
    review UI/audit trail has the compliance detail without a second read off
    the filesystem. `attributes` stores `result.record.attributes` — the
    grounded structured input the description was generated from — for the
    same reason.
    """
    dual = result.correctness.dual_script
    provenance_payload = {
        "is_clean": result.provenance.is_clean,
        "entries": [
            {
                "sentence": entry.sentence,
                "supporting_attributes": list(entry.supporting_attributes),
                "supported": entry.supported,
            }
            for entry in result.provenance.entries
        ],
    }
    return {
        "batch": batch,
        "product_id": result.record.product_id,
        "cirilica": dual.cirilica,
        "latinica": dual.latinica,
        "needs_review": result.needs_review,
        "status": DjangoReviewItem.Status.PENDING,
        "provenance": provenance_payload,
        "attributes": dict(result.record.attributes),
    }


def build_review_items(
    batch: Batch, results: list[ProductResult]
) -> list[DjangoReviewItem]:
    """Build (unsaved) `ReviewItem` model instances, ready for `bulk_create`."""
    return [
        DjangoReviewItem(**review_item_kwargs_from_result(batch, result))
        for result in results
    ]
