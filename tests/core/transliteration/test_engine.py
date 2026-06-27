"""Tests for the transliteration engine, using the Serbian pack as the
concrete language under test.

These tests directly encode the Phase 0 hard rules from doc/CLAUDE.md:
- protected terms (brand/model/SKU) must survive with 0% error
- the engine must not need Serbian-specific code to do this (it only ever
  calls pack.* hooks), which these tests implicitly verify by importing
  the engine and the pack from separate, independent modules.
"""

from __future__ import annotations

import pytest

from core.transliteration import Direction, transliterate
from lang.sr import SR_PACK

CYR_TO_LAT = Direction.SCRIPT_A_TO_B
LAT_TO_CYR = Direction.SCRIPT_B_TO_A


class TestBasicSentences:
    def test_cyr_to_lat_simple_sentence(self):
        result = transliterate("Ово је кратак опис производа.", SR_PACK, CYR_TO_LAT)
        assert result == "Ovo je kratak opis proizvoda."

    def test_lat_to_cyr_simple_sentence(self):
        result = transliterate("Ovo je kratak opis proizvoda.", SR_PACK, LAT_TO_CYR)
        assert result == "Ово је кратак опис производа."

    def test_empty_string(self):
        assert transliterate("", SR_PACK, CYR_TO_LAT) == ""
        assert transliterate("", SR_PACK, LAT_TO_CYR) == ""

    def test_punctuation_and_whitespace_preserved(self):
        text = "Цена: 1.999,00 RSD - бесплатна достава!"
        result = transliterate(text, SR_PACK, CYR_TO_LAT)
        assert result == "Cena: 1.999,00 RSD - besplatna dostava!"


class TestDigraphCasing:
    """nj/lj/dž must round-trip through all three casing patterns."""

    def test_cyr_to_lat_digraph_lowercase(self):
        assert transliterate("коњ", SR_PACK, CYR_TO_LAT) == "konj"
        assert transliterate("љубав", SR_PACK, CYR_TO_LAT) == "ljubav"
        assert transliterate("џеп", SR_PACK, CYR_TO_LAT) == "džep"

    def test_cyr_to_lat_digraph_titlecase(self):
        # Njegoš: real surname, canonical test case for title-case digraphs.
        assert transliterate("Његош", SR_PACK, CYR_TO_LAT) == "Njegoš"

    def test_cyr_to_lat_digraph_allcaps(self):
        assert transliterate("ЊЕГОШ", SR_PACK, CYR_TO_LAT) == "NJEGOŠ"
        assert transliterate("ЏЕП", SR_PACK, CYR_TO_LAT) == "DŽEP"
        assert transliterate("ЉУБАВ", SR_PACK, CYR_TO_LAT) == "LJUBAV"

    def test_cyr_to_lat_digraph_all_three_casings_per_letter(self):
        # њ/nj, љ/lj, џ/dž each exercised in lower/title/allcaps form.
        assert transliterate("коњ", SR_PACK, CYR_TO_LAT) == "konj"
        assert transliterate("Његош", SR_PACK, CYR_TO_LAT) == "Njegoš"
        assert transliterate("ЊЕГОШ", SR_PACK, CYR_TO_LAT) == "NJEGOŠ"

        assert transliterate("љубав", SR_PACK, CYR_TO_LAT) == "ljubav"
        assert transliterate("Љубав", SR_PACK, CYR_TO_LAT) == "Ljubav"
        assert transliterate("ЉУБАВ", SR_PACK, CYR_TO_LAT) == "LJUBAV"

        assert transliterate("џеп", SR_PACK, CYR_TO_LAT) == "džep"
        assert transliterate("Џеп", SR_PACK, CYR_TO_LAT) == "Džep"
        assert transliterate("ЏЕП", SR_PACK, CYR_TO_LAT) == "DŽEP"

    def test_lat_to_cyr_digraph_default_merge(self):
        # "konj" (horse) is not a boundary exception -> nj merges to њ.
        assert transliterate("konj", SR_PACK, LAT_TO_CYR) == "коњ"
        assert transliterate("ljubav", SR_PACK, LAT_TO_CYR) == "љубав"
        assert transliterate("džep", SR_PACK, LAT_TO_CYR) == "џеп"

    def test_lat_to_cyr_digraph_all_three_casings_per_letter(self):
        assert transliterate("konj", SR_PACK, LAT_TO_CYR) == "коњ"
        assert transliterate("Njegoš", SR_PACK, LAT_TO_CYR) == "Његош"
        assert transliterate("NJEGOŠ", SR_PACK, LAT_TO_CYR) == "ЊЕГОШ"

        assert transliterate("ljubav", SR_PACK, LAT_TO_CYR) == "љубав"
        assert transliterate("Ljubav", SR_PACK, LAT_TO_CYR) == "Љубав"
        assert transliterate("LJUBAV", SR_PACK, LAT_TO_CYR) == "ЉУБАВ"

        assert transliterate("džep", SR_PACK, LAT_TO_CYR) == "џеп"
        assert transliterate("Džep", SR_PACK, LAT_TO_CYR) == "Џеп"
        assert transliterate("DŽEP", SR_PACK, LAT_TO_CYR) == "ЏЕП"


