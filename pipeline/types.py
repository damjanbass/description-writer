"""Shared data contracts for the Phase 1 batch pipeline.

This is the seam every pipeline stage composes through, analogous to how
`core/*/types.py` defines the pack contracts for the correctness core. The
stage modules (ingest -> generation -> correctness -> provenance -> runner)
must keep their public signatures aligned to these shapes so the pipeline
composes without any stage re-inventing a record format.

Script convention (see lang/sr/alphabet.py): generation produces *ćirilica*
(Cyrillic) as the source script because Cyrillic->Latin is the lossless,
exception-free transliteration direction. The latinica rendering is derived
by transliteration, never regenerated (hard rule in doc/CLAUDE.md). All
grammatical analysis (agreement/claims/provenance) runs on the *latinica*
rendering, because the Serbian agreement and claim heuristics in lang/sr are
defined over Latin-script forms and product attribute values are
conventionally latinica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.agreement.types import AgreementIssue
from core.claims.types import ClaimsReport

# Attribute keys whose values carry brand / model / SKU-like tokens that must
# be protected verbatim during transliteration (the highest-confidence
# protected-term signal, tied to structured input — see
# lang/sr/protected_terms.py). Matched case-insensitively against column names.
PROTECTED_ATTRIBUTE_KEYS: frozenset[str] = frozenset({
    "brand",
    "model",
    "model_number",
    "model_no",
    "sku",
    "mpn",
    "ean",
    "gtin",
    "barcode",
    "manufacturer",
})


class Script(Enum):
    CIRILICA = "cirilica"  # Cyrillic — the lossless source script for generation
    LATINICA = "latinica"  # Latin — derived by transliteration; the analysis script


@dataclass(frozen=True)
class ProductRecord:
    """One input product, normalized from a CSV/XLSX row.

    `attributes` holds only the non-empty columns and is the structured data
    that generation is grounded to (no claim may be asserted that is not
    traceable here). `raw_row` keeps the original row verbatim (including
    empty cells) for round-tripping and provenance/debugging.
    """

    product_id: str
    attributes: dict[str, str]
    raw_row: dict[str, str] = field(default_factory=dict)

    @property
    def glossary(self) -> frozenset[str]:
        """Brand/model/SKU tokens to protect verbatim during transliteration.

        Derived from the values of PROTECTED_ATTRIBUTE_KEYS, whitespace-split
        into individual tokens. Passed straight into
        `core.transliteration.engine.transliterate(..., glossary=...)`, tying
        protection to the product's own structured input.
        """
        tokens: set[str] = set()
        for key, value in self.attributes.items():
            if key.lower() in PROTECTED_ATTRIBUTE_KEYS:
                tokens.update(value.split())
        return frozenset(t for t in tokens if t)


@dataclass(frozen=True)
class GeneratedCopy:
    """Raw LLM output for one product, in a single source script."""

    text: str
    source_script: Script = Script.CIRILICA


@dataclass(frozen=True)
class DualScript:
    """The same description in both Serbian scripts, from one generation."""

    cirilica: str
    latinica: str

    def in_script(self, script: Script) -> str:
        return self.cirilica if script is Script.CIRILICA else self.latinica


@dataclass(frozen=True)
class ProvenanceEntry:
    """One generated sentence mapped to the attributes that ground it."""

    sentence: str
    supporting_attributes: tuple[str, ...]
    supported: bool


@dataclass(frozen=True)
class ProvenanceReport:
    """Claims-provenance view: every factual sentence -> its source attributes.

    The compliance artifact for Zakon o zaštiti potrošača 88/2021 — it makes
    every factual claim traceable to structured input and flags any sentence
    that is not.
    """

    entries: tuple[ProvenanceEntry, ...]

    @property
    def unsupported(self) -> tuple[ProvenanceEntry, ...]:
        return tuple(e for e in self.entries if not e.supported)

    @property
    def is_clean(self) -> bool:
        return all(e.supported for e in self.entries)


@dataclass(frozen=True)
class CorrectnessResult:
    """Output of the correctness layer for one product: the dual-script copy
    plus every issue the Phase 0 validators surfaced for human review.
    """

    dual_script: DualScript
    claims: ClaimsReport
    agreement_issues: tuple[AgreementIssue, ...]

    @property
    def needs_review(self) -> bool:
        return (not self.claims.is_clean) or bool(self.agreement_issues)


@dataclass(frozen=True)
class ProductResult:
    """Everything the pipeline produced for one input product."""

    record: ProductRecord
    generated: GeneratedCopy
    correctness: CorrectnessResult
    provenance: ProvenanceReport

    @property
    def needs_review(self) -> bool:
        return self.correctness.needs_review or not self.provenance.is_clean
