"""Rule-based claims grounding: flag numeric claims in generated text that
don't trace back to any value in the product's structured attributes.

Why numbers specifically: they are the highest-confidence signal for
hallucination (a spec the model invented) and, unlike adjectives, are
almost invariant across Serbian grammatical case - "128GB" or "6.1" does
not decline, so a literal-text match against the source attributes is
reliable without any language-specific normalization. This is deliberately
narrower than full claim extraction (e.g. it won't catch an invented
non-numeric claim like an unsupported material) - see core/claims/types.py.
"""

from __future__ import annotations

import re

from core.claims.types import ClaimsReport, UnsupportedClaim

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_CLAIM_RE = re.compile(r"\d+(?:[.,]\d+)?\s*[A-Za-zčćžšđČĆŽŠĐ%]*")


def _normalize_number(raw: str) -> str:
    return raw.replace(",", ".")


def _attribute_numbers(attributes: dict[str, object]) -> set[str]:
    numbers: set[str] = set()
    for value in attributes.values():
        for match in _NUMBER_RE.finditer(str(value)):
            numbers.add(_normalize_number(match.group(0)))
    return numbers


def find_unsupported_numeric_claims(
    text: str, attributes: dict[str, object]
) -> tuple[UnsupportedClaim, ...]:
    """Numeric claims in `text` whose number does not appear anywhere in
    `attributes`' values. An empty result is the Phase 0 compliance bar:
    every number in generated copy must be traceable to input data.
    """
    known_numbers = _attribute_numbers(attributes)
    issues: list[UnsupportedClaim] = []
    for match in _CLAIM_RE.finditer(text):
        number_match = _NUMBER_RE.match(match.group(0))
        if number_match is None:
            continue
        if _normalize_number(number_match.group(0)) not in known_numbers:
            issues.append(
                UnsupportedClaim(claim_text=match.group(0).strip(), span=match.span())
            )
    return tuple(issues)


def find_unreferenced_attributes(text: str, attributes: dict[str, object]) -> frozenset[str]:
    """Attribute keys whose value does not appear verbatim in `text`.

    Best-effort and informational only: a literal substring check will
    under-report usage when the value was used in a different grammatical
    case (e.g. attribute "crna" appearing in text as "crnoj"). Use this to
    see what data was drawn on, not as a hard compliance gate - the numeric
    check above is the one with a 0%-tolerance bar.
    """
    lowered_text = text.lower()
    return frozenset(
        key for key, value in attributes.items() if str(value).lower() not in lowered_text
    )


def check_claims(text: str, attributes: dict[str, object]) -> ClaimsReport:
    unsupported = find_unsupported_numeric_claims(text, attributes)
    unreferenced = find_unreferenced_attributes(text, attributes)
    referenced = frozenset(attributes.keys()) - unreferenced
    return ClaimsReport(
        unsupported=unsupported,
        referenced_attributes=referenced,
        unreferenced_attributes=unreferenced,
    )
