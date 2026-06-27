"""Detect tokens that must pass through transliteration unchanged.

Hard rule (see doc/CLAUDE.md): brand names, model numbers, and SKUs must
have 0% transliteration error. "iPhone" must never become "ајПхоне". The
only reliable way to guarantee that is to never run the mapping table over
them at all - detect them and copy them verbatim into both script outputs.

Heuristics below are deliberately narrow and only fire on signals that are
near-certain markers of a foreign/brand/code token in running Serbian text.
A blanket "all-caps = protected" rule is intentionally NOT included: it
would falsely protect legitimate Serbian acronyms (e.g. "PDV") that should
transliterate normally. Callers should supply a `glossary` of the product's
own brand/model/SKU attribute values - that is the highest-confidence
signal and ties protection directly to the structured input data, matching
the claims-grounding principle (core/claims).
"""

from __future__ import annotations

import re

# Letters that do not exist in the Serbian Latin alphabet (gajica). Any word
# containing one is virtually guaranteed to be foreign (a brand/product
# name), not a Serbian word that happens to need transliteration.
_FOREIGN_LETTERS = frozenset("qwxyQWXY")

# Internal capital following a lowercase letter: "iPhone", "PlayStation",
# "YouTube". Genuine Serbian words are never written this way.
_CAMEL_CASE_RE = re.compile(r"[a-zšđčćž][A-ZŠĐČĆŽ]")


def is_protected_word(word: str, glossary: frozenset[str] = frozenset()) -> bool:
    """True if `word` should be copied verbatim, never transliterated.

    `glossary` should be populated from the product's own structured
    attributes (brand, model, SKU) at call time, not hardcoded here.
    """
    if not word:
        return False
    if word in glossary:
        return True
    lowered = word.lower()
    if lowered in {g.lower() for g in glossary}:
        return True
    if any(ch in _FOREIGN_LETTERS for ch in word):
        return True
    if _CAMEL_CASE_RE.search(word):
        return True
    has_digit = any(ch.isdigit() for ch in word)
    has_letter = any(ch.isalpha() for ch in word)
    if has_digit and has_letter:
        return True
    return False
