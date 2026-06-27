"""Tests for the Phase 2 review/approval queue (pipeline.review).

The contract under test: building a queue never auto-approves anything (every
item starts PENDING, even a clean one); status transitions are guarded
(unknown ids and PUBLISHED-adjacent moves raise); every transition returns a
new, immutable `ReviewQueue`; and JSON round-trips losslessly, including
Cyrillic text and an absent `reason`.
"""

from __future__ import annotations

import json

from pipeline.generation import FakeProvider
from pipeline.review import (
    ReviewItem,
    ReviewQueue,
    ReviewStatus,
    build_review_queue,
    review_queue_from_json,
    review_queue_to_json,
)
from pipeline.runner import process_product
from pipeline.types import DualScript, ProductRecord


def _clean_record(product_id: str = "1") -> ProductRecord:
    return ProductRecord(product_id=product_id, attributes={"brand": "Samsung", "storage": "128GB"})


def _dirty_record(product_id: str = "2") -> ProductRecord:
    return ProductRecord(product_id=product_id, attributes={"brand": "Samsung", "color": "crna"})


def _scenario_response(prompt: str) -> str:
    if "128GB" in prompt:
        return "Samsung telefon. 128GB memorije."
    return "Samsung telefon. Vodootporan do 50m."


def _results(*records: ProductRecord) -> list:
    provider = FakeProvider(_scenario_response)
    return [process_product(record, provider) for record in records]


def _queue_with_two_items() -> ReviewQueue:
    # "1" is clean (needs_review False), "2" carries an unsupported claim
    # (needs_review True) - both must still land PENDING in the built queue.
    return build_review_queue(_results(_clean_record("1"), _dirty_record("2")))


class TestBuildReviewQueue:
    def test_every_item_starts_pending_regardless_of_needs_review(self):
        results = _results(_clean_record("1"), _dirty_record("2"))
        assert results[0].needs_review is False
        assert results[1].needs_review is True

        queue = build_review_queue(results)

        assert [item.status for item in queue.items] == [
            ReviewStatus.PENDING,
            ReviewStatus.PENDING,
        ]

    def test_preserves_product_order_and_carries_needs_review_and_dual_script(self):
        results = _results(_clean_record("1"), _dirty_record("2"))
        queue = build_review_queue(results)

        assert [item.product_id for item in queue.items] == ["1", "2"]
        assert queue.items[0].needs_review is False
        assert queue.items[1].needs_review is True
        assert queue.items[0].dual_script == results[0].correctness.dual_script
        assert queue.items[1].dual_script == results[1].correctness.dual_script

    def test_reason_is_none_for_freshly_built_items(self):
        queue = build_review_queue(_results(_clean_record("1")))
        assert queue.items[0].reason is None

    def test_empty_results_yields_empty_queue(self):
        queue = build_review_queue([])
        assert queue.items == ()


class TestGet:
    def test_returns_matching_item(self):
        queue = _queue_with_two_items()
        item = queue.get("2")
        assert item is not None
        assert item.product_id == "2"

    def test_returns_none_when_absent(self):
        queue = _queue_with_two_items()
        assert queue.get("missing") is None


class TestByStatus:
    def test_filters_and_preserves_order(self):
        queue = _queue_with_two_items()
        approved = queue.approve("2")

        pending = approved.by_status(ReviewStatus.PENDING)
        approved_items = approved.by_status(ReviewStatus.APPROVED)

        assert [item.product_id for item in pending] == ["1"]
        assert [item.product_id for item in approved_items] == ["2"]

    def test_empty_when_no_items_match(self):
        queue = _queue_with_two_items()
        assert queue.by_status(ReviewStatus.PUBLISHED) == ()


class TestApprove:
    def test_happy_path_sets_status_and_clears_reason(self):
        queue = _queue_with_two_items().reject("1", reason="needs rewrite")
        approved = queue.approve("1")

        item = approved.get("1")
        assert item.status is ReviewStatus.APPROVED
        assert item.reason is None

    def test_unknown_product_id_raises(self):
        queue = _queue_with_two_items()
        try:
            queue.approve("missing")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "unknown product_id: missing"

    def test_approving_published_item_raises(self):
        queue = _queue_with_two_items().approve("1").mark_published("1")
        try:
            queue.approve("1")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "product 1 is already published"

    def test_returns_new_queue_and_leaves_original_unchanged(self):
        queue = _queue_with_two_items()
        approved = queue.approve("1")

        assert approved is not queue
        assert queue.get("1").status is ReviewStatus.PENDING
        assert approved.get("1").status is ReviewStatus.APPROVED


class TestReject:
    def test_happy_path_sets_status_and_reason(self):
        queue = _queue_with_two_items()
        rejected = queue.reject("2", reason="hallucinated claim")

        item = rejected.get("2")
        assert item.status is ReviewStatus.REJECTED
        assert item.reason == "hallucinated claim"

    def test_reason_defaults_to_none(self):
        queue = _queue_with_two_items()
        rejected = queue.reject("2")
        assert rejected.get("2").reason is None

    def test_unknown_product_id_raises(self):
        queue = _queue_with_two_items()
        try:
            queue.reject("missing", reason="x")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "unknown product_id: missing"

    def test_rejecting_published_item_raises(self):
        queue = _queue_with_two_items().approve("1").mark_published("1")
        try:
            queue.reject("1", reason="too late")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "product 1 is already published"

    def test_returns_new_queue_and_leaves_original_unchanged(self):
        queue = _queue_with_two_items()
        rejected = queue.reject("2", reason="bad copy")

        assert rejected is not queue
        assert queue.get("2").status is ReviewStatus.PENDING
        assert queue.get("2").reason is None
        assert rejected.get("2").status is ReviewStatus.REJECTED


