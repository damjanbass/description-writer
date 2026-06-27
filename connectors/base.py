"""Connector contract shared by every platform integration.

A connector is the seam between the pipeline and a store: it reads products
in as `ProductRecord`s (so the same ingest->generate->correct flow applies
regardless of source) and writes finished dual-script descriptions back.
Keeping this a Protocol means the runner never imports a concrete platform
and Phase 2 connectors (Selltico, TAU) drop in without touching the pipeline.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.types import DualScript, ProductRecord, Script


@runtime_checkable
class Connector(Protocol):
    """Bidirectional bridge between a store and the pipeline.

    Implementations should isolate all network I/O behind an injectable seam
    (a transport/session object) so they are unit-testable without live HTTP.
    """

    def fetch_products(self) -> list[ProductRecord]:
        """Read the store catalog as pipeline-ready ProductRecords."""
        ...

    def push_description(
        self,
        product_id: str,
        dual: DualScript,
        *,
        publish_script: Script = Script.LATINICA,
    ) -> None:
        """Write a finished dual-script description back to one product.

        `publish_script` selects which rendering becomes the store's primary
        description; implementations may persist the other script in a
        secondary field/meta if the platform supports it.
        """
        ...
