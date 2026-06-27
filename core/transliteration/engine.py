"""Generic transliteration engine. No Serbian (or any language) literals here.

Algorithm:
- Script A is assumed single-character-per-letter only (no digraphs), so
  A -> B is always a direct, per-character, exception-free mapping.
- Script B may have digraphs (two B-characters representing one A-letter).
  B -> A scans left to right with a 2-character lookahead, consulting
  `pack.is_digraph_exception` to decide whether a digraph sequence is one
  A-letter or two separate ones.
- In both directions, whole word chunks that `pack.is_protected_word`
  flags are copied verbatim and never touch any mapping table.
"""

from __future__ import annotations

import re

from core.transliteration.types import Direction, TransliterationPack

_WORD_CHUNK_RE = re.compile(r"[\w-]+", re.UNICODE)


def transliterate(
    text: str,
    pack: TransliterationPack,
    direction: Direction,
    glossary: frozenset[str] = frozenset(),
) -> str:
    """Transliterate `text` per `pack` in the given `direction`.

    `glossary` should be the calling product's own brand/model/SKU
    attribute values - the highest-confidence protected-term signal,
    since it ties protection directly to structured input data.
    """

    def replace(match: re.Match[str]) -> str:
        chunk = match.group(0)
        if pack.is_protected_word(chunk, glossary):
            return chunk
        if direction is Direction.SCRIPT_A_TO_B:
            return _a_to_b_word(chunk, pack)
        return _b_to_a_word(chunk, pack)

    return _WORD_CHUNK_RE.sub(replace, text)


def _a_to_b_word(word: str, pack: TransliterationPack) -> str:
    word_all_upper = word.isupper()
    out: list[str] = []
    for ch in word:
        lower_ch = ch.lower()
        base = pack.digraph_a_to_b.get(lower_ch)
        if base is not None:
            if ch.isupper():
                out.append(base.upper() if word_all_upper else base[0].upper() + base[1:])
            else:
                out.append(base)
        else:
            out.append(pack.simple_a_to_b.get(ch, ch))
    return "".join(out)


def _b_to_a_word(word: str, pack: TransliterationPack) -> str:
    if pack.is_digraph_exception(word):
        return "".join(pack.simple_b_to_a.get(ch, ch) for ch in word)

    result: list[str] = []
    i = 0
    n = len(word)
    while i < n:
        two = word[i : i + 2]
        digraph_base = pack.digraph_b_to_a.get(two.lower())
        if digraph_base is not None and len(two) == 2:
            result.append(digraph_base.upper() if two[0].isupper() else digraph_base.lower())
            i += 2
            continue
        ch = word[i]
        result.append(pack.simple_b_to_a.get(ch, ch))
        i += 1
    return "".join(result)
