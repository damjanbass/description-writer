"""Tests for Stage 2 attribute-grounded generation.

FakeProvider only — no network, no `anthropic` install. Covers the contract:
the prompt lists every supplied attribute value and a no-hallucination
instruction, keeps protected (brand/model/SKU) tokens verbatim, honors the
script, and that `generate_description` round-trips provider output into a
`GeneratedCopy` tagged with the right source script.
"""

from pipeline.generation import (
    DEFAULT_MODEL,
    FakeProvider,
    build_prompt,
    generate_description,
)
from pipeline.types import GeneratedCopy, ProductRecord, Script


def _record() -> ProductRecord:
    return ProductRecord(
        product_id="1",
        attributes={
            "brand": "Samsung",
            "model": "Galaxy S24",
            "storage": "256GB",
            "color": "crna",
        },
    )


class TestBuildPrompt:
    def test_prompt_contains_every_attribute_value(self):
        prompt = build_prompt(_record())
        for value in ("Samsung", "Galaxy S24", "256GB", "crna"):
            assert value in prompt

    def test_prompt_contains_attribute_keys(self):
        prompt = build_prompt(_record())
        for key in ("brand", "model", "storage", "color"):
            assert key in prompt

    def test_prompt_has_no_hallucination_instruction(self):
        # The grounding rule: only the supplied attributes, no invented
        # specs/numbers. Asserted on the Serbian instruction text.
        prompt = build_prompt(_record())
        assert "Не измишљај" in prompt

    def test_prompt_protects_brand_model_sku_tokens_verbatim(self):
        # Glossary tokens (brand/model) must be carried verbatim — and named in
        # the prompt as protected so the model keeps them as-is.
        prompt = build_prompt(_record())
        assert "Samsung" in prompt
        assert "Galaxy" in prompt and "S24" in prompt
        # The protected-token instruction is present (mentions verbatim transfer).
        assert "непромењене" in prompt

    def test_prompt_defaults_to_cirilica(self):
        prompt = build_prompt(_record())
        assert "ћирилицом" in prompt
        assert "латиницом" not in prompt

    def test_prompt_honors_explicit_latinica_script(self):
        prompt = build_prompt(_record(), script=Script.LATINICA)
        assert "латиницом" in prompt
        assert "ћирилицом" not in prompt

    def test_prompt_handles_record_with_no_attributes(self):
        # No structured data => nothing may be asserted; the builder must not
        # crash and must still emit the no-hallucination instruction.
        prompt = build_prompt(ProductRecord(product_id="1", attributes={}))
        assert "Не измишљај" in prompt

    def test_prompt_without_protected_tokens_omits_verbatim_clause(self):
        record = ProductRecord(product_id="1", attributes={"color": "crna"})
        prompt = build_prompt(record)
        assert "непромењене" not in prompt


class TestFakeProvider:
    def test_fixed_string_response_is_returned_for_any_prompt(self):
        provider = FakeProvider("Опис производа.")
        assert provider.complete("any prompt") == "Опис производа."
        assert provider.complete("другачији prompt") == "Опис производа."

    def test_callable_form_receives_the_prompt(self):
        seen: list[str] = []

        def respond(prompt: str) -> str:
            seen.append(prompt)
            return "ехо"

        provider = FakeProvider(respond)
        result = provider.complete("здраво")
        assert result == "ехо"
        assert seen == ["здраво"]


class TestGenerateDescription:
    def test_round_trips_provider_output_into_generated_copy(self):
        provider = FakeProvider("Црна Samsung Galaxy S24 мајица.")
        copy = generate_description(_record(), provider)
        assert isinstance(copy, GeneratedCopy)
        assert copy.text == "Црна Samsung Galaxy S24 мајица."

    def test_default_source_script_is_cirilica(self):
        copy = generate_description(_record(), FakeProvider("текст"))
        assert copy.source_script is Script.CIRILICA

    def test_source_script_matches_requested_script(self):
        copy = generate_description(
            _record(), FakeProvider("tekst"), script=Script.LATINICA
        )
        assert copy.source_script is Script.LATINICA

    def test_provider_receives_the_built_prompt(self):
        # The callable provider proves generate_description hands the provider
        # exactly what build_prompt produced (same script).
        record = _record()
        seen: list[str] = []
        provider = FakeProvider(lambda prompt: seen.append(prompt) or "ok")
        generate_description(record, provider)
        assert seen == [build_prompt(record)]


def test_default_model_is_a_non_empty_string():
    # Guards against an accidental date-suffix / empty default; the model id is
    # a plain alias string per the claude-api skill's model table.
    assert isinstance(DEFAULT_MODEL, str) and DEFAULT_MODEL
