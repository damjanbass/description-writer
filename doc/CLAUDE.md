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

- **Phase 0** (correctness core) — DONE: transliterator, agreement validator, claims-extractor in
  `core/` + `lang/sr/`.
- **Phase 1** (batch pipeline) — DONE: CSV/XLSX in → generate → correct → dual-script out →
  provenance report, plus a real WooCommerce connector. Run paid pilot.
- **Phase 2** — IN PROGRESS: human review/approval queue (`pipeline/review.py` + the `review`/
  `publish` CLI subcommands) is done — nothing publishes without an explicit approve. The domestic
  connector half is a **named placeholder only**: `connectors/selltico.py` and
  `connectors/tau_commerce.py` satisfy `Connector` and are selectable via `publish --connector`,
  but every method raises `NotImplementedError` — no public API documentation exists for either
  platform. Do NOT fill in real endpoint/auth logic for them without a real API doc or sandbox
  account in hand; guessing a contract here risks silently corrupting a real store, which is the
  one thing worse than not building it.
- **Venture kill criterion**: 3 paid pilots (€2.5k+) from named Serbian retailers before Phase 2.

## Stack

- Language/runtime: Python 3.11+, stdlib only everywhere (no third-party runtime deps; `anthropic`
  is an optional extra, lazily imported)
- Framework: none — CLI is stdlib `argparse` (`pipeline/cli.py`), no web framework
- LLM provider: `pipeline.generation.AnthropicProvider` (real) / `FakeProvider` (offline, what the
  whole test suite uses)
- DB: none — state lives in plain JSON/CSV files under the run's `--out` directory
- Test runner: pytest

## Structure

- `core/transliteration/` — generic engine (`engine.py`), pack interface (`types.py`); no Serbian literals
- `core/agreement/` — generic adj-noun agreement check + 1/2-4/5+ numeral classifier (`engine.py`, `types.py`)
- `core/claims/` — numeric claims-grounding check against structured attributes (`engine.py`, `types.py`)
- `lang/sr/` — Serbian rule pack: `alphabet.py` (30-letter table), `digraph_exceptions.py` (nj/dž
  boundary words), `protected_terms.py` (brand/SKU heuristics), `agreement.py` (gender/number
  ending heuristics), `counting.py` (seed lexicon of noun counting-forms). Clone this directory
  for hr/bs/me/mk later.
- `pipeline/` — `ingest.py` → `generation.py` → `correctness.py` → `provenance.py` → `runner.py`
  (Phase 1 batch flow); `review.py` is the Phase 2 approval-queue data model (`ReviewQueue`,
  PENDING/APPROVED/REJECTED/PUBLISHED — nothing auto-approves); `cli.py` wires it all into
  `generate` / `review list|approve|reject` / `publish` subcommands.
- `connectors/` — `base.py` (the `Connector` Protocol), `woocommerce.py` (real, Phase 1). Phase 2
  adds `selltico.py` / `tau_commerce.py` — named but `NotImplementedError`-only placeholders, see
  Build phases above. Magento not started.
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
