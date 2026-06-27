"""Seed lexicon of noun counting-forms for the 1 / 2-4 / 5+ numeral rule.

This is NOT a general declension engine - it is a small, hand-verified
table of common catalog/product nouns. An unlisted noun returns None (no
verdict) rather than a guessed form: Serbian noun declension has enough
irregularity (mobile vowels like artikal/artikla, inconsistent -ov-/-ev-
plural infixes, multiple genders sharing surface endings) that guessing
risks shipping confidently wrong grammar - worse than flagging "no data"
for human review. Grow this table under copy-editor review, same
discipline as digraph_exceptions.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agreement.types import CountClass


@dataclass(frozen=True)
class CountForms:
    one: str
    few: str  # used for 2, 3, 4 (and 22-24, 32-34, ...)
    many: str  # used for 0, 5-20, 25-31, ... (incl. the 11-14 exception)

    def form_for(self, count_class: CountClass) -> str:
        return {
            CountClass.ONE: self.one,
            CountClass.FEW: self.few,
            CountClass.MANY: self.many,
        }[count_class]


NOUN_COUNT_FORMS: dict[str, CountForms] = {
    "proizvod": CountForms(one="proizvod", few="proizvoda", many="proizvoda"),
    "komad": CountForms(one="komad", few="komada", many="komada"),
    "artikal": CountForms(one="artikal", few="artikla", many="artikala"),
    "telefon": CountForms(one="telefon", few="telefona", many="telefona"),
    "par": CountForms(one="par", few="para", many="parova"),
    "model": CountForms(one="model", few="modela", many="modela"),
    "majica": CountForms(one="majica", few="majice", many="majica"),
    "pakovanje": CountForms(one="pakovanje", few="pakovanja", many="pakovanja"),
}


def expected_noun_form(noun_dict_form: str, count_class: CountClass) -> str | None:
    forms = NOUN_COUNT_FORMS.get(noun_dict_form.lower())
    if forms is None:
        return None
    return forms.form_for(count_class)
