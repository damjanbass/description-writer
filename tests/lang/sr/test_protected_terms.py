import pytest

from lang.sr.protected_terms import is_protected_word


@pytest.mark.parametrize(
    "word",
    ["iPhone", "PlayStation", "YouTube", "iPad", "eBay"],
)
def test_camelcase_brand_names_are_protected(word):
    assert is_protected_word(word) is True


@pytest.mark.parametrize("word", ["Wi-Fi", "Xbox", "Yves", "Qatar", "Wow"])
def test_foreign_letters_are_protected(word):
    assert is_protected_word(word) is True


@pytest.mark.parametrize("word", ["SM-G991B", "RTX4090", "XPS13", "iPhone15"])
def test_alphanumeric_codes_are_protected(word):
    assert is_protected_word(word) is True


@pytest.mark.parametrize(
    "word",
    ["Kupite", "odmah", "proizvod", "kožna", "Pro", "Samsung", "Najk"],
)
def test_plain_words_are_not_protected_by_default(word):
    assert is_protected_word(word) is False


def test_glossary_protects_exact_match():
    assert is_protected_word("Pro", glossary=frozenset({"Pro"})) is True


def test_glossary_match_is_case_insensitive():
    assert is_protected_word("pro", glossary=frozenset({"Pro"})) is True


def test_empty_word_is_not_protected():
    assert is_protected_word("") is False
