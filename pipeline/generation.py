"""Stage 2 — attribute-grounded generation. ProductRecord -> GeneratedCopy.

IMPLEMENTATION CONTRACT (keep all public signatures below stable):

The product value is *grounded* generation: the model may assert ONLY
attributes present in `record.attributes`. The prompt must instruct the model,
in Serbian, to (a) write a product description in ćirilica (Cyrillic) — the
lossless source script, (b) use only the supplied attributes and invent no
specs/numbers, (c) keep brand/model/SKU tokens verbatim. Generation does not
need to produce latinica — the correctness stage transliterates that.

- `Provider` (Protocol): `.complete(prompt: str) -> str`. The injectable LLM
  seam so the pipeline never hard-depends on a vendor.
- `FakeProvider`: deterministic, no network — accepts either a fixed string or
  a `Callable[[str], str]`. This is what the whole test suite and the runner's
  integration tests use. MUST NOT import any third-party package.
- `AnthropicProvider`: the real provider. LAZILY import `anthropic` *inside*
  `__init__`/`complete` (never at module top) so importing this module and
  running tests needs no `anthropic` install and no API key. Model id is a
  constructor parameter with a sensible default; api_key falls back to the
  ANTHROPIC_API_KEY env var. Use the `claude-api` skill to confirm the current
  model ids and the correct Messages API call shape before writing it.
- `build_prompt(record, *, script=Script.CIRILICA) -> str`: assembles the
  grounded Serbian prompt from the record's attributes (and glossary).
- `generate_description(record, provider, *, script=Script.CIRILICA)
  -> GeneratedCopy`: builds the prompt, calls `provider.complete`, wraps the
  result as `GeneratedCopy(text=..., source_script=script)`.

Tests go in tests/pipeline/test_generation.py using FakeProvider only (no
network). Cover: prompt contains every attribute value + the no-hallucination
instruction, generate_description round-trips provider output into
GeneratedCopy with the right script, and FakeProvider's callable form sees the
built prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pipeline.types import GeneratedCopy, ProductRecord, Script

# Default Claude model for bulk catalog generation. This is a *batch* workload
# (entire CSV/XLSX catalogs, many products per run), so the cost-sensitive
# default is Sonnet — the `claude-api` skill's own cost-optimization guidance
# names `claude-sonnet-4-6` as the "high-volume production workload" tier
# ($3/$15 per 1M tokens vs Opus' $5/$25), and the grounded prompt does the
# heavy lifting of constraining output, so the marginal quality gain from Opus
# does not justify the per-product cost across a large catalog. Callers who
# want maximum fidelity pass `model="claude-opus-4-8"` to the constructor.
# (Model id string is authoritative per the skill's cached model table; do not
# append a date suffix.)
DEFAULT_MODEL = "claude-sonnet-4-6"

# Cap on a single product description. Generation is non-streaming (one short
# call per product), so this stays well under the SDK's non-streaming HTTP
# timeout guard while leaving ample room for a multi-paragraph description.
_MAX_TOKENS = 2048

# Serbian, ćirilica. This is the system instruction that encodes the three hard
# rules from doc/CLAUDE.md: ground every claim in the supplied attributes,
# never invent specs/numbers, and keep protected tokens verbatim. It is written
# in ćirilica because that is also the script we want the output in — the model
# stays in-script far more reliably when the instruction itself is in-script.
_SYSTEM_PROMPT = (
    "Ти си стручни копирајтер за српске продавнице. Пишеш описе производа "
    "искључиво на основу датих атрибута. Никада не измишљаш податке: "
    "не наводиш ниједну особину, спецификацију ни број који није експлицитно "
    "наведен међу атрибутима. Пиши искључиво ћирилицом."
)


class Provider(Protocol):
    """The LLM seam. Any object with `.complete(prompt) -> str` is a provider.

    Defining the dependency as a Protocol (structural typing) is what keeps the
    pipeline vendor-agnostic: `generate_description` only ever sees this shape,
    so the real `AnthropicProvider`, the offline `FakeProvider`, or any future
    backend are interchangeable without the call site importing a vendor SDK.
    """

    def complete(self, prompt: str) -> str: ...


class FakeProvider:
    """Deterministic provider for tests and offline runs.

    Holds either a fixed canned string (return it for every prompt) or a
    callable that is handed the built prompt and returns the response. The
    callable form is what lets a test assert on exactly what the prompt builder
    produced (it receives `build_prompt(...)`'s output verbatim) and lets the
    runner's integration tests synthesize per-record output without a network
    call. Deliberately imports nothing third-party so this module — and the
    whole suite that leans on it — runs with no `anthropic` install.
    """

    def __init__(self, response: str | Callable[[str], str]) -> None:
        self._response = response

    def complete(self, prompt: str) -> str:
        if callable(self._response):
            return self._response(prompt)
        return self._response


class AnthropicProvider:
    """Real Claude-backed provider; lazily imports `anthropic`.

    `anthropic` is an optional dependency (`[project.optional-dependencies] llm`)
    and is imported *inside* `__init__`/`complete`, never at module import time,
    so importing `pipeline.generation` and running the test suite (which only
    ever uses `FakeProvider`) needs neither the package nor an API key. The
    model id is a constructor parameter (see `DEFAULT_MODEL` for why Sonnet is
    the batch default) and the API key falls back to the ANTHROPIC_API_KEY
    environment variable via the SDK's own credential resolution.
    """

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        # Lazy import: keeps `import pipeline.generation` free of any third-party
        # dependency. Surfaced as a clear, actionable error if the optional
        # extra is not installed.
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ImportError(
                "AnthropicProvider requires the optional 'anthropic' dependency. "
                "Install it with: pip install 'ecommerce-description-generator[llm]'"
            ) from exc

        self.model = model
        # Passing api_key=None lets the SDK fall back to the ANTHROPIC_API_KEY
        # env var (its default credential resolution), so callers can rely on
        # the environment without threading the key through this constructor.
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, prompt: str) -> str:
        # Non-streaming single call: one short description per product. Adaptive
        # thinking is the recommended default on current Claude models and is a
        # no-op on models that predate it; the grounding system prompt carries
        # the hard rules, the user prompt carries the per-product attributes.
        message = self._client.messages.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        # `content` is a list of typed blocks; concatenate the text blocks so a
        # response split across multiple text blocks is not silently truncated.
        return "".join(block.text for block in message.content if block.type == "text")


def build_prompt(record: ProductRecord, *, script: Script = Script.CIRILICA) -> str:
    """Assemble the grounded Serbian generation prompt for one product.

    The prompt lists every supplied attribute as ``key: value`` and instructs
    the model, in Serbian, to (a) use ONLY those attributes and invent no specs
    or numbers, (b) keep brand/model/SKU tokens (``record.glossary``) verbatim,
    and (c) write in the requested script (ćirilica by default — the lossless
    source script per ``pipeline.types``). Every attribute *value* appears
    literally in the text so the downstream claims/provenance checks, which
    match generated copy against these values, have something to anchor to.

    ``script`` is honored generically rather than hard-coding ćirilica: the
    enum already carries the human-facing script name, so a latinica request
    produces a latinica instruction with no Serbian-only branching here.
    """
    script_name = "ћирилицом" if script is Script.CIRILICA else "латиницом"

    lines: list[str] = []
    lines.append(
        "Напиши маркетиншки опис производа на српском језику, " f"{script_name}."
    )
    lines.append("")
    lines.append("Атрибути производа (једини извор података):")
    if record.attributes:
        for key, value in record.attributes.items():
            lines.append(f"- {key}: {value}")
    else:
        # No structured data => nothing may be asserted. Say so explicitly
        # rather than emitting an empty list the model might "fill in".
        lines.append("- (нема датих атрибута)")
    lines.append("")

    # The no-hallucination rule, restated in the user turn (not only the system
    # prompt) so it travels with the data even if a provider drops the system
    # prompt. This is the line tests assert on for "no invented specs/numbers".
    lines.append(
        "Користи ИСКЉУЧИВО горе наведене атрибуте. Не измишљај никакве "
        "податке, спецификације ни бројеве који нису наведени."
    )

    # Protected tokens (brand/model/SKU), carried verbatim. Tied to the
    # product's own structured input via record.glossary so transliteration and
    # generation protect exactly the same tokens (0% protected-term error is a
    # hard rule in doc/CLAUDE.md).
    glossary = sorted(record.glossary)
    if glossary:
        tokens = ", ".join(glossary)
        lines.append(
            "Следеће ознаке (бренд, модел, SKU) пренеси у потпуности "
            f"непромењене, тачно овако како су написане: {tokens}."
        )

    return "\n".join(lines)


def generate_description(
    record: ProductRecord, provider: Provider, *, script: Script = Script.CIRILICA
) -> GeneratedCopy:
    """Build the grounded prompt, run it through `provider`, wrap the result.

    The whole of Stage 2 in one seam: `build_prompt` encodes the grounding
    rules, `provider.complete` is the swappable LLM call, and the output is
    tagged with the `script` it was generated in so the correctness stage knows
    which direction to transliterate. `source_script` is set from the same
    `script` used to build the prompt, so the tag can never disagree with the
    instruction the model actually received.
    """
    prompt = build_prompt(record, script=script)
    text = provider.complete(prompt)
    return GeneratedCopy(text=text, source_script=script)
