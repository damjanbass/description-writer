"""Stage 4 — claims-provenance report. analysis text -> ProvenanceReport.

The compliance artifact: every factual sentence in the generated copy is
mapped to the structured attribute(s) that ground it; sentences asserting a
number with no source attribute are flagged unsupported. Builds ON TOP of
core.claims (reuse it for the numeric grounding decision — do not duplicate
the regex logic).

IMPLEMENTATION CONTRACT (keep public signatures stable):

`build_provenance(text, record) -> ProvenanceReport`
  - `text` is the LATINICA analysis rendering (what the runner passes from
    CorrectnessResult.dual_script.latinica).
  - Split `text` into sentences (a simple `[.!?]` splitter is fine; keep
    non-empty trimmed sentences).
  - For each sentence build a `ProvenanceEntry`:
      * `supporting_attributes` = tuple of attribute KEYS whose value is
        evidenced in the sentence. Reuse the matching idea from
        `core.claims.find_unreferenced_attributes` (literal, case-insensitive
        substring) AND treat any attribute whose numeric value appears in the
        sentence as supporting.
      * `supported` = the sentence is clean iff it contains no unsupported
        numeric claim per `core.claims.find_unsupported_numeric_claims(
        sentence, record.attributes)`. A sentence with no numbers and no
        matched attribute is still `supported=True` (it asserts nothing
        falsifiable) — only an UNSUPPORTED NUMBER makes it False.
  - Return `ProvenanceReport(entries=...)`.

`provenance_to_json(report) -> str`
  - Deterministic, human-reviewable JSON (indent=2, ensure_ascii=False) with
    each entry's sentence, supporting_attributes, supported, plus a top-level
    `is_clean` and the list of unsupported sentences. This is the file a
    catalog manager / legal reviewer reads.

Tests go in tests/pipeline/test_provenance.py. Cover: a grounded sentence maps
to its attribute and stays supported; a hallucinated-number sentence is
flagged unsupported and lowers report.is_clean; an attribute-free prose
sentence stays supported; JSON round-trips via json.loads with the documented
keys.

DESIGN NOTES (why it is built this way):
  - We delegate the numeric grounding decision wholesale to
    `core.claims.find_unsupported_numeric_claims` rather than re-deriving "is
    this number in the attributes?" here. That keeps the 0%-tolerance numeric
    rule (decimal-comma normalization, unit-token handling) defined in exactly
    one place — the compliance bar must not drift between Stage 3 (claims) and
    Stage 4 (provenance).
  - Numeric *attribution* (which attribute grounds a number) is computed by
    probing the same engine per-attribute: a sentence number is grounded by
    attribute K iff checking the sentence against only `{K: value}` flags
    fewer claims than checking it against no attributes at all. This reuses the
    engine's number-extraction/normalization instead of duplicating the regex.
  - Attribute order is `record.attributes` insertion order, so the report is
    deterministic and reads in the same column order the catalog manager input.
"""

from __future__ import annotations

import json
import re

from core.claims.engine import find_unsupported_numeric_claims
from pipeline.types import ProductRecord, ProvenanceEntry, ProvenanceReport

# A sentence boundary is any of `.`, `!`, `?`. This is intentionally simple
# (the spec calls for a `[.!?]` split): the analysis text is machine-generated
# marketing copy, not prose with abbreviations, so we do not need an
# abbreviation-aware tokenizer here.
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]")


def _split_sentences(text: str) -> list[str]:
    """Split `text` into trimmed, non-empty sentences on `[.!?]`."""
    return [chunk.strip() for chunk in _SENTENCE_SPLIT_RE.split(text) if chunk.strip()]


def _attribute_grounds_number(sentence: str, key: str, value: str) -> bool:
    """True iff a number from attribute `value` appears in `sentence`.

    Computed by re-running the claims engine against a single-attribute view:
    if isolating `{key: value}` leaves fewer numeric claims unsupported than the
    empty-attribute baseline, then this attribute accounts for at least one of
    the sentence's numbers. This deliberately routes every numeric comparison
    back through `find_unsupported_numeric_claims` so the matching logic lives
    only in core.claims.
    """
    baseline = len(find_unsupported_numeric_claims(sentence, {}))
    with_attribute = len(find_unsupported_numeric_claims(sentence, {key: value}))
    return with_attribute < baseline


def _supporting_attributes(sentence: str, record: ProductRecord) -> tuple[str, ...]:
    """Attribute keys evidenced in `sentence`, in `record.attributes` order.

    An attribute supports the sentence when either its value appears as a
    case-insensitive literal substring (the `find_unreferenced_attributes`
    idea, applied positively) OR one of its numbers appears in the sentence.
    """
    lowered_sentence = sentence.lower()
    supporting: list[str] = []
    for key, value in record.attributes.items():
        value_str = str(value)
        substring_match = bool(value_str) and value_str.lower() in lowered_sentence
        if substring_match or _attribute_grounds_number(sentence, key, value_str):
            supporting.append(key)
    return tuple(supporting)


def build_provenance(text: str, record: ProductRecord) -> ProvenanceReport:
    """Map each sentence of the latinica analysis text to its source attributes.

    See the module docstring for the full contract. The only thing that can
    make a sentence `supported=False` is an unsupported numeric claim — prose
    with no numbers (even if it matches no attribute) asserts nothing
    falsifiable and stays supported.
    """
    entries: list[ProvenanceEntry] = []
    for sentence in _split_sentences(text):
        supported = not find_unsupported_numeric_claims(sentence, record.attributes)
        entries.append(
            ProvenanceEntry(
                sentence=sentence,
                supporting_attributes=_supporting_attributes(sentence, record),
                supported=supported,
            )
        )
    return ProvenanceReport(entries=tuple(entries))


def provenance_to_json(report: ProvenanceReport) -> str:
    """Render `report` as deterministic, human-reviewable JSON.

    The top-level `is_clean` and `unsupported_sentences` are the at-a-glance
    verdict for a catalog manager / legal reviewer; `entries` carries the full
    sentence -> attribute mapping for an audit trail. Uses
    `ensure_ascii=False` so Serbian diacritics stay readable in the artifact.
    """
    payload = {
        "is_clean": report.is_clean,
        "unsupported_sentences": [e.sentence for e in report.unsupported],
        "entries": [
            {
                "sentence": entry.sentence,
                "supporting_attributes": list(entry.supporting_attributes),
                "supported": entry.supported,
            }
            for entry in report.entries
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
