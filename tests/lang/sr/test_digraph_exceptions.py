import pytest

from lang.sr.digraph_exceptions import is_digraph_exception


@pytest.mark.parametrize(
    "word",
    ["injekcija", "Injekcija", "INJEKCIJA", "konjunktiv", "konjugacija", "nadživeti", "nadžupan"],
)
def test_known_exceptions_are_flagged(word):
    assert is_digraph_exception(word) is True


@pytest.mark.parametrize("word", ["konjak", "konj", "ljubav", "džep", "Njegoš"])
def test_normal_digraph_words_are_not_flagged(word):
    assert is_digraph_exception(word) is False
