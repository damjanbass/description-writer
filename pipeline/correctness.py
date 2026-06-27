"""Stage 3 — correctness layer. GeneratedCopy -> CorrectnessResult.

This stage is where the Phase 0 moat (core/transliteration, core/agreement,
core/claims + the lang/sr packs) is wired into the pipeline. It must not
re-implement any rule — only orchestrate the existing engines.

IMPLEMENTATION CONTRACT (keep the public signature stable):

`apply_correctness(generated, record, *, pack=SR_PACK,
agreement_pack=SR_AGREEMENT_PACK) -> CorrectnessResult`

Steps:
1. Produce both scripts from the single generation (NEVER regenerate):
   - If `generated.source_script` is CIRILICA, the ćirilica text is the
     generation as-is; derive latinica via
     `transliterate(text, pack, Direction.SCRIPT_A_TO_B, glossary=record.glossary)`.
   - If LATINICA, derive ćirilica via Direction.SCRIPT_B_TO_A.
   - Always pass `record.glossary` so brand/model/SKU tokens stay verbatim.
   - Wrap as `DualScript(cirilica=..., latinica=...)`.
2. Run grammatical analysis on the LATINICA rendering (lang/sr heuristics are
   Latin-script forms): tokenize, and for each adjacent (adjective, noun)
   candidate pair call `check_adjective_noun_agreement(adj, noun,
   agreement_pack)`; collect the non-None `AgreementIssue`s into a tuple.
3. Run `check_claims(latinica_text, record.attributes)` for the ClaimsReport
   (numeric grounding is script-invariant; attribute values are latinica).
4. Return `CorrectnessResult(dual_script, claims, agreement_issues)`.

WHY transliterate instead of regenerate (step 1): a second LLM call would be
non-deterministic — the two scripts could diverge in wording, numbers, or
claims, which would defeat the whole point of dual-script output. Cyrillic is
the lossless source script (see lang/sr/alphabet.py), so the Latin rendering
is a pure, reproducible function of the one generation. The glossary
(record.glossary, the product's own brand/model/SKU attribute values) is
threaded into both directions so a protected token such as "iPhone" is copied
verbatim into BOTH scripts and never touches the mapping table.

WHY analysis runs on the latinica side (steps 2-3): the lang/sr agreement and
claims heuristics are defined over Latin-script forms, and product attribute
values are conventionally latinica, so the Latin rendering is the only side
where the validators are meaningful (per pipeline/types.py).

WHY the adjacency heuristic below is gated rather than "every adjacent pair":
the stub notes over-pairing is safe because the validator abstains on
low-confidence words. That holds when the *noun* (second token) is the
ambiguous one, but the lang/sr noun heuristic is purely ending-based, so it
*confidently* profiles short function words (e.g. "od", "za", "sa", "i") and
oblique-case nouns. Feeding those as adjective→noun pairs makes the validator
emit issues on perfectly clean copy (e.g. a noun followed by a preposition).
This stage therefore filters *which* pairs reach the validator — a
tokenization concern, the same kind of narrow seed-list the engines
themselves use — without making any grammatical judgment of its own; the
validator still decides every pass/fail/abstain verdict. The filter is:
  - split on sentence punctuation first, so no pair straddles a sentence;
  - skip any pair touching a short Serbian function word (prepositions /
    conjunctions / clitics — never an attributive adjective or a head noun);
  - only let a word *lead* a pair when it is a recognized inflected adjective
    form, i.e. `agreement_pack.adjective_ending(word) is not None` (the pack's
    own signal — a consonant-ending word is a short/oblique form the
    nominative-scoped validator cannot judge anyway).
"""

from __future__ import annotations

import re

from core.agreement.engine import check_adjective_noun_agreement
from core.agreement.types import AgreementIssue, AgreementPack
from core.claims.engine import check_claims
from core.transliteration.engine import transliterate
from core.transliteration.types import Direction, TransliterationPack
from lang.sr import SR_PACK
from lang.sr.agreement import SR_AGREEMENT_PACK
from pipeline.types import CorrectnessResult, DualScript, GeneratedCopy, ProductRecord, Script

# Sentence boundaries: a pair must never straddle two sentences (the last
# noun of one clause is not modified by the first adjective of the next).
_SENTENCE_RE = re.compile(r"[.!?…]+")

