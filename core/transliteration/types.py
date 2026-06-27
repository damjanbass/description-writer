"""Language-agnostic contract for a transliteration pack.

Nothing in this module knows about Serbian specifically. A language pack
(see lang/sr/__init__.py for the Serbian one) supplies the data; the engine
(core/transliteration/engine.py) supplies the algorithm. This split is what
satisfies the hard rule that agreement/transliteration logic must be
pluggable per-language from day one (sr -> hr/bs/me/mk later) without
rewriting the core.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class Direction(Enum):
    SCRIPT_A_TO_B = "a_to_b"
    SCRIPT_B_TO_A = "b_to_a"


@dataclass(frozen=True)
class TransliterationPack:
    """Everything the engine needs to transliterate one language pair.

    For Serbian, script A is Cyrillic and script B is Latin. Script A is
    expected to be the side with single-character letters only (no
    digraphs) and therefore the lossless, exception-free direction;
    script B is expected to carry the digraphs and the exception list.
    The engine does not assume which is "Cyrillic" or "Latin" by name.
    """

    name: str

    # Single-character letters, fully case-expanded: e.g. {"а": "a", "А": "A"}.
    simple_a_to_b: dict[str, str]
    simple_b_to_a: dict[str, str]

    # Letters that are one character in script A but multiple in script B,
    # e.g. {"љ": "lj"}. Keys/values are lowercase canonical forms; the
    # engine derives case variants using word-level context.
    digraph_a_to_b: dict[str, str]
    digraph_b_to_a: dict[str, str]

    # Lowercased script-B words where a digraph sequence must NOT merge
    # into a single script-A letter (morpheme-boundary exceptions).
    is_digraph_exception: Callable[[str], bool]

    # True if a script-B word must be copied verbatim, never transliterated
    # (brand names, model numbers, SKUs). Takes an optional glossary set.
    is_protected_word: Callable[[str, frozenset[str]], bool] = field(
        default=lambda word, glossary: False
    )
