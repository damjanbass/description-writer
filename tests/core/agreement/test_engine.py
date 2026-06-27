import pytest

from core.agreement.engine import check_adjective_noun_agreement, classify_count
from core.agreement.types import CountClass
from lang.sr.agreement import SR_AGREEMENT_PACK


class TestClassifyCount:
    @pytest.mark.parametrize("n", [1, 21, 31, 101])
    def test_one(self, n):
        assert classify_count(n) == CountClass.ONE

    @pytest.mark.parametrize("n", [2, 3, 4, 22, 23, 24, 32])
    def test_few(self, n):
        assert classify_count(n) == CountClass.FEW

    @pytest.mark.parametrize("n", [0, 5, 6, 10, 11, 12, 13, 14, 15, 20, 25, 100, 111])
    def test_many(self, n):
        assert classify_count(n) == CountClass.MANY


class TestAdjectiveNounAgreement:
    def test_feminine_singular_correct(self):
        assert check_adjective_noun_agreement("crna", "majica", SR_AGREEMENT_PACK) is None

    def test_feminine_singular_mismatch(self):
        issue = check_adjective_noun_agreement("crni", "majica", SR_AGREEMENT_PACK)
        assert issue is not None
        assert issue.actual_ending == "i"
        assert issue.expected_endings == frozenset({"a"})

    def test_masculine_singular_correct(self):
        assert check_adjective_noun_agreement("crni", "kaiš", SR_AGREEMENT_PACK) is None

    def test_masculine_singular_mismatch(self):
        issue = check_adjective_noun_agreement("crna", "kaiš", SR_AGREEMENT_PACK)
        assert issue is not None
        assert issue.actual_ending == "a"
        assert issue.expected_endings == frozenset({"i"})

    def test_neuter_singular_correct(self):
        # "vino" is unambiguously neuter singular from its -o ending.
        assert check_adjective_noun_agreement("crveno", "vino", SR_AGREEMENT_PACK) is None

    def test_neuter_singular_mismatch(self):
        issue = check_adjective_noun_agreement("crvena", "vino", SR_AGREEMENT_PACK)
        assert issue is not None
        assert issue.expected_endings == frozenset({"o", "e"})

    def test_ambiguous_e_ending_noun_abstains(self):
        # "pakovanje" is neuter, but the heuristic can't tell that from the
        # ending alone (vs. feminine plural) - it must abstain, not guess.
        assert check_adjective_noun_agreement("crveno", "pakovanje", SR_AGREEMENT_PACK) is None
        assert check_adjective_noun_agreement("crvena", "pakovanje", SR_AGREEMENT_PACK) is None

    def test_short_form_adjective_flagged_not_silently_passed(self):
        issue = check_adjective_noun_agreement("lep", "kaiš", SR_AGREEMENT_PACK)
        assert issue is not None
        assert issue.actual_ending is None

    def test_masculine_a_exception_noun(self):
        # "tata" ends in -a but is masculine - must not be treated as fem.
        assert check_adjective_noun_agreement("dobar", "tata", SR_AGREEMENT_PACK) is not None
        # Confirms it resolved to masculine (expects "i"), not feminine ("a"):
        issue = check_adjective_noun_agreement("dobra", "tata", SR_AGREEMENT_PACK)
        assert issue is not None
        assert issue.expected_endings == frozenset({"i"})
