"""Serbian language pack: plugs Serbian-specific data into core.transliteration.

Script A = ćirilica (Cyrillic), script B = latinica (Latin). This is the
only file that should ever be imported by pipeline/connector code that
needs "the Serbian rules" - it is the seam where hr/bs/me/mk packs would
be added later, each in their own lang/<code>/ package.
"""

from __future__ import annotations

from core.transliteration.types import TransliterationPack
from lang.sr.alphabet import (
    DIGRAPH_CYR_TO_LAT,
    DIGRAPH_LAT_TO_CYR,
    SIMPLE_CYR_TO_LAT,
    SIMPLE_LAT_TO_CYR,
)
from lang.sr.digraph_exceptions import is_digraph_exception
from lang.sr.protected_terms import is_protected_word

SR_PACK = TransliterationPack(
    name="sr",
    simple_a_to_b=SIMPLE_CYR_TO_LAT,
    simple_b_to_a=SIMPLE_LAT_TO_CYR,
    digraph_a_to_b=DIGRAPH_CYR_TO_LAT,
    digraph_b_to_a=DIGRAPH_LAT_TO_CYR,
    is_digraph_exception=is_digraph_exception,
    is_protected_word=is_protected_word,
)

__all__ = ["SR_PACK"]