class TestMarkPublished:
    def test_happy_path_from_approved(self):
        queue = _queue_with_two_items().approve("1")
        published = queue.mark_published("1")
        assert published.get("1").status is ReviewStatus.PUBLISHED

    def test_unknown_product_id_raises(self):
        queue = _queue_with_two_items()
        try:
            queue.mark_published("missing")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "unknown product_id: missing"

    def test_non_approved_item_raises(self):
        queue = _queue_with_two_items()  # "1" is still PENDING
        try:
            queue.mark_published("1")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "product 1 must be approved before publishing (status: pending)"

    def test_already_published_item_raises(self):
        queue = _queue_with_two_items().approve("1").mark_published("1")
        try:
            queue.mark_published("1")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "product 1 must be approved before publishing (status: published)"

    def test_rejected_item_raises(self):
        queue = _queue_with_two_items().reject("1", reason="no")
        try:
            queue.mark_published("1")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "product 1 must be approved before publishing (status: rejected)"

    def test_returns_new_queue_and_leaves_original_unchanged(self):
        queue = _queue_with_two_items().approve("1")
        published = queue.mark_published("1")

        assert published is not queue
        assert queue.get("1").status is ReviewStatus.APPROVED
        assert published.get("1").status is ReviewStatus.PUBLISHED


class TestTransitionsPreserveOrderAndOtherItems:
    def test_approving_one_item_does_not_disturb_others_or_order(self):
        results = _results(_clean_record("1"), _dirty_record("2"), _clean_record("3"))
        queue = build_review_queue(results)

        approved = queue.approve("2")

        assert [item.product_id for item in approved.items] == ["1", "2", "3"]
        assert approved.get("1").status is ReviewStatus.PENDING
        assert approved.get("3").status is ReviewStatus.PENDING


class TestReviewQueueToJson:
    def test_round_trips_documented_shape(self):
        record = ProductRecord(product_id="1", attributes={"brand": "Samsung"})
        queue = build_review_queue(_results(record))
        rendered = review_queue_to_json(queue)
        parsed = json.loads(rendered)

        assert set(parsed.keys()) == {"items"}
        assert len(parsed["items"]) == 1
        entry = parsed["items"][0]
        assert set(entry.keys()) == {
            "product_id",
            "cirilica",
            "latinica",
            "needs_review",
            "status",
            "reason",
        }
        assert entry["product_id"] == "1"
        assert entry["status"] == "pending"
        assert entry["reason"] is None

    def test_status_is_rendered_as_value_string(self):
        queue = _queue_with_two_items().reject("2", reason="x")
        parsed = json.loads(review_queue_to_json(queue))
        statuses = {item["product_id"]: item["status"] for item in parsed["items"]}
        assert statuses["1"] == "pending"
        assert statuses["2"] == "rejected"

    def test_uses_two_space_indent_and_preserves_cyrillic(self):
        dual_script = DualScript(cirilica="Само ћирилица текст", latinica="Samo latinica tekst")
        item = ReviewItem(
            product_id="1",
            dual_script=dual_script,
            needs_review=False,
            status=ReviewStatus.PENDING,
        )
        rendered = review_queue_to_json(ReviewQueue(items=(item,)))
        # ensure_ascii=False keeps Cyrillic literal, not escaped to \uXXXX.
        assert "Само ћирилица текст" in rendered
        assert "\\u" not in rendered
        assert "\n  " in rendered

    def test_is_deterministic(self):
        queue = _queue_with_two_items()
        assert review_queue_to_json(queue) == review_queue_to_json(queue)


class TestReviewQueueFromJson:
    def test_round_trip_reconstructs_equal_queue(self):
        queue = _queue_with_two_items().reject("2", reason="hallucinated claim")
        rendered = review_queue_to_json(queue)
        reconstructed = review_queue_from_json(rendered)
        assert reconstructed == queue

    def test_round_trip_preserves_cyrillic_text(self):
        dual_script = DualScript(cirilica="Само ћирилица текст", latinica="Samo latinica tekst")
        item = ReviewItem(
            product_id="1",
            dual_script=dual_script,
            needs_review=True,
            status=ReviewStatus.APPROVED,
        )
        queue = ReviewQueue(items=(item,))

        reconstructed = review_queue_from_json(review_queue_to_json(queue))

        assert reconstructed == queue
        assert reconstructed.items[0].dual_script.cirilica == "Само ћирилица текст"

    def test_round_trip_preserves_reason_when_present(self):
        queue = _queue_with_two_items().reject("1", reason="needs human voice pass")
        reconstructed = review_queue_from_json(review_queue_to_json(queue))
        assert reconstructed.get("1").reason == "needs human voice pass"

    def test_round_trip_preserves_none_reason(self):
        queue = _queue_with_two_items()
        reconstructed = review_queue_from_json(review_queue_to_json(queue))
        assert reconstructed.get("1").reason is None
        assert reconstructed.get("2").reason is None

    def test_reconstructed_status_is_enum_member(self):
        queue = _queue_with_two_items().approve("1")
        reconstructed = review_queue_from_json(review_queue_to_json(queue))
        assert reconstructed.get("1").status is ReviewStatus.APPROVED

    def test_empty_items_round_trips(self):
        queue = ReviewQueue(items=())
        reconstructed = review_queue_from_json(review_queue_to_json(queue))
        assert reconstructed == queue
