# CLAUDE.md

Project context for Claude Code. Keep this lean — it loads every turn.
Full strategy lives in `serbian-product-description-saas-plan.md`; read it on demand, don't duplicate it here.

## What this is

A Serbian-language **catalog correctness & compliance engine** that generates product
descriptions. NOT a generic "AI writes descriptions" tool — that market is dead
(Describely/Hypotenuse own it). The moat is correctness + compliance + local integration.

If a request drifts toward "just generate copy," push back: the value is in the layers below.

## The wedge (never lose this)

1. **Correctness** — deterministic Serbian grammar (7 cases, gender/number agreement) +
   ćirilica↔latinica transliteration. Copy-editor-grade output in BOTH scripts from ONE generation.
2. **Compliance** — generation is grounded to input attributes only. No hallucinated specs.
   Claims-provenance: every factual sentence maps to a source attribute. Ties to Zakon o
   zaštiti potrošača 88/2021 (Right to Information, Serbian-language, burden on trader).
3. **Distribution** — native connectors for domestic platforms (Selltico, TAU Commerce) that
   global tools will never build. WooCommerce + Magento first.

Defensibility order: Distribution > Correctness > Compliance.

## Hard rules (do not violate)

- Transliteration of protected terms (brand names, model numbers, SKUs) = **0% error**.
  "iPhone" never becomes "ајПхоне". This is non-negotiable; if logic can't guarantee it, flag it.
- Never assert a product attribute not present in the structured input. Unsupported claim → flag, don't write it.
- Every generation produces both ćirilica and latinica from a single LLM call (transliterate, don't regenerate).
- Agreement rules must be **pluggable per-language** from day one (sr → hr/bs/me/mk later). No Serbian-only hardcoding in the core.
- Pricing model is catalog-state licensing, never per-product credits. Don't build metered billing.

## Build phases & kill criteria

- **Phase 0** (correctness core): standalone post-processor — transliterator, agreement
  validator, claims-extractor. KILL: copy editor reviews 200 products → <3% agreement error,
  0% protected-term transliteration error. If transliteration ≠ 0%, the moat is fake. Stop.
- **Phase 1**: batch pipeline (CSV/XLSX in → generate → correct → dual-script out → provenance
  report) + 1 connector (WooCommerce). Run paid pilot.
- **Phase 2**: domestic connector (Selltico/TAU) + human review/approval queue.
- **Venture kill criterion**: 3 paid pilots (€2.5k+) from named Serbian retailers before Phase 2.

## Stack

- Language/runtime: Python 3.11+, stdlib only in `core`/`lang` (no third-party runtime deps yet)
- Framework: none yet — `pipeline/` and `connectors/` are still empty, Phase 1 work
- LLM provider: not yet integrated — Phase 0 is the standalone correctness core only
- DB: none yet
- Test runner: pytest

## Structure

- `core/transliteration/` — generic engine (`engine.py`), pack interface (`types.py`); no Serbian literals
- `core/agreement/` — generic adj-noun agreement check + 1/2-4/5+ numeral classifier (`engine.py`, `types.py`)
- `core/claims/` — numeric claims-grounding check against structured attributes (`engine.py`, `types.py`)
- `lang/sr/` — Serbian rule pack: `alphabet.py` (30-letter table), `digraph_exceptions.py` (nj/dž
  boundary words), `protected_terms.py` (brand/SKU heuristics), `agreement.py` (gender/number
  ending heuristics), `counting.py` (seed lexicon of noun counting-forms). Clone this directory
  for hr/bs/me/mk later.
- `pipeline/` — batch generation flow. Not yet built (Phase 1).
- `connectors/` — platform integrations (woocommerce, magento, selltico, tau). Not yet built (Phase 1/2).
- `tests/` — mirrors the source tree 1:1 (`tests/core/...`, `tests/lang/sr/...`)

Key design pattern used throughout `core/`: a generic engine takes a "pack" (a dataclass of
data + callables) supplied by `lang/sr/`, so no language ever gets hardcoded into `core/`.
Unrecognized/ambiguous input is flagged for human review rather than guessed — see the
`is_protected_word` glossary fallback and the agreement validator's confidence threshold.

## Commands

- Install: `python -m venv .venv` then `.venv\Scripts\python.exe -m pip install pytest ruff`
- Dev: n/a — no app/CLI yet, this is library code consumed by tests
- Test: `.venv\Scripts\python.exe -m pytest`
- Lint: `.venv\Scripts\python.exe -m ruff check .`

## Working style

- Direct, production-oriented. Honest pushback over validation.
- Output in Serbian latinica when writing user-facing copy; English for code/comments.
- Concrete deliverables. Don't over-explain; do the work.
- When a change touches the correctness core, write a test first — that code is the moat.
