"""Words where Latin nj/lj/dž must NOT merge into a single Cyrillic letter.

In most Serbian words, "nj"/"lj"/"dž" represent one sound (њ/љ/џ). But when
a prefix ending in n/d (or, rarely, l) attaches to a root starting with
j/ž, the two letters stay phonetically and orthographically separate, e.g.
"in-jekcija" (prefix in- + jekcija), not a single nj-sound. Naive merging
produces a real Pravopis error ("ињекција" instead of "инјекција").

This is a SEED list of well-established cases, not an exhaustive dictionary.
Phase 0's kill criterion (<3% agreement error, 0% protected-term error on
200 copy-edited products) is the mechanism for catching gaps: any missed
exception surfaces as a transliteration error during copy-editor review and
should be added here. Matching is case-insensitive; store lowercase only.
"""

from __future__ import annotations

NJ_DZ_BOUNDARY_EXCEPTIONS: frozenset[str] = frozenset({
    # in- + j-initial root ("nj" stays n+j)
    "injekcija", "injekcije", "injekciju", "injekcijom", "injekcijama", "injekcijski",
    "injektor", "injektora", "injektoru",
    # kon- + j-initial root ("nj" stays n+j)
    "konjunktiv", "konjunktiva", "konjunktivu", "konjunktivom",
    "konjunkcija", "konjunkcije", "konjunkciju",
    "konjugacija", "konjugacije", "konjugaciju", "konjugacijom",
    "konjugovati", "konjugovan", "konjugovana", "konjugovano",
    # van- + j-initial root ("nj" stays n+j)
    "vanjezički", "vanjezička", "vanjezičko", "vanjezičke", "vanjezičkog",
    # nad- + ž-initial root ("dž" stays d+ž)
    "nadživeti", "nadživela", "nadživeo", "nadživljavati", "nadživljava",
    "nadžupan", "nadžupana", "nadžupanu",
    # pod- + ž-initial root ("dž" stays d+ž)
    "podžupan", "podžupana",
    # od- + ž-initial root ("dž" stays d+ž)
    "odžaliti", "odžalio", "odžalila",
})

# Real lj-boundary exceptions are rare in Serbian: most prefix+lj sequences
# still palatalize into the single lj-sound, so there is no seed entry yet.
# Leave this as an explicit, separate set so it is obvious where to add one
# if copy-editor review (the Phase 0 kill criterion) surfaces a real case.
LJ_BOUNDARY_EXCEPTIONS: frozenset[str] = frozenset()

DIGRAPH_EXCEPTIONS: frozenset[str] = NJ_DZ_BOUNDARY_EXCEPTIONS | LJ_BOUNDARY_EXCEPTIONS


def is_digraph_exception(word: str) -> bool:
    """True if `word` (any case) must be transliterated letter-by-letter,
    never merging nj/lj/dž into a single Cyrillic letter."""
    return word.lower() in DIGRAPH_EXCEPTIONS
