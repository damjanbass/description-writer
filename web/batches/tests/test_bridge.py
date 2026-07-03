"""Tests for batches.bridge: the Django<->pipeline mapping layer."""
from __future__ import annotations

from accounts.models import Organization
from django.test import TestCase

from batches.bridge import build_review_items, export_review_queue_json
from batches.models import Batch, ReviewItem
from core.claims.types import ClaimsReport
from pipeline.review import ReviewStatus, review_queue_from_json
from pipeline.types import (
    CorrectnessResult,
    DualScript,
    GeneratedCopy,
    ProductRecord,
    ProductResult,
    ProvenanceEntry,
    ProvenanceReport,
    Script,
)


def _make_org():
    return Organization.objects.create(name="Acme", slug="acme")


def _make_batch(org):
    return Batch.objects.create(
        name="B", organization=org, source_file="orgs/acme/batches/x.csv"
    )


def _make_product_result(product_id="p1", *, unsupported=()):
    record = ProductRecord(product_id=product_id, attributes={"brand": "Acme"})
    generated = GeneratedCopy(text="Ћирилица текст.", source_script=Script.CIRILICA)
    dual = DualScript(cirilica="Ћирилица текст.", latinica="Latinica tekst.")
    claims = ClaimsReport(
        unsupported=unsupported,
        referenced_attributes=frozenset({"brand"}),
        unreferenced_attributes=frozenset(),
    )
    correctness = CorrectnessResult(dual_script=dual, claims=claims, agreement_issues=())
    provenance = ProvenanceReport(
        entries=(
            ProvenanceEntry(
                sentence="Latinica tekst",
                supporting_attributes=("brand",),
                supported=True,
            ),
        )
    )
    return ProductResult(
        record=record, generated=generated, correctness=correctness, provenance=provenance
    )


class BuildReviewItemsTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.batch = _make_batch(self.org)

    def test_build_review_items_maps_fields(self):
        result = _make_product_result("sku-1")
        items = build_review_items(self.batch, [result])
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.batch, self.batch)
        self.assertEqual(item.product_id, "sku-1")
        self.assertEqual(item.cirilica, "Ћирилица текст.")
        self.assertEqual(item.latinica, "Latinica tekst.")
        self.assertEqual(item.status, ReviewItem.Status.PENDING)
        self.assertFalse(item.needs_review)
        self.assertEqual(item.attributes, {"brand": "Acme"})
        self.assertTrue(item.provenance["is_clean"])
        self.assertEqual(len(item.provenance["entries"]), 1)

    def test_needs_review_true_when_correctness_needs_review(self):
        from core.claims.types import UnsupportedClaim

        result = _make_product_result(
            "sku-2", unsupported=(UnsupportedClaim(claim_text="99cm", span=(0, 4)),)
        )
        self.assertTrue(result.needs_review)
        items = build_review_items(self.batch, [result])
        self.assertTrue(items[0].needs_review)
        # Nothing auto-approves regardless of needs_review.
        self.assertEqual(items[0].status, ReviewItem.Status.PENDING)

    def test_build_review_items_is_bulk_create_ready(self):
        results = [_make_product_result(f"p{i}") for i in range(3)]
        items = build_review_items(self.batch, results)
        ReviewItem.objects.bulk_create(items)
        self.assertEqual(ReviewItem.objects.filter(batch=self.batch).count(), 3)


class ExportReviewQueueJsonTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.batch = _make_batch(self.org)

    def test_round_trips_through_pipeline_review_queue_from_json(self):
        ReviewItem.objects.create(
            batch=self.batch,
            product_id="a1",
            cirilica="Ћирилица A",
            latinica="Latinica A",
            needs_review=True,
            status=ReviewItem.Status.PENDING,
        )
        ReviewItem.objects.create(
            batch=self.batch,
            product_id="a2",
            cirilica="Ћирилица B",
            latinica="Latinica B",
            needs_review=False,
            status=ReviewItem.Status.APPROVED,
            reason="",
        )
        ReviewItem.objects.create(
            batch=self.batch,
            product_id="a3",
            cirilica="Ћирилица C",
            latinica="Latinica C",
            needs_review=True,
            status=ReviewItem.Status.REJECTED,
            reason="Missing spec",
        )

        raw_json = export_review_queue_json(self.batch)
        queue = review_queue_from_json(raw_json)

        self.assertEqual(len(queue.items), 3)
        # ReviewItem.Meta.ordering is by product_id, so the queue is ordered too.
        self.assertEqual([i.product_id for i in queue.items], ["a1", "a2", "a3"])

        a1 = queue.get("a1")
        self.assertEqual(a1.status, ReviewStatus.PENDING)
        self.assertEqual(a1.dual_script.cirilica, "Ћирилица A")
        self.assertEqual(a1.dual_script.latinica, "Latinica A")
        self.assertTrue(a1.needs_review)
        self.assertIsNone(a1.reason)

        a2 = queue.get("a2")
        self.assertEqual(a2.status, ReviewStatus.APPROVED)

        a3 = queue.get("a3")
        self.assertEqual(a3.status, ReviewStatus.REJECTED)
        self.assertEqual(a3.reason, "Missing spec")

    def test_export_empty_batch_is_valid_json(self):
        raw_json = export_review_queue_json(self.batch)
        queue = review_queue_from_json(raw_json)
        self.assertEqual(queue.items, ())
