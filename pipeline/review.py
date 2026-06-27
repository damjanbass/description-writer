"""Phase 2 — human-in-the-loop review/approval queue.

Masterplan line this implements: "Add human-in-the-loop review/approval
queue — enterprise teams will NOT publish unreviewed AI copy to 800k pages."
This module is the data model only: building the queue from pipeline output,
querying it, and recording reviewer decisions. CLI wiring and connector
publish-hooks are separate, later concerns and must not be assumed here.

IMPLEMENTATION CONTRACT (keep public signatures stable):

`ReviewStatus` — string Enum, lowercase values: PENDING, APPROVED, REJECTED,
PUBLISHED. Matches the `Script` enum convention in pipeline/types.py.

`ReviewItem` — frozen dataclass: product_id, dual_script, needs_review,
status, reason (`str | None`, default None - a rejection note; unused
otherwise).

`ReviewQueue` — frozen dataclass wrapping `items: tuple[ReviewItem, ...]`.
  - `get(product_id) -> ReviewItem | None` - lookup, None if absent.
  - `by_status(status) -> tuple[ReviewItem, ...]` - filter, order preserved.
  - `approve(product_id) -> ReviewQueue` - new queue, that item -> APPROVED,
    `reason` cleared to None. Valid from any status except PUBLISHED.
  - `reject(product_id, *, reason=None) -> ReviewQueue` - new queue, that
    item -> REJECTED, `reason` stored. Same validity/errors as `approve`.
  - `mark_published(product_id) -> ReviewQueue` - new queue, that item ->
    PUBLISHED. Valid only from APPROVED.
  - Unknown `product_id` on any of the three above ->
    `ValueError(f"unknown product_id: {product_id}")`.
  - `approve`/`reject` on an already-PUBLISHED item ->
    `ValueError(f"product {product_id} is already published")`.
  - `mark_published` on anything other than APPROVED ->
    `ValueError(f"product {product_id} must be approved before publishing "
    f"(status: {item.status.value})")`.
  - All three transitions use `dataclasses.replace` on the single changed
    item and rebuild `items` preserving original order - never reorder.

`build_review_queue(results: list[ProductResult]) -> ReviewQueue` - one
`ReviewItem` per `ProductResult`, every item starts `ReviewStatus.PENDING`
regardless of `needs_review`. `dual_script` comes from
`result.correctness.dual_script`. `needs_review` is carried through
unchanged as a triage signal only (see DESIGN NOTES - nothing is
auto-approved).

`review_queue_to_json(queue) -> str` / `review_queue_from_json(text) ->
ReviewQueue` - inverse pair, `indent=2, ensure_ascii=False` JSON (matches
`provenance_to_json`). Shape: `{"items": [{"product_id", "cirilica",
"latinica", "needs_review", "status", "reason"}, ...]}`, `status` rendered
as its `.value` string.

Tests go in tests/pipeline/test_review.py.

DESIGN NOTES (why it is shaped this way):

  - Every item starts PENDING, even when `needs_review` is False. The
    masterplan line driving this module is explicit that the gap being
    closed is "enterprise teams will NOT publish unreviewed AI copy" - the
    risk is unreviewed copy, not just flagged-as-risky copy. A clean
    correctness/provenance verdict says the deterministic checks found
    nothing wrong; it says nothing about brand voice, pricing sensitivity,
    or context a human still needs to sign off on for an 800k-page catalog.
    Auto-approving "clean" items would silently reintroduce the exact
    failure mode (unreviewed copy reaching production) the masterplan calls
    out, just gated on a narrower set of checks. `needs_review` is kept on
    `ReviewItem` purely as a triage signal so a reviewer UI/CLI can sort or
    filter the queue (review the risky ones first), never as a publish gate.

  - `ReviewItem`/`ReviewQueue` are frozen, and every transition method
    returns a new `ReviewQueue` via `dataclasses.replace` rather than
    mutating in place. This matches the immutable-dataclass convention used
    throughout pipeline/types.py and core/*/types.py: a `ProductResult` or
    `CorrectnessResult` is never mutated after construction, it is rebuilt.
    For a review queue specifically, immutability also means a queue that
    has already been written to disk/passed to a caller can never be
    silently altered later by an unrelated reference holding the same
    object - every state change is an explicit, observable new value.

  - Status transitions are guarded rather than open writes, and PUBLISHED is
    terminal (no transition leads out of it). The queue's primary consumer
    is a future CLI driven by a human typing product ids - a typo'd id or a
    double-invoked "publish" command is the realistic failure mode, not a
    malicious caller. Raising a specific, descriptive `ValueError` (unknown
    id vs. wrong-state vs. already-published) turns that mistake into an
    immediate, loud failure instead of a silent overwrite that could
    re-publish or re-approve copy a reviewer already finished with -
    exactly the kind of silent-corruption bug this module must not allow
    given what is riding on the review gate.

  - JSON round-trips through plain dict/list shapes, the same pattern as
    `provenance_to_json`/`build_provenance`'s implicit contract: a flat,
    obvious-to-read structure a non-Python tool (or a human with a text
    editor) could also produce/consume, and `ensure_ascii=False` because the
    `cirilica` field is Cyrillic text that must stay literal Cyrillic in the
    artifact, not escaped to `\\uXXXX` sequences.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum

from pipeline.types import DualScript, ProductResult


class ReviewStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


@dataclass(frozen=True)
class ReviewItem:
    """One product's place in the review queue: its dual-script copy, the
    triage signal from the correctness layer, and the reviewer's decision.
    """

    product_id: str
    dual_script: DualScript
    needs_review: bool
    status: ReviewStatus
    reason: str | None = None


@dataclass(frozen=True)
class ReviewQueue:
    """An ordered, immutable collection of `ReviewItem`s.

    Every state-changing method returns a NEW `ReviewQueue` - see the module
    DESIGN NOTES for why this is frozen+replace rather than mutable.
    """

    items: tuple[ReviewItem, ...]

    def get(self, product_id: str) -> ReviewItem | None:
        for item in self.items:
            if item.product_id == product_id:
                return item
        return None

    def by_status(self, status: ReviewStatus) -> tuple[ReviewItem, ...]:
        return tuple(item for item in self.items if item.status is status)

    def _replace_item(self, product_id: str, **changes: object) -> ReviewQueue:
        """Rebuild `items` with the matching item replaced, order preserved.

        Internal helper shared by `approve`/`reject`/`mark_published` so the
        find-or-raise and rebuild-preserving-order logic lives in one place.
        """
        item = self.get(product_id)
        if item is None:
            raise ValueError(f"unknown product_id: {product_id}")
        updated = replace(item, **changes)
        new_items = tuple(updated if i.product_id == product_id else i for i in self.items)
        return replace(self, items=new_items)

    def approve(self, product_id: str) -> ReviewQueue:
        """Mark `product_id` APPROVED, clearing any prior rejection reason.

        Valid from any status except PUBLISHED (publishing is terminal).
        """
        item = self.get(product_id)
        if item is None:
            raise ValueError(f"unknown product_id: {product_id}")
        if item.status is ReviewStatus.PUBLISHED:
            raise ValueError(f"product {product_id} is already published")
        return self._replace_item(product_id, status=ReviewStatus.APPROVED, reason=None)

    def reject(self, product_id: str, *, reason: str | None = None) -> ReviewQueue:
        """Mark `product_id` REJECTED, storing an optional `reason` note.

        Valid from any status except PUBLISHED (publishing is terminal).
        """
        item = self.get(product_id)
        if item is None:
            raise ValueError(f"unknown product_id: {product_id}")
        if item.status is ReviewStatus.PUBLISHED:
            raise ValueError(f"product {product_id} is already published")
        return self._replace_item(product_id, status=ReviewStatus.REJECTED, reason=reason)

    def mark_published(self, product_id: str) -> ReviewQueue:
        """Mark `product_id` PUBLISHED. Only valid when currently APPROVED."""
        item = self.get(product_id)
        if item is None:
            raise ValueError(f"unknown product_id: {product_id}")
        if item.status is not ReviewStatus.APPROVED:
            raise ValueError(
                f"product {product_id} must be approved before publishing "
                f"(status: {item.status.value})"
            )
        return self._replace_item(product_id, status=ReviewStatus.PUBLISHED)


def build_review_queue(results: list[ProductResult]) -> ReviewQueue:
    """Build the initial review queue from a batch of `ProductResult`s.

    Every item starts `ReviewStatus.PENDING` regardless of `needs_review` -
    see the module DESIGN NOTES for why nothing is auto-approved here.
    """
    items = tuple(
        ReviewItem(
            product_id=result.record.product_id,
            dual_script=result.correctness.dual_script,
            needs_review=result.needs_review,
            status=ReviewStatus.PENDING,
        )
        for result in results
    )
    return ReviewQueue(items=items)


def review_queue_to_json(queue: ReviewQueue) -> str:
    """Render `queue` as deterministic, human-reviewable JSON.

    Uses `ensure_ascii=False` so the `cirilica` field's Cyrillic text stays
    readable rather than being escaped, matching `provenance_to_json`.
    """
    payload = {
        "items": [
            {
                "product_id": item.product_id,
                "cirilica": item.dual_script.cirilica,
                "latinica": item.dual_script.latinica,
                "needs_review": item.needs_review,
                "status": item.status.value,
                "reason": item.reason,
            }
            for item in queue.items
        ]
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def review_queue_from_json(text: str) -> ReviewQueue:
    """Reconstruct a `ReviewQueue` from `review_queue_to_json` output."""
    payload = json.loads(text)
    items = tuple(
        ReviewItem(
            product_id=entry["product_id"],
            dual_script=DualScript(
                cirilica=entry["cirilica"], latinica=entry["latinica"]
            ),
            needs_review=entry["needs_review"],
            status=ReviewStatus(entry["status"]),
            reason=entry["reason"],
        )
        for entry in payload["items"]
    )
    return ReviewQueue(items=items)
