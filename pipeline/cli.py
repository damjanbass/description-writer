"""Stage 5 — CLI entrypoint. Subcommands:

  generate <catalog> -o <out_dir> [--model] [--fake] [--source-script]
      Batch-generate dual-script descriptions (Phase 1 behaviour, unchanged)
      and seed a Phase 2 review queue (`<out_dir>/review_queue.json`) with
      every product PENDING — see pipeline.review for why nothing is
      auto-approved here, even a product with `needs_review=False`.

  review list -o <out_dir> [--status pending|approved|rejected|published]
  review approve <product_id> -o <out_dir>
  review reject <product_id> -o <out_dir> [--reason TEXT]
      Phase 2 human-in-the-loop gate over the queue `generate` wrote.

  publish -o <out_dir> --connector {woocommerce,selltico,tau_commerce}
          [--base-url URL] [--consumer-key KEY] [--consumer-secret SECRET]
          [--publish-script cirilica|latinica] [--fake-connector]
      Push every APPROVED item to the chosen connector, then mark it
      PUBLISHED. PENDING/REJECTED items are skipped. `selltico` and
      `tau_commerce` are named, selectable connectors today (per
      connectors/selltico.py and connectors/tau_commerce.py) but raise
      NotImplementedError on push — no public API docs exist for either yet.
      A per-product push failure is reported as a warning and the item is
      left APPROVED (retryable) rather than aborting the whole run, the same
      "never abort on one bad record" contract `run_batch` uses.

`--fake` (generate) and `--fake-connector` (publish) are what let the whole
Phase 1+2 flow be demoed/tested offline, with no API key, no network, no
store credentials - the same role `--fake` already played for Stage 5's LLM
call, now extended to the connector call. `AnthropicProvider` and the real
connectors are only ever constructed in the non-fake branches, so `--fake`
/`--fake-connector` runs need neither package nor credentials on the path.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from pathlib import Path

from connectors.base import Connector
from connectors.selltico import SellticoConnector
from connectors.tau_commerce import TauCommerceConnector
from connectors.woocommerce import WooCommerceConnector
from pipeline.generation import AnthropicProvider, FakeProvider, Provider
from pipeline.ingest import read_products
from pipeline.review import (
    ReviewQueue,
    ReviewStatus,
    build_review_queue,
    review_queue_from_json,
    review_queue_to_json,
)
from pipeline.runner import BatchProcessingError, run_batch, write_outputs
from pipeline.types import DualScript, ProductRecord, Script

# Canned offline response for --fake. Carries no numbers and no attribute
# echoes on purpose, so a demo run never spuriously flags claims/provenance
# issues regardless of what catalog it is pointed at.
_FAKE_RESPONSE = (
    "Ово је демо опис производа, генерисан у режиму --fake без позива ка АИ моделу."
)

# Filename the review queue is written under, inside the same --out directory
# `write_outputs` already writes descriptions.csv/provenance/* into. Keeping
# all of one run's artifacts in one directory is what lets `review`/`publish`
# take just `-o <out_dir>` and find everything `generate` produced.
_REVIEW_QUEUE_FILENAME = "review_queue.json"


def _queue_path(out_dir: str) -> Path:
    return Path(out_dir) / _REVIEW_QUEUE_FILENAME


def _load_queue(out_dir: str) -> ReviewQueue:
    """Read the review queue `generate` wrote. Raises OSError if absent."""
    return review_queue_from_json(_queue_path(out_dir).read_text(encoding="utf-8"))


def _save_queue(queue: ReviewQueue, out_dir: str) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    _queue_path(out_dir).write_text(review_queue_to_json(queue), encoding="utf-8")


class _FakeConnector:
    """In-memory Connector for `--fake-connector`: records pushes, does
    nothing else. Mirrors FakeProvider's role for the LLM call - lets
    `publish` be demoed/tested with no store credentials and no network.
    """

    def __init__(self) -> None:
        self.pushed: list[tuple[str, DualScript, Script]] = []

    def fetch_products(self) -> list[ProductRecord]:
        return []

    def push_description(
        self,
        product_id: str,
        dual: DualScript,
        *,
        publish_script: Script = Script.LATINICA,
    ) -> None:
        self.pushed.append((product_id, dual, publish_script))


# One factory per `--connector` choice. selltico/tau_commerce are included
# deliberately - their docstrings say the runner/CLI should be able to
# reference them as named connector choices today, even though every method
# they implement raises NotImplementedError until real API docs exist.
_CONNECTOR_FACTORIES: dict[str, Callable[[Namespace], Connector]] = {
    "woocommerce": lambda a: WooCommerceConnector(a.base_url, a.consumer_key, a.consumer_secret),
    "selltico": lambda a: SellticoConnector(a.base_url, a.consumer_key),
    "tau_commerce": lambda a: TauCommerceConnector(a.base_url, a.consumer_key),
}


def _build_connector(args: Namespace) -> Connector:
    if args.fake_connector:
        return _FakeConnector()
    if not args.base_url or not args.consumer_key:
        raise ValueError(
            "--base-url and --consumer-key are required unless --fake-connector is set"
        )
    if args.connector == "woocommerce" and not args.consumer_secret:
        raise ValueError("--consumer-secret is required for --connector woocommerce")
    return _CONNECTOR_FACTORIES[args.connector](args)


def _cmd_generate(args: Namespace) -> int:
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
    _save_queue(build_review_queue(results), args.out)

    total = len(results)
    needs_review = sum(1 for result in results if result.needs_review)
    print(
        f"Processed {total} product(s); {needs_review} need review. "
        f"Output: {args.out} (review queue: {_queue_path(args.out)})"
    )
    return 0


def _cmd_review_list(args: Namespace) -> int:
    try:
        queue = _load_queue(args.out)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    items = queue.by_status(ReviewStatus(args.status)) if args.status else queue.items
    if not items:
        print("No items match.")
        return 0

    for item in items:
        flag = " [needs review]" if item.needs_review else ""
        reason = f" reason={item.reason!r}" if item.reason else ""
        print(f"{item.product_id}\t{item.status.value}{flag}{reason}")
    return 0


def _cmd_review_approve(args: Namespace) -> int:
    try:
        queue = _load_queue(args.out)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        queue = queue.approve(args.product_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _save_queue(queue, args.out)
    print(f"Approved {args.product_id}.")
    return 0


def _cmd_review_reject(args: Namespace) -> int:
    try:
        queue = _load_queue(args.out)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        queue = queue.reject(args.product_id, reason=args.reason)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _save_queue(queue, args.out)
    print(f"Rejected {args.product_id}.")
    return 0


def _cmd_publish(args: Namespace) -> int:
    try:
        queue = _load_queue(args.out)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        connector = _build_connector(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    publish_script = Script.CIRILICA if args.publish_script == "cirilica" else Script.LATINICA

    approved_items = queue.by_status(ReviewStatus.APPROVED)
    skipped = len(queue.items) - len(approved_items)
    published = 0
    failed = 0
    for item in approved_items:
        try:
            connector.push_description(
                item.product_id, item.dual_script, publish_script=publish_script
            )
        except Exception as exc:  # noqa: BLE001 - one bad product must not abort the run
            failed += 1
            print(f"warning: product {item.product_id} failed to publish: {exc}", file=sys.stderr)
            continue
        queue = queue.mark_published(item.product_id)
        published += 1

    _save_queue(queue, args.out)
    print(f"Published {published} product(s); {failed} failed; {skipped} not approved (skipped).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(
        prog="python -m pipeline.cli",
        description="Batch-generate, review, and publish Serbian dual-script product descriptions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser(
        "generate", help="Generate dual-script descriptions from a catalog file."
    )
    generate.add_argument("catalog", help="Path to the input .csv or .xlsx catalog file.")
    generate.add_argument("-o", "--out", default="out", help="Output directory (default: ./out).")
    generate.add_argument(
        "--model", default=None, help="Anthropic model id (ignored when --fake is set)."
    )
    generate.add_argument(
        "--fake",
        action="store_true",
        help="Use a canned offline response instead of calling the Anthropic API.",
    )
    generate.add_argument(
        "--source-script",
        choices=("cirilica", "latinica"),
        default="cirilica",
        help="Script the model is asked to generate in (default: cirilica).",
    )
    generate.set_defaults(func=_cmd_generate)

    review = subparsers.add_parser("review", help="Inspect or decide on the review queue.")
    review_subparsers = review.add_subparsers(dest="review_command", required=True)

    review_list = review_subparsers.add_parser("list", help="List items in the review queue.")
    review_list.add_argument(
        "-o", "--out", default="out", help="Output directory (default: ./out)."
    )
    review_list.add_argument(
        "--status",
        choices=("pending", "approved", "rejected", "published"),
        default=None,
        help="Only list items in this status (default: all).",
    )
    review_list.set_defaults(func=_cmd_review_list)

    review_approve = review_subparsers.add_parser("approve", help="Approve one product.")
    review_approve.add_argument("product_id")
    review_approve.add_argument(
        "-o", "--out", default="out", help="Output directory (default: ./out)."
    )
    review_approve.set_defaults(func=_cmd_review_approve)

    review_reject = review_subparsers.add_parser("reject", help="Reject one product.")
    review_reject.add_argument("product_id")
    review_reject.add_argument(
        "-o", "--out", default="out", help="Output directory (default: ./out)."
    )
    review_reject.add_argument("--reason", default=None, help="Optional rejection note.")
    review_reject.set_defaults(func=_cmd_review_reject)

    publish = subparsers.add_parser("publish", help="Push approved descriptions to a connector.")
    publish.add_argument("-o", "--out", default="out", help="Output directory (default: ./out).")
    publish.add_argument(
        "--connector",
        choices=("woocommerce", "selltico", "tau_commerce"),
        required=True,
        help="Which connector to publish through.",
    )
    publish.add_argument("--base-url", default=None, help="Store base URL.")
    publish.add_argument("--consumer-key", default=None, help="API key/consumer key.")
    publish.add_argument(
        "--consumer-secret", default=None, help="Consumer secret (required for woocommerce)."
    )
    publish.add_argument(
        "--publish-script",
        choices=("cirilica", "latinica"),
        default="latinica",
        help="Script written to the connector's primary description field (default: latinica).",
    )
    publish.add_argument(
        "--fake-connector",
        action="store_true",
        help="Use an in-memory connector instead of a real store (no network, no credentials).",
    )
    publish.set_defaults(func=_cmd_publish)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
