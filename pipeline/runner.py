"""Stage 5 — batch orchestrator. Composes ingest -> generate -> correct ->
provenance into one run and writes reviewable outputs.

`process_product` is pure composition of the real stage functions (generation
-> correctness -> provenance) and adds no new rules of its own.

`run_batch` must not let one bad record abort a 50k-row catalog run, but it
also must not silently swallow a failure. The chosen strategy: every record
is attempted independently; if any raise, processing still completes for the
rest, and a single `BatchProcessingError` is raised at the end carrying BOTH
the successful `partial_results` and the per-record `failures`. A caller that
wants to proceed with a partial batch must explicitly catch the exception and
read `.partial_results` - an unhandled failure is loud, never a quietly
truncated result list.

`write_outputs` is the artifact a catalog manager reviews: one CSV row per
product (for a quick reviewable pass) plus one detailed provenance JSON per
product (for the compliance audit trail).
"""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pipeline.correctness import apply_correctness
from pipeline.generation import Provider, generate_description
from pipeline.provenance import build_provenance, provenance_to_json
from pipeline.types import ProductRecord, ProductResult, Script

# Allow-list for provenance filenames: `product_id` comes from untrusted
# catalog data (a CSV/XLSX cell), so anything that isn't alphanumeric/./_/-
# is replaced rather than passed through to a filesystem path - this is what
# keeps a crafted id like "../../evil" from writing outside `provenance_dir`.
_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def process_product(
    record: ProductRecord, provider: Provider, *, source_script: Script = Script.CIRILICA
) -> ProductResult:
    """Run one product through generation -> correctness -> provenance.

    Provenance is built from `correctness.dual_script.latinica` because the
    claims/agreement heuristics it relies on (via core.claims) are defined
    over Latin-script forms, matching the convention in pipeline.correctness.
    """
    generated = generate_description(record, provider, script=source_script)
    correctness = apply_correctness(generated, record)
    provenance = build_provenance(correctness.dual_script.latinica, record)
    return ProductResult(
        record=record,
        generated=generated,
        correctness=correctness,
        provenance=provenance,
    )


@dataclass(frozen=True)
class BatchFailure:
    """One record that raised while being processed, paired with its error."""

    record: ProductRecord
    error: BaseException


class BatchProcessingError(RuntimeError):
    """Raised by `run_batch` when one or more records failed to process.

    Every record is still attempted - a failure never aborts the batch - so
    `partial_results` holds every `ProductResult` that succeeded and
    `failures` holds what went wrong for the rest. Raising (rather than
    returning a partial list silently) means a caller must explicitly opt in
    to proceeding with an incomplete batch instead of a dropped product going
    unnoticed across a 50k-row run.
    """

    def __init__(
        self, partial_results: list[ProductResult], failures: list[BatchFailure]
    ) -> None:
        self.partial_results = partial_results
        self.failures = failures
        total = len(partial_results) + len(failures)
        ids = ", ".join(f.record.product_id for f in failures)
        super().__init__(f"{len(failures)} of {total} product(s) failed to process: {ids}")


def run_batch(
    records: Iterable[ProductRecord],
    provider: Provider,
    *,
    source_script: Script = Script.CIRILICA,
) -> list[ProductResult]:
    """Process every record independently; never abort on one failure.

    If every record succeeds, the results are returned normally. If any
    record raised, every other record is still processed to completion, then
    a single `BatchProcessingError` is raised carrying both the results that
    succeeded and the per-record failures (see its docstring for why raising,
    not swallowing, is the chosen contract).
    """
    results: list[ProductResult] = []
    failures: list[BatchFailure] = []
    for record in records:
        try:
            results.append(process_product(record, provider, source_script=source_script))
        except Exception as exc:
            failures.append(BatchFailure(record=record, error=exc))
    if failures:
        raise BatchProcessingError(results, failures)
    return results


def _safe_filename(product_id: str) -> str:
    """Sanitize `product_id` for use as a provenance filename component."""
    sanitized = _UNSAFE_FILENAME_RE.sub("_", product_id)
    return sanitized or "_"


def write_outputs(results: Iterable[ProductResult], out_dir: str | os.PathLike[str]) -> None:
    """Write descriptions.csv and one provenance/<product_id>.json per product.

    Both scripts go in the CSV so a reviewer can scan the whole batch in one
    file; the per-product JSON carries the full sentence-level provenance for
    the compliance audit trail. `out_dir` (and its `provenance` subdirectory)
    is created if missing. UTF-8 without a BOM, `newline=""`, since the
    ćirilica rendering needs full Unicode and csv's own line-ending handling
    requires the caller to disable text-mode newline translation.
    """
    out_path = Path(out_dir)
    provenance_dir = out_path / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)

    results = list(results)

    csv_path = out_path / "descriptions.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["product_id", "latinica", "cirilica", "needs_review"])
        for result in results:
            writer.writerow([
                result.record.product_id,
                result.correctness.dual_script.latinica,
                result.correctness.dual_script.cirilica,
                result.needs_review,
            ])

    for result in results:
        filename = _safe_filename(result.record.product_id) + ".json"
        (provenance_dir / filename).write_text(
            provenance_to_json(result.provenance), encoding="utf-8"
        )
