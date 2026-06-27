"""Data shapes for claims-grounding (core/CLAUDE.md Layer 2: never assert
an attribute not present in the structured input).

v1 scope: numeric claims only (measurements, capacities, counts - the
highest-risk hallucination target for compliance under Zakon o zastiti
potrosaca 88/2021). Detecting non-numeric unsupported claims (e.g. an
invented adjective like "vodootporan" with no matching attribute) needs
real claim extraction/NLI and is out of scope for a rule-based v1.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnsupportedClaim:
    claim_text: str
    span: tuple[int, int]


@dataclass(frozen=True)
class ClaimsReport:
    unsupported: tuple[UnsupportedClaim, ...]
    referenced_attributes: frozenset[str]
    unreferenced_attributes: frozenset[str]

    @property
    def is_clean(self) -> bool:
        return len(self.unsupported) == 0
