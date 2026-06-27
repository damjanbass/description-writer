import pytest

from core.agreement.engine import LOW_CONFIDENCE_THRESHOLD
from core.agreement.types import Gender, Number
from lang.sr.agreement import adjective_ending, infer_noun_profile


class TestInferNounProfile:
    def test_consonant_ending_is_masculine_singular(self):
        profile = infer_noun_profile("kaiš")
        assert profile.gender == Gender.MASCULINE
        assert profile.number == Number.SINGULAR
        assert profile.confidence >= LOW_CONFIDENCE_THRESHOLD

    def test_a_ending_is_feminine_singular(self):
        profile = infer_noun_profile("majica")
        assert profile.gender == Gender.FEMININE
        assert profile.number == Number.SINGULAR
        assert profile.confidence >= LOW_CONFIDENCE_THRESHOLD

    def test_o_ending_is_neuter_singular(self):
        profile = infer_noun_profile("vino")
        assert profile.gender == Gender.NEUTER
        assert profile.number == Number.SINGULAR
        assert profile.confidence >= LOW_CONFIDENCE_THRESHOLD

    def test_i_ending_is_masculine_plural(self):
        profile = infer_noun_profile("telefoni")
        assert profile.gender == Gender.MASCULINE
        assert profile.number == Number.PLURAL
        assert profile.confidence >= LOW_CONFIDENCE_THRESHOLD

    def test_e_ending_is_low_confidence(self):
        # Genuinely ambiguous (neuter sg vs feminine pl) - must stay below
        # the engine's review threshold regardless of which guess it makes.
        profile = infer_noun_profile("pakovanje")
        assert profile.confidence < LOW_CONFIDENCE_THRESHOLD

    def test_masculine_a_exception(self):
        profile = infer_noun_profile("tata")
        assert profile.gender == Gender.MASCULINE
        assert profile.number == Number.SINGULAR

    def test_empty_string_returns_none(self):
        assert infer_noun_profile("") is None

    def test_case_insensitive(self):
        profile = infer_noun_profile("KAIŠ")
        assert profile.gender == Gender.MASCULINE


class TestAdjectiveEnding:
    @pytest.mark.parametrize(
        ("word", "ending"),
        [("crni", "i"), ("crna", "a"), ("crno", "o"), ("crne", "e")],
    )
    def test_recognized_vowel_endings(self, word, ending):
        assert adjective_ending(word) == ending

    def test_short_form_has_no_ending(self):
        assert adjective_ending("lep") is None

    def test_empty_string_returns_none(self):
        assert adjective_ending("") is None
