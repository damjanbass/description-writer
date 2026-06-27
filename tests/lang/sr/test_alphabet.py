from lang.sr.alphabet import (
    DIGRAPH_CYR_TO_LAT,
    DIGRAPH_LAT_TO_CYR,
    DIGRAPH_PAIRS,
    SIMPLE_CYR_TO_LAT,
    SIMPLE_LAT_TO_CYR,
    SIMPLE_PAIRS,
)


def test_alphabet_has_30_letters():
    assert len(SIMPLE_PAIRS) + len(DIGRAPH_PAIRS) == 30


def test_simple_pairs_are_unique():
    cyr_letters = [pair[0] for pair in SIMPLE_PAIRS]
    lat_letters = [pair[1] for pair in SIMPLE_PAIRS]
    assert len(cyr_letters) == len(set(cyr_letters))
    assert len(lat_letters) == len(set(lat_letters))


def test_simple_maps_are_case_complete():
    # Every simple pair must have both lower and upper entries in both maps.
    for cyr, lat in SIMPLE_PAIRS:
        assert SIMPLE_CYR_TO_LAT[cyr] == lat
        assert SIMPLE_CYR_TO_LAT[cyr.upper()] == lat.upper()
        assert SIMPLE_LAT_TO_CYR[lat] == cyr
        assert SIMPLE_LAT_TO_CYR[lat.upper()] == cyr.upper()


def test_simple_maps_are_mutual_inverses():
    for cyr, lat in SIMPLE_CYR_TO_LAT.items():
        assert SIMPLE_LAT_TO_CYR[lat] == cyr


def test_digraph_maps_are_mutual_inverses():
    for cyr, lat in DIGRAPH_CYR_TO_LAT.items():
        assert DIGRAPH_LAT_TO_CYR[lat] == cyr


def test_digraph_latin_forms_are_two_chars():
    for lat in DIGRAPH_LAT_TO_CYR:
        assert len(lat) == 2


def test_cyrillic_letters_have_python_case_support():
    # The engine relies on str.upper()/str.lower() handling Serbian
    # Cyrillic correctly - verify that assumption explicitly rather than
    # relying on it implicitly through engine tests only.
    for cyr, _ in DIGRAPH_PAIRS:
        assert cyr.upper().lower() == cyr
        assert cyr != cyr.upper()
