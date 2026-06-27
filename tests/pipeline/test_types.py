"""Tests for the shared pipeline data contracts (the composition spine)."""

from core.agreement.types import AgreementIssue
from core.claims.types import ClaimsReport, UnsupportedClaim
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


def _clean_claims() -> ClaimsReport:
    return ClaimsReport(
        unsupported=(),
        referenced_attributes=frozenset(),
        unreferenced_attributes=frozenset(),
    )


class TestProductRecordGlossary:
    def test_glossary_collects_protected_attribute_tokens(self):
        record = ProductRecord(
            product_id="1",
            attributes={"brand": "Samsung", "model": "Galaxy S24", "color": "crna"},
        )
        # brand + model tokens are protected; ordinary attributes (color) are not.
        assert record.glossary == frozenset({"Samsung", "Galaxy", "S24"})

    def test_glossary_is_case_insensitive_on_keys(self):
        record = ProductRecord(product_id="1", attributes={"Brand": "Sony", "SKU": "XM5"})
        assert record.glossary == frozenset({"Sony", "XM5"})

    def test_glossary_empty_when_no_protected_keys(self):
        record = ProductRecord(product_id="1", attributes={"color": "crna"})
        assert record.glossary == frozenset()


class TestDualScript:
    def test_in_script_selects_rendering(self):
        dual = DualScript(cirilica="Црна мајица", latinica="Crna majica")
        assert dual.in_script(Script.CIRILICA) == "Црна мајица"
        assert dual.in_script(Script.LATINICA) == "Crna majica"


class TestProvenanceReport:
    def test_unsupported_and_is_clean(self):
        clean = ProvenanceEntry("Crna majica.", ("color",), True)
        bad = ProvenanceEntry("Vodootporan do 50m.", (), False)
        assert ProvenanceReport((clean,)).is_clean
        report = ProvenanceReport((clean, bad))
        assert not report.is_clean
        assert report.unsupported == (bad,)


class TestNeedsReview:
    def test_clean_product_does_not_need_review(self):
        correctness = CorrectnessResult(
            dual_script=DualScript("a", "a"), claims=_clean_claims(), agreement_issues=()
        )
        result = ProductResult(
            record=ProductRecord("1", {}),
            generated=GeneratedCopy("a", Script.CIRILICA),
            correctness=correctness,
            provenance=ProvenanceReport(()),
        )
        assert result.needs_review is False

    def test_agreement_issue_forces_review(self):
        issue = AgreementIssue("crna", "kaiš", frozenset({"i"}), "a", "mismatch")
        correctness = CorrectnessResult(
            dual_script=DualScript("a", "a"), claims=_clean_claims(), agreement_issues=(issue,)
        )
        assert correctness.needs_review is True

    def test_unsupported_claim_forces_review(self):
        claims = ClaimsReport(
            unsupported=(UnsupportedClaim("50m", (0, 3)),),
            referenced_attributes=frozenset(),
            unreferenced_attributes=frozenset(),
        )
        correctness = CorrectnessResult(
            dual_script=DualScript("a", "a"), claims=claims, agreement_issues=()
        )
        assert correctness.needs_review is True
