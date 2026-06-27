"""Serbian Cyrillic <-> Latin letter table.

Serbian is digraphic: every text has a 1:1 letter-level mapping between
ćirilica and latinica (unlike e.g. Russian->English transliteration, which
is lossy). The 30-letter Cyrillic alphabet pairs exactly with the 30 letter
*units* of the Latin alphabet, where three units (lj, nj, dž) are written
with two Latin characters but count as a single Cyrillic letter (љ, њ, џ).

CYR_TO_LAT is always lossless and exception-free: each Cyrillic letter maps
to exactly one Latin form, so this direction needs no judgment calls.
LAT_TO_CYR is the hard direction: "nj"/"lj"/"dž" are ambiguous whenever they
straddle a morpheme boundary instead of representing the single digraph
sound (see digraph_exceptions.py). That asymmetry is why the engine should
prefer generating ćirilica as the source script when it has a choice.
"""

from __future__ import annotations

# The 27 letters with a single-character form in both scripts.
# (cyrillic, latin) lowercase base pairs - everything else is derived.
SIMPLE_PAIRS: tuple[tuple[str, str], ...] = (
    ("а", "a"), ("б", "b"), ("в", "v"), ("г", "g"), ("д", "d"),
    ("ђ", "đ"), ("е", "e"), ("ж", "ž"), ("з", "z"), ("и", "i"),
    ("ј", "j"), ("к", "k"), ("л", "l"), ("м", "m"), ("н", "n"),
    ("о", "o"), ("п", "p"), ("р", "r"), ("с", "s"), ("т", "t"),
    ("ћ", "ć"), ("у", "u"), ("ф", "f"), ("х", "h"), ("ц", "c"),
    ("ч", "č"), ("ш", "š"),
)

# The 3 letters that are a single Cyrillic character but two Latin
# characters. Latin form given lowercase; case is derived at use time.
DIGRAPH_PAIRS: tuple[tuple[str, str], ...] = (
    ("љ", "lj"),
    ("њ", "nj"),
    ("џ", "dž"),
)

assert len(SIMPLE_PAIRS) + len(DIGRAPH_PAIRS) == 30, "Serbian alphabet has 30 letters"


def _build_simple_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Build flat case-expanded lookup tables for the 27 simple pairs.

    Every lower AND upper variant is a separate explicit key so lookups
    never need runtime case juggling.
    """
    cyr_to_lat: dict[str, str] = {}
    lat_to_cyr: dict[str, str] = {}
    for cyr, lat in SIMPLE_PAIRS:
        cyr_to_lat[cyr] = lat
        cyr_to_lat[cyr.upper()] = lat.upper()
        lat_to_cyr[lat] = cyr
        lat_to_cyr[lat.upper()] = cyr.upper()
    return cyr_to_lat, lat_to_cyr


SIMPLE_CYR_TO_LAT, SIMPLE_LAT_TO_CYR = _build_simple_maps()

# Digraph lookups keyed by lowercase Cyrillic letter / lowercase Latin
# digraph. Case is resolved by the engine using word-level context, since
# Cyrillic only has 2 case forms per letter but Latin digraphs need 3
# (lj / Lj / LJ) depending on whether the whole word is capitalized.
DIGRAPH_CYR_TO_LAT: dict[str, str] = {cyr: lat for cyr, lat in DIGRAPH_PAIRS}
DIGRAPH_LAT_TO_CYR: dict[str, str] = {lat: cyr for cyr, lat in DIGRAPH_PAIRS}

ALL_CYRILLIC_LETTERS: frozenset[str] = frozenset(
    SIMPLE_CYR_TO_LAT.keys()
) | frozenset(DIGRAPH_CYR_TO_LAT.keys()) | frozenset(c.upper() for c in DIGRAPH_CYR_TO_LAT)
