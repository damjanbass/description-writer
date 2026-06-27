from core.agreement.types import CountClass
from lang.sr.counting import expected_noun_form


class TestExpectedNounForm:
    def test_proizvod_all_three_classes(self):
        assert expected_noun_form("proizvod", CountClass.ONE) == "proizvod"
        assert expected_noun_form("proizvod", CountClass.FEW) == "proizvoda"
        assert expected_noun_form("proizvod", CountClass.MANY) == "proizvoda"

    def test_artikal_mobile_vowel_pattern(self):
        assert expected_noun_form("artikal", CountClass.ONE) == "artikal"
        assert expected_noun_form("artikal", CountClass.FEW) == "artikla"
        assert expected_noun_form("artikal", CountClass.MANY) == "artikala"

    def test_par_ova_insertion_pattern(self):
        assert expected_noun_form("par", CountClass.ONE) == "par"
        assert expected_noun_form("par", CountClass.FEW) == "para"
        assert expected_noun_form("par", CountClass.MANY) == "parova"

    def test_majica_feminine_pattern(self):
        assert expected_noun_form("majica", CountClass.ONE) == "majica"
        assert expected_noun_form("majica", CountClass.FEW) == "majice"
        assert expected_noun_form("majica", CountClass.MANY) == "majica"

    def test_case_insensitive_lookup(self):
        assert expected_noun_form("PROIZVOD", CountClass.ONE) == "proizvod"

    def test_unknown_noun_returns_none(self):
        assert expected_noun_form("nepostojecaimenica", CountClass.ONE) is None