# Word tokens: letters only (Unicode), so punctuation and standalone numbers
# are stripped. `\d` is excluded so "128GB" / "6.1" never enter agreement
# pairing — numeric grounding is the claims engine's job, not agreement's.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Short Serbian function words (prepositions, conjunctions, clitics). None of
# these is ever an attributive adjective or a head noun, so a pair touching
# one carries no agreement signal — but the ending-based noun heuristic would
# still confidently profile them (e.g. "od" → masculine), producing false
# positives. Skipping them is a tokenization decision, not a grammar rule:
# the agreement *verdict* is still entirely the validator's. Lowercase only;
# matched case-insensitively.
_FUNCTION_WORDS: frozenset[str] = frozenset({
    # conjunctions / particles
    "i", "pa", "te", "ni", "a", "ali", "ili", "no", "već", "nego",
    # prepositions
    "u", "na", "za", "od", "do", "iz", "sa", "s", "o", "po", "uz", "niz",
    "kroz", "pred", "nad", "pod", "pre", "bez", "među", "radi", "zbog",
    "preko", "oko", "ka", "k", "uoči", "duž", "putem",
    # clitics / common auxiliaries
    "je", "su", "smo", "ste", "sam", "si", "se", "li", "da", "ne",
})


def apply_correctness(
    generated: GeneratedCopy,
    record: ProductRecord,
    *,
    pack: TransliterationPack = SR_PACK,
    agreement_pack: AgreementPack = SR_AGREEMENT_PACK,
) -> CorrectnessResult:
    """Wire the Phase 0 validators onto one generation and return its review state.

    `generated` is a single-script generation; `record` supplies the structured
    attributes that claims are grounded to and (via `record.glossary`) the
    brand/model/SKU tokens protected verbatim across transliteration. `pack` and
    `agreement_pack` are injected for language-pluggability (sr → hr/bs/me/mk
    later) and default to the Serbian packs.

    Returns a `CorrectnessResult` carrying the dual-script copy plus every issue
    the validators surfaced; `result.needs_review` is True iff a numeric claim
    is unsupported or an agreement issue was found.
    """
    dual_script = _build_dual_script(generated, record, pack)
    latinica = dual_script.latinica

    agreement_issues = _check_agreement(latinica, agreement_pack)
    claims = check_claims(latinica, record.attributes)

    return CorrectnessResult(
        dual_script=dual_script,
        claims=claims,
        agreement_issues=agreement_issues,
    )


def _build_dual_script(
    generated: GeneratedCopy,
    record: ProductRecord,
    pack: TransliterationPack,
) -> DualScript:
    """Render both scripts from the single generation by transliteration only.

    The source script is kept verbatim; the other is derived in the lossless
    direction (Cyrillic↔Latin) with the product's glossary threaded through so
    protected tokens are copied byte-for-byte into both renderings.
    """
    text = generated.text
    glossary = record.glossary

    if generated.source_script is Script.CIRILICA:
        cirilica = text
        latinica = transliterate(text, pack, Direction.SCRIPT_A_TO_B, glossary=glossary)
    else:
        latinica = text
        cirilica = transliterate(text, pack, Direction.SCRIPT_B_TO_A, glossary=glossary)

    return DualScript(cirilica=cirilica, latinica=latinica)


def _check_agreement(latinica: str, agreement_pack: AgreementPack) -> tuple[AgreementIssue, ...]:
    """Collect adjective→noun agreement issues over the Latin-script rendering.

    Pairs are formed only within a sentence, skip short function words, and lead
    with a recognized inflected adjective (see the module docstring for why).
    Every selected pair is handed to `check_adjective_noun_agreement`, which
    owns the actual pass/fail/abstain decision; this function never judges
    agreement itself.
    """
    issues: list[AgreementIssue] = []
    for sentence in _SENTENCE_RE.split(latinica):
        words = _WORD_RE.findall(sentence)
        for adjective, noun in zip(words, words[1:]):
            if adjective.lower() in _FUNCTION_WORDS or noun.lower() in _FUNCTION_WORDS:
                continue
            # Only an inflected (vowel-ending) adjective form can lead a pair;
            # this uses the pack's own signal, not a rule defined here.
            if agreement_pack.adjective_ending(adjective) is None:
                continue
            issue = check_adjective_noun_agreement(adjective, noun, agreement_pack)
            if issue is not None:
                issues.append(issue)
    return tuple(issues)
