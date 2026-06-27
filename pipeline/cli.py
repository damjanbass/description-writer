"""Stage 5 — CLI entrypoint. `python -m pipeline.cli <catalog> -o <out_dir>`.

`--fake` runs the entire pipeline offline (no API key, no network) using a
canned response - this is what lets the batch pipeline be demoed and tested
end-to-end without an Anthropic account. `AnthropicProvider` is only ever
constructed in the non-fake branch, and that class itself defers the
`anthropic` import to its constructor (see pipeline.generation), so `--fake`
runs need the package installed nowhere on the path.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser

from pipeline.generation import AnthropicProvider, FakeProvider, Provider
from pipeline.ingest import read_products
from pipeline.runner import BatchProcessingError, run_batch, write_outputs
from pipeline.types import Script

# Canned offline response for --fake. Carries no numbers and no attribute
# echoes on purpose, so a demo run never spuriously flags claims/provenance
# issues regardless of what catalog it is pointed at.
_FAKE_RESPONSE = (
    "Ово је демо опис производа, генерисан у режиму --fake без позива ка АИ моделу."
)


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(
        prog="python -m pipeline.cli",
        description="Batch-generate Serbian dual-script product descriptions from a catalog file.",
    )
    parser.add_argument("catalog", help="Path to the input .csv or .xlsx catalog file.")
    parser.add_argument("-o", "--out", default="out", help="Output directory (default: ./out).")
    parser.add_argument(
        "--model", default=None, help="Anthropic model id (ignored when --fake is set)."
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Use a canned offline response instead of calling the Anthropic API.",
    )
    parser.add_argument(
        "--source-script",
        choices=("cirilica", "latinica"),
        default="cirilica",
        help="Script the model is asked to generate in (default: cirilica).",
    )
    args = parser.parse_args(argv)

    try:
        records = read_products(args.catalog)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        provider: Provider
        if args.fake:
            provider = FakeProvider(_FAKE_RESPONSE)
        elif args.model:
            provider = AnthropicProvider(model=args.model)
        else:
            provider = AnthropicProvider()
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    source_script = Script.CIRILICA if args.source_script == "cirilica" else Script.LATINICA

    try:
        results = run_batch(records, provider, source_script=source_script)
    except BatchProcessingError as exc:
        results = exc.partial_results
        for failure in exc.failures:
            print(
                f"warning: product {failure.record.product_id} failed: {failure.error}",
                file=sys.stderr,
            )

    write_outputs(results, args.out)

    total = len(results)
    needs_review = sum(1 for result in results if result.needs_review)
    print(f"Processed {total} product(s); {needs_review} need review. Output: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
