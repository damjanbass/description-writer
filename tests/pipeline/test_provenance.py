"""Tests for Stage 4 claims-provenance (sentence -> grounding attributes).

The compliance contract under test: every sentence is mapped to the structured
attributes that ground it, and any sentence asserting a number with no source
attribute is flagged so it lowers the report's clean verdict.
"""

import json

from pipeline.provenance import build_provenance, provenance_to_json
from pipeline.types import ProductRecord, ProvenanceReport


def _record(attributes: dict[str, str]) -> ProductRecord:
    return ProductRecord(product_id="1", attributes=attributes)


class TestBuildProvenanceSentences:
    def test_splits_on_terminal_punctuation_and_trims(self):
        record = _record({})
        report = build_provenance("Prva recenica.  Druga!  Treca?", record)
        assert [e.sentence for e in report.entries] == ["Prva recenica", "Druga", "Treca"]

    def test_empty_text_yields_no_entries(self):
        report = build_provenance("   ", _record({"color": "crna"}))
        assert report.entries == ()
        assert report.is_clean is True


class TestSupportingAttributes:
    def test_grounded_sentence_maps_to_attribute_key_and_stays_supported(self):
        record = _record({"color": "crna", "material": "koza"})
        report = build_provenance("Crna jakna izgleda elegantno.", record)
        assert len(report.entries) == 1
        entry = report.entries[0]
        # The literal value "crna" appears (case-insensitively) -> color grounds it.
        assert "color" in entry.supporting_attributes
        assert "material" not in entry.supporting_attributes
        assert entry.supported is True

    def test_numeric_value_grounds_attribute_even_without_literal_match(self):
        # The sentence carries the number 128 but not the literal "128GB" token;
        # the attribute must still be credited as supporting via numeric match.
        record = _record({"storage": "128GB"})
        report = build_provenance("Memorija je 128 gigabajta.", record)
        entry = report.entries[0]
        assert entry.supporting_attributes == ("storage",)
        assert entry.supported is True

    def test_supporting_attributes_follow_insertion_order(self):
        record = _record({"brand": "Samsung", "color": "crna"})
        report = build_provenance("Samsung crna varijanta.", record)
        assert report.entries[0].supporting_attributes == ("brand", "color")

    def test_matching_is_case_insensitive(self):
        record = _record({"brand": "Samsung"})
        report = build_provenance("SAMSUNG kvalitet.", record)
        assert report.entries[0].supporting_attributes == ("brand",)


class TestSupportedFlag:
    def test_hallucinated_number_is_flagged_and_lowers_is_clean(self):
        record = _record({"brand": "Samsung", "color": "crna"})
        report = build_provenance("Vodootporan do 50m dubine.", record)
        entry = report.entries[0]
        assert entry.supported is False
        assert entry.supporting_attributes == ()
        assert report.is_clean is False
        assert report.unsupported == (entry,)

    def test_attribute_free_prose_sentence_stays_supported(self):
        # No numbers and no matched attribute: asserts nothing falsifiable.
        record = _record({"brand": "Samsung"})
        report = build_provenance("Idealan poklon za svaku priliku.", record)
        entry = report.entries[0]
        assert entry.supporting_attributes == ()
        assert entry.supported is True
        assert report.is_clean is True

    def test_grounded_number_is_supported(self):
        record = _record({"battery": "5000mAh"})
        report = build_provenance("Baterija od 5000mAh.", record)
        assert report.entries[0].supported is True
        assert report.is_clean is True

    def test_mixed_sentences_only_the_hallucinated_one_is_flagged(self):
        record = _record({"battery": "5000mAh"})
        report = build_provenance("Baterija 5000mAh. Vodootporno do 100m.", record)
        good, bad = report.entries
        assert good.supported is True
        assert bad.supported is False
        assert report.is_clean is False
        assert report.unsupported == (bad,)


class TestProvenanceToJson:
    def test_round_trips_and_has_documented_keys(self):
        record = _record({"color": "crna"})
        report = build_provenance("Crna jakna. Otporna do 99m.", record)
        rendered = provenance_to_json(report)
        parsed = json.loads(rendered)

        assert set(parsed.keys()) == {"is_clean", "unsupported_sentences", "entries"}
        assert parsed["is_clean"] is False
        assert parsed["unsupported_sentences"] == ["Otporna do 99m"]

        first = parsed["entries"][0]
        assert set(first.keys()) == {"sentence", "supporting_attributes", "supported"}
        assert first["sentence"] == "Crna jakna"
        assert first["supporting_attributes"] == ["color"]
        assert first["supported"] is True

    def test_uses_two_space_indent_and_preserves_diacritics(self):
        record = _record({"material": "koža"})
        report = build_provenance("Materijal je koža.", record)
        rendered = provenance_to_json(report)
        # ensure_ascii=False keeps Serbian diacritics readable for the reviewer.
        assert "koža" in rendered
        assert "\n  " in rendered

    def test_clean_report_renders_empty_unsupported_list(self):
        record = _record({"color": "crna"})
        rendered = provenance_to_json(build_provenance("Crna jakna.", record))
        parsed = json.loads(rendered)
        assert parsed["is_clean"] is True
        assert parsed["unsupported_sentences"] == []

    def test_is_deterministic(self):
        record = _record({"brand": "Samsung", "color": "crna"})
        report = build_provenance("Samsung crna. Do 50m.", record)
        assert provenance_to_json(report) == provenance_to_json(report)


class TestEmptyReport:
    def test_empty_report_is_clean_json(self):
        rendered = provenance_to_json(ProvenanceReport(entries=()))
        parsed = json.loads(rendered)
        assert parsed == {"is_clean": True, "unsupported_sentences": [], "entries": []}