class TestDigraphExceptions:
    """Morpheme-boundary words where nj/dž must NOT merge (see
    lang/sr/digraph_exceptions.py). These are real Pravopis examples."""

    @pytest.mark.parametrize(
        ("latin", "cyrillic"),
        [
            ("injekcija", "инјекција"),
            ("konjunktiv", "конјунктив"),
            ("konjugacija", "конјугација"),
            ("nadživeti", "надживети"),
            ("nadžupan", "наджупан"),
        ],
    )
    def test_lat_to_cyr_exception_words_do_not_merge(self, latin, cyrillic):
        assert transliterate(latin, SR_PACK, LAT_TO_CYR) == cyrillic

    def test_exception_is_contrasted_by_normal_word(self):
        # "konjak" (cognac) looks similar to "konjugacija" but is NOT an
        # exception - nj legitimately merges to њ here.
        assert transliterate("konjak", SR_PACK, LAT_TO_CYR) == "коњак"

    def test_exception_matching_is_case_insensitive(self):
        assert transliterate("Injekcija", SR_PACK, LAT_TO_CYR) == "Инјекција"
        assert transliterate("INJEKCIJA", SR_PACK, LAT_TO_CYR) == "ИНЈЕКЦИЈА"


class TestProtectedTerms:
    """Hard rule: brand names, model numbers, SKUs = 0% transliteration
    error. They must come out byte-for-byte identical in both directions."""

    def test_iphone_hard_rule(self):
        # The literal example from doc/CLAUDE.md.
        result = transliterate("iPhone", SR_PACK, LAT_TO_CYR)
        assert result == "iPhone"
        assert result != "ајПхоне"

    def test_camelcase_brand_in_sentence_lat_to_cyr(self):
        result = transliterate("Kupite iPhone odmah.", SR_PACK, LAT_TO_CYR)
        assert result == "Купите iPhone одмах."

    def test_camelcase_brand_in_sentence_cyr_to_lat(self):
        # A Latin-script brand name embedded in Cyrillic text already
        # passes through unchanged (it has no Cyrillic keys to match) -
        # this confirms protection holds even without the heuristic firing.
        result = transliterate("Купите iPhone одмах.", SR_PACK, CYR_TO_LAT)
        assert result == "Kupite iPhone odmah."

    def test_foreign_letter_heuristic(self):
        # q/w/x/y do not exist in Serbian latinica.
        for word in ("Wi-Fi", "Xbox", "Yves"):
            assert transliterate(word, SR_PACK, LAT_TO_CYR) == word

    def test_sku_alnum_heuristic(self):
        for sku in ("SM-G991B", "RTX4090", "XPS13"):
            assert transliterate(sku, SR_PACK, LAT_TO_CYR) == sku

    def test_protected_term_with_adjacent_punctuation(self):
        # Punctuation directly touching a protected term must not leak
        # into the match or break protection.
        result = transliterate("Novi (iPhone), odmah.", SR_PACK, LAT_TO_CYR)
        assert result == "Нови (iPhone), одмах."

    def test_glossary_protects_plain_word_token(self):
        text = "Kupite iPhone 15 Pro odmah."
        without_glossary = transliterate(text, SR_PACK, LAT_TO_CYR)
        assert without_glossary == "Купите iPhone 15 Про одмах."

        with_glossary = transliterate(
            text, SR_PACK, LAT_TO_CYR, glossary=frozenset({"Pro"})
        )
        assert with_glossary == "Купите iPhone 15 Pro одмах."


class TestRoundTrip:
    """Self-consistency: for text with no exception words and no protected
    terms, converting there and back must reproduce the original exactly.
    This is the property-level confidence check behind the 0%-error gate -
    it does not depend on any single hand-computed expected string."""

    SAFE_LATIN_SENTENCES = [
        "Ovo je ljubičasta kožna jakna sa džepovima i postavom.",
        "Konj i konjak nisu ista reč.",
        "Njegoš je veliki pesnik.",
        "NOVO: SVI PROIZVODI NA AKCIJI.",
        "Veličina, boja i materijal su prikazani u tabeli ispod.",
    ]

    @pytest.mark.parametrize("latin", SAFE_LATIN_SENTENCES)
    def test_lat_cyr_lat_round_trip(self, latin):
        cyr = transliterate(latin, SR_PACK, LAT_TO_CYR)
        back = transliterate(cyr, SR_PACK, CYR_TO_LAT)
        assert back == latin

    @pytest.mark.parametrize("latin", SAFE_LATIN_SENTENCES)
    def test_cyr_lat_cyr_round_trip(self, latin):
        # Start from the Cyrillic form of the same sentence.
        cyr = transliterate(latin, SR_PACK, LAT_TO_CYR)
        lat = transliterate(cyr, SR_PACK, CYR_TO_LAT)
        back = transliterate(lat, SR_PACK, LAT_TO_CYR)
        assert back == cyr
