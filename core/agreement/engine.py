"""Generic agreement-checking algorithm. No Serbian literals here.

classify_count() is pure arithmetic on the numeral and needs no language
pack - the 1 / 2-4 / 5+ (with an 11-14 exception) pattern is shared across
Slavic languages this engine will eventually support (sr -> hr/bs/me/mk).
"""

from __future__ import annotations

from core.agreement.types import AgreementIssue, AgreementPack, CountClass

# Confidence below this means "don't assert pass/fail" - the noun's gender
# could not be reliably inferred from its ending alone (e.g. nouns ending
# in -e are genuinely ambiguous between neuter singular and feminine
# plural). Surface as a review flag instead of a possibly-wrong verdict.
LOW_CONFIDENCE_THRESHOLD = 0.6


def classify_count(n: int) -> CountClass:
    """1/2-4/5+ numeral classification, with the 11-14 exception."""
    n = abs(n)
    if n % 100 in (11, 12, 13, 14):
        return CountClass.MANY
    if n % 10 == 1:
        return CountClass.ONE
    if n % 10 in (2, 3, 4):
        return CountClass.FEW
    return CountClass.MANY


def check_adjective_noun_agreement(
    adjective: str, noun: str, pack: AgreementPack
) -> AgreementIssue | None:
    """None means "agreement confirmed OR not enough confidence to judge" -
    callers that need to distinguish those two should call
    pack.infer_noun_profile(noun) themselves first.
    """
    profile = pack.infer_noun_profile(noun)
    if profile is None or profile.confidence < LOW_CONFIDENCE_THRESHOLD:
        return None

    actual_ending = pack.adjective_ending(adjective)
    expected = pack.expected_endings(profile.gender, profile.number)

    if actual_ending is None:
        return AgreementIssue(
            adjective=adjective,
            noun=noun,
            expected_endings=expected,
            actual_ending=None,
            message=(
                f"'{adjective}' has no recognized inflectional ending "
                f"(short/indefinite form?) - cannot verify agreement with '{noun}'."
            ),
        )

    if actual_ending in expected:
        return None

    return AgreementIssue(
        adjective=adjective,
        noun=noun,
        expected_endings=expected,
        actual_ending=actual_ending,
        message=(
            f"'{adjective}' ends in '-{actual_ending}' but '{noun}' "
            f"({profile.gender.value}/{profile.number.value}) expects "
            f"{sorted(expected)}."
        ),
    )
