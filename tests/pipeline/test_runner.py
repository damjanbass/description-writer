"""Tests for the Stage 5 batch orchestrator (pipeline.runner)."""

from __future__ import annotations

import csv
import json

from pipeline.generation import FakeProvider
from pipeline.runner import BatchProcessingError, process_product, run_batch, write_outputs
from pipeline.types import ProductRecord, Script


def _clean_record() -> ProductRecord:
    return ProductRecord(product_id="1", attributes={"brand": "Samsung", "storage": "128GB"})


def _dirty_record() -> ProductRecord:
    return ProductRecord(product_id="2", attributes={"brand": "Samsung", "color": "crna"})


def _scenario_response(prompt: str) -> str:
    if "128GB" in prompt:
        return "Samsung telefon. 128GB memorije."
    return "Samsung telefon. Vodootporan do 50m."


class TestProcessProduct:
    def test_composes_generation_correctness_and_provenance(self):
        record = _clean_record()
        provider = FakeProvider(_scenario_response)
        result = process_product(record, provider)

        assert result.record is record
        assert result.generated.source_script is Script.CIRILICA
        assert "128GB" in result.correctness.dual_script.latinica
        assert result.provenance.entries
        assert result.needs_review is False

    def test_unsupported_claim_propagates_to_needs_review(self):
        record = _dirty_record()
        provider = FakeProvider(_scenario_response)
        result = process_product(record, provider)

        assert result.needs_review is True
        assert result.correctness.claims.is_clean is False
        assert result.provenance.is_clean is False

    def test_latinica_source_script_is_respected(self):
        record = ProductRecord(product_id="3", attributes={"brand": "Samsung"})
        provider = FakeProvider("Samsung telefon.")
        result = process_product(record, provider, source_script=Script.LATINICA)

        assert result.generated.source_script is Script.LATINICA
        assert result.correctness.dual_script.latinica == "Samsung telefon."


class TestRunBatch:
    def test_processes_every_record_in_order(self):
        provider = FakeProvider(_scenario_response)
        results = run_batch([_clean_record(), _dirty_record()], provider)

        assert [r.record.product_id for r in results] == ["1", "2"]
        assert results[0].needs_review is False
        assert results[1].needs_review is True

    def test_one_failure_does_not_abort_the_batch(self):
        good_a = ProductRecord(product_id="a", attributes={})
        bad = ProductRecord(product_id="bad", attributes={"note": "BOOM"})
        good_b = ProductRecord(product_id="b", attributes={})

        class _RaisingProvider:
            def complete(self, prompt: str) -> str:
                if "BOOM" in prompt:
                    raise RuntimeError("simulated provider failure")
                return "Opis bez brojeva."

        try:
            run_batch([good_a, bad, good_b], _RaisingProvider())
            raise AssertionError("expected BatchProcessingError")
        except BatchProcessingError as exc:
            succeeded_ids = [r.record.product_id for r in exc.partial_results]
            # Both "a" and "b" were attempted despite "bad" raising in between -
            # a single bad record must not abort the rest of the batch.
            assert succeeded_ids == ["a", "b"]
            assert len(exc.failures) == 1
            assert exc.failures[0].record.product_id == "bad"
            assert isinstance(exc.failures[0].error, RuntimeError)


class TestWriteOutputs:
    def test_writes_csv_and_provenance_json(self, tmp_path):
        provider = FakeProvider(_scenario_response)
        results = run_batch([_clean_record(), _dirty_record()], provider)

        out_dir = tmp_path / "out"
        write_outputs(results, out_dir)

        csv_path = out_dir / "descriptions.csv"
        assert csv_path.exists()
        with open(csv_path, encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [row["product_id"] for row in rows] == ["1", "2"]
        assert rows[0]["needs_review"] == "False"
        assert rows[1]["needs_review"] == "True"
        assert "128GB" in rows[0]["latinica"]

        for product_id in ("1", "2"):
            json_path = out_dir / "provenance" / f"{product_id}.json"
            assert json_path.exists()
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            assert "is_clean" in payload
            assert "entries" in payload

    def test_creates_missing_output_directory(self, tmp_path):
        provider = FakeProvider("Opis bez brojeva.")
        results = run_batch([ProductRecord(product_id="x", attributes={})], provider)

        out_dir = tmp_path / "nested" / "out"
        assert not out_dir.exists()
        write_outputs(results, out_dir)
        assert (out_dir / "descriptions.csv").exists()

    def test_neutralizes_csv_formula_injection(self, tmp_path):
        provider = FakeProvider("Opis bez brojeva.")
        record = ProductRecord(product_id="=HYPERLINK(1)", attributes={})
        results = run_batch([record], provider)

        out_dir = tmp_path / "out"
        write_outputs(results, out_dir)

        # Read the raw cell: the dangerous leading "=" must have been escaped
        # with a single quote so a spreadsheet app treats it as text, and
        # stripping that quote recovers the original untrusted value.
        csv_path = out_dir / "descriptions.csv"
        with open(csv_path, encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        data_row = rows[1]
        assert data_row[0] == "'=HYPERLINK(1)"
        assert data_row[0].lstrip("'") == "=HYPERLINK(1)"

    def test_sanitizes_unsafe_product_id_for_filename(self, tmp_path):
        provider = FakeProvider("Opis bez brojeva.")
        record = ProductRecord(product_id="../../evil", attributes={})
        results = run_batch([record], provider)

        out_dir = tmp_path / "out"
        write_outputs(results, out_dir)

        # The sanitized file must land inside provenance/, never escape it.
        provenance_dir = out_dir / "provenance"
        children = list(provenance_dir.iterdir())
        assert len(children) == 1
        assert children[0].parent == provenance_dir
