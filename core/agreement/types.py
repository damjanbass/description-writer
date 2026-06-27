"""Language-agnostic contract for the agreement validator.

Scope (Phase 0 v1): nominative-case adjective<->noun gender/number
agreement, plus the 1 / 2-4 / 5+ numeral counting-class rule. Full 7-case
declension is NOT attempted here - product titles and short descriptions
are overwhelmingly nominative, and a real case-declension generator needs
a noun lexicon (gender + declension class per noun) that is a substantially
bigger effort than Phase 0. This module is scoped to validate, not to
silently auto-correct: low-confidence or unknown words are flagged for
human review rather than guessed, matching how core/transliteration
handles unrecognized protected terms.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class Gender(Enum):
    MASCULINE = "m"
    FEMININE = "f"
    NEUTER = "n"


class Number(Enum):
    SINGULAR = "sg"
    PLURAL = "pl"


class CountClass(Enum):
    ONE = "one"  # 1, 21, 31, ... (not 11)
    FEW = "few"  # 2-4, 22-24, 32-34, ...
    MANY = "many"  # 0, 5-20, 25-30, ...


@dataclass(frozen=True)
class NounProfile:
    gender: Gender
    number: Number
    confidence: float  # 0.0-1.0; below the caller's threshold = flag, don't assert


@dataclass(frozen=True)
class AgreementIssue:
    adjective: str
    noun: str
    expected_endings: frozenset[str]
    actual_ending: str | None
    message: str


@dataclass(frozen=True)
class AgreementPack:
    name: str
    infer_noun_profile: Callable[[str], NounProfile | None]
    adjective_ending: Callable[[str], str | None]
    expected_endings: Callable[[Gender, Number], frozenset[str]]
