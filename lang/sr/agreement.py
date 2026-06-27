"""Serbian adjective<->noun gender/number agreement data (nominative case).

Heuristics are ending-pattern based, not a noun lexicon, so they cover the
regular/dominant pattern with explicit confidence scores rather than a
hardcoded list of every Serbian noun. Low confidence forces a "needs
review" outcome in core/agreement/engine.py rather than a possibly-wrong
verdict - deliberate, because a few Serbian nouns break the pattern (e.g.
masculine nouns ending in -a that refer to people: "tata", "sudija"), and
-e endings are genuinely ambiguous (neuter singular "more" vs feminine
plural "majice") with no way to disambiguate from the ending alone.
"""

from __future__ import annotations

from core.agreement.types import AgreementPack, Gender, NounProfile, Number

# Masculine nouns ending in -a are real but rare among PRODUCT nouns
# specifically (mostly people nouns). Guard against misclassifying them.
_MASCULINE_A_EXCEPTIONS = frozenset({
    "tata", "sudija", "kolega", "komšija", "vladika", "paša",
})

_ADJECTIVE_VOWEL_ENDINGS = frozenset("aeio")

_EXPECTED_ENDINGS: dict[tuple[Gender, Number], frozenset[str]] = {
    (Gender.MASCULINE, Number.SINGULAR): frozenset({"i"}),
    (Gender.MASCULINE, Number.PLURAL): frozenset({"i"}),
    (Gender.FEMININE, Number.SINGULAR): frozenset({"a"}),
    (Gender.FEMININE, Number.PLURAL): frozenset({"e"}),
    (Gender.NEUTER, Number.SINGULAR): frozenset({"o", "e"}),
    (Gender.NEUTER, Number.PLURAL): frozenset({"a"}),
}


def infer_noun_profile(noun: str) -> NounProfile | None:
    if not noun:
        return None
    lowered = noun.lower()
    last = lowered[-1]

    if last == "a":
        if lowered in _MASCULINE_A_EXCEPTIONS:
            return NounProfile(Gender.MASCULINE, Number.SINGULAR, confidence=0.8)
        return NounProfile(Gender.FEMININE, Number.SINGULAR, confidence=0.9)
    if last == "o":
        return NounProfile(Gender.NEUTER, Number.SINGULAR, confidence=0.85)
    if last == "e":
        # Genuinely ambiguous: neuter sg ("more") vs feminine pl ("majice").
        # Confidence is deliberately below the engine's review threshold so
        # this never asserts a verdict on its own either way.
        return NounProfile(Gender.FEMININE, Number.PLURAL, confidence=0.4)
    if last == "i":
        return NounProfile(Gender.MASCULINE, Number.PLURAL, confidence=0.75)
    # Consonant ending: dominant pattern for masculine singular nouns.
    return NounProfile(Gender.MASCULINE, Number.SINGULAR, confidence=0.85)


def adjective_ending(word: str) -> str | None:
    if not word:
        return None
    last = word[-1].lower()
    if last in _ADJECTIVE_VOWEL_ENDINGS:
        return last
    return None  # short/indefinite form (e.g. "lep") - not verifiable here


def expected_endings(gender: Gender, number: Number) -> frozenset[str]:
    return _EXPECTED_ENDINGS[(gender, number)]


SR_AGREEMENT_PACK = AgreementPack(
    name="sr",
    infer_noun_profile=infer_noun_profile,
    adjective_ending=adjective_ending,
    expected_endings=expected_endings,
)
