"""Tests for the Stage 3 correctness layer (pipeline/correctness.py).

These exercise the *orchestration*: that the Phase 0 engines are wired onto a
GeneratedCopy correctly. The engines' own rule coverage lives in tests/core
and tests/lang — here we assert the seam: dual-script derivation, protected
tokens surviving in both scripts, and each validator's output reaching the
CorrectnessResult and driving needs_review. No network, no LLM.
"""

from core.transliteration.engine import transliterate
from core.transliteration.types import Direction
from lang.sr import SR_PACK
from pipeline.correctness import apply_correctness
from pipeline.types import GeneratedCopy, ProductRecord, Script


def _record(**attributes: str) -> ProductRecord:
    return ProductRecord(product_id="p1", attributes=dict(attributes))


class TestDualScript:
    def test_cirilica_source_produces_both_scripts(self):
        # Plain feminine-singular phrase: clean nominative agreement.
        generated = GeneratedCopy("Црна кожна торба.", Script.CIRILICA)
        result = apply_correctness(generated, _record(boja="crna"))

        # Source script is preserved verbatim; latinica is the transliteration.
        assert result.dual_script.cirilica == "Црна кожна торба."
        assert result.dual_script.latinica == "Crna kožna torba."

    def test_latinica_source_also_produces_both_scripts(self):
        # Requirement (f): a latinica-source generation still yields both scripts.
        generated = GeneratedCopy("Crna kožna torba.", Script.LATINICA)
        result = apply_correctness(generated, _record(boja="crna"))

        assert result.dual_script.latinica == "Crna kožna torba."
        assert result.dual_script.cirilica == "Црна кожна торба."

    def test_round_trip_is_consistent_between_scripts(self):
        # Requirement (b): ćirilica↔latinica round-trips on a normal phrase.
        cirilica = "Црвена памучна мајица."
        generated = GeneratedCopy(cirilica, Script.CIRILICA)
        result = apply_correctness(generated, _record(boja="crvena"))

        # Latinica re-transliterated back to Cyrillic must recover the source.
        back = transliterate(
            result.dual_script.latinica, SR_PACK, Direction.SCRIPT_B_TO_A
        )
        assert back == cirilica
        assert result.dual_script.latinica == "Crvena pamučna majica."


class TestProtectedTokens:
    def test_brand_token_identical_in_both_scripts_from_cirilica(self):
        # Requirement (a): a protected brand token is byte-for-byte identical in
        # BOTH scripts. "iPhone" is protected by its camelCase shape AND by the
        # glossary (brand attribute), so it must never transliterate.
        generated = GeneratedCopy("Нови iPhone телефон.", Script.CIRILICA)
        result = apply_correctness(generated, _record(brand="iPhone"))

        assert "iPhone" in result.dual_script.cirilica
        assert "iPhone" in result.dual_script.latinica

    def test_glossary_brand_protected_when_token_is_plain_latin(self):
        # A brand made only of Serbian-Latin letters ("Lenovo") has no intrinsic
        # protected-shape signal; it survives in both scripts ONLY because the
        # product's glossary (record.glossary) is threaded into transliteration.
        generated = GeneratedCopy("Lenovo laptop.", Script.LATINICA)
        result = apply_correctness(generated, _record(brand="Lenovo"))

        # In both scripts the brand is verbatim Latin; the common noun is not.
        assert "Lenovo" in result.dual_script.latinica
        assert "Lenovo" in result.dual_script.cirilica
        # Sanity: the non-protected word DID transliterate (so this isn't a no-op).
        assert "laptop" in result.dual_script.latinica
        assert "лаптоп" in result.dual_script.cirilica


class TestClaims:
    def test_hallucinated_number_is_unsupported(self):
        # Requirement (c): a number in the text but not in attributes surfaces in
        # result.claims.unsupported and forces review.
        generated = GeneratedCopy("Батерија од 5000 mAh.", Script.CIRILICA)
        result = apply_correctness(generated, _record(kapacitet="4000 mAh"))

        unsupported_texts = [u.claim_text for u in result.claims.unsupported]
        assert any("5000" in t for t in unsupported_texts)
        assert result.claims.is_clean is False
        assert result.needs_review is True

    def test_grounded_number_is_supported(self):
        # The same shape, but the number matches an attribute → clean claims.
        generated = GeneratedCopy("Батерија од 4000 mAh.", Script.CIRILICA)
        result = apply_correctness(generated, _record(kapacitet="4000 mAh"))

        assert result.claims.is_clean is True


class TestAgreement:
    def test_gender_mismatch_surfaces_as_issue(self):
        # Requirement (d): "crna kaiš" (feminine adjective + masculine noun) is an
        # agreement mismatch. Generate it in latinica so the validator (Latin
        # heuristics) sees the exact forms.
        generated = GeneratedCopy("Crna kaiš sa metalnom kopčom.", Script.LATINICA)
        result = apply_correctness(generated, _record(boja="crna"))

        assert len(result.agreement_issues) >= 1
        issue = result.agreement_issues[0]
        assert issue.adjective == "Crna"
        assert issue.noun == "kaiš"
        assert issue.actual_ending == "a"
        assert result.needs_review is True

    def test_mismatch_detected_from_cirilica_source_too(self):
        # The mismatch must be caught even when generation was Cyrillic: analysis
        # runs on the derived latinica, so transliteration must precede it.
        generated = GeneratedCopy("Црна каиш.", Script.CIRILICA)
        result = apply_correctness(generated, _record(boja="crna"))

        assert len(result.agreement_issues) >= 1
        assert result.agreement_issues[0].noun == "kaiš"

    def test_function_words_and_oblique_forms_do_not_false_positive(self):
        # Realistic clean copy with prepositions, a conjunction, and oblique-case
        # phrases (-og/-im/-om endings). The heuristic must not flag any of these
        # as agreement issues — only genuine nominative mismatches.
        text = "Crna kožna torba od pravog pamuka i sa kratkim drškama."
        generated = GeneratedCopy(text, Script.LATINICA)
        result = apply_correctness(generated, _record(boja="crna"))

        assert result.agreement_issues == ()


class TestNeedsReview:
    def test_clean_product_does_not_need_review(self):
        # Requirement (e): a clean product (no bad numbers, correct agreement)
        # yields needs_review == False.
        generated = GeneratedCopy("Crna kožna torba od kvalitetnog materijala.", Script.LATINICA)
        result = apply_correctness(generated, _record(boja="crna", materijal="koža"))

        assert result.claims.is_clean is True
        assert result.agreement_issues == ()
        assert result.needs_review is False

    def test_clean_product_from_cirilica_source_does_not_need_review(self):
        generated = GeneratedCopy("Црвена памучна мајица.", Script.CIRILICA)
        result = apply_correctness(generated, _record(boja="crvena", materijal="pamuk"))

        assert result.needs_review is False
