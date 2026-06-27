"""Selltico connector — Phase 2 placeholder, NOT a working integration.

No public Selltico API documentation could be found. A web search for
"Selltico API documentation" turned up no developer docs, no REST/GraphQL
reference, and no sandbox/partner program — only marketing pages. There is
nothing here to implement against: no known base path, no auth scheme, no
product schema, no field names for a description/content update.

This module exists purely so the pipeline has a *named* integration point
that already satisfies `connectors.base.Connector`. The masterplan's Phase 2
line names Selltico as one of the two domestic-platform distribution targets
(see `connectors/__init__.py`), so the runner/CLI should be able to reference
`"selltico"` as a connector choice today — the class just cannot do anything
yet. The moment real API docs or a sandbox account become available, the
constructor signature below is already what a real implementation would
want; only the method bodies need filling in, no call site changes.

NOT SAFE TO POINT AT A LIVE STORE. Contrast this with
`connectors/woocommerce.py`, which is shaped the way it is (an injectable
`Transport` seam, a stdlib-only default transport, pagination over a
documented REST endpoint) because WooCommerce's REST API is public and
stable enough to build against safely. None of those design decisions can be
made responsibly for Selltico without a contract to design them against —
guessing an endpoint path or a request body shape here would not fail loudly,
it would silently write garbage (or nothing) to a real merchant's catalog,
which is strictly worse than refusing to run. So every method below raises
`NotImplementedError` instead of guessing:

  - There is deliberately no `Transport` Protocol and no default transport
    (contrast `connectors.woocommerce.Transport` /
    `connectors.woocommerce._UrllibTransport`) — building a network seam for
    an API we have not seen would itself be an invented contract.
  - `__init__` still takes `base_url`, `api_key`, and an optional `transport`
    and stores them verbatim, because that is the shape a real Selltico
    connector will almost certainly need (a store URL, an API credential, an
    injectable transport for hermetic tests) and locking it in now means a
    future implementer fills in method bodies without touching any call
    site that already constructs `SellticoConnector(...)`.
  - `fetch_products` and `push_description` exist with the exact signatures
    `connectors.base.Connector` requires (so `isinstance(connector,
    Connector)` is `True` via the Protocol's structural check) but each
    raises immediately, naming the platform in the message, so a future
    reader grepping logs or a stack trace knows instantly which placeholder
    fired and why.

Tests live in tests/connectors/test_selltico.py and cover: the connector
satisfies `Connector` structurally, the constructor stores its arguments, and
both methods raise `NotImplementedError` with a message naming "Selltico".
"""

from __future__ import annotations

from pipeline.types import DualScript, ProductRecord, Script


class SellticoConnector:
    """Structural placeholder for a future Selltico integration.

    Satisfies `connectors.base.Connector` by shape only — every method raises
    `NotImplementedError`. See the module docstring for why: no public
    Selltico API documentation exists to implement against, and guessing at
    one risks silently corrupting a real store's catalog.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: object | None = None,
    ) -> None:
        # Stored verbatim, unused for now. This locks in the constructor
        # shape a real implementation will need so that filling in the
        # method bodies later requires no change to existing call sites.
        self._base_url = base_url
        self._api_key = api_key
        self._transport = transport

    def fetch_products(self) -> list[ProductRecord]:
        """Not implemented: no public Selltico API documentation exists.

        Raises unconditionally rather than guessing at an endpoint or
        response shape — see the module docstring.
        """
        raise NotImplementedError(
            "SellticoConnector.fetch_products: no public Selltico API "
            "documentation found; this connector is a structural "
            "placeholder — obtain API docs/credentials before implementing"
        )

    def push_description(
        self,
        product_id: str,
        dual: DualScript,
        *,
        publish_script: Script = Script.LATINICA,
    ) -> None:
        """Not implemented: no public Selltico API documentation exists.

        Raises unconditionally rather than guessing at an endpoint or
        request body shape — see the module docstring.
        """
        raise NotImplementedError(
            "SellticoConnector.push_description: no public Selltico API "
            "documentation found; this connector is a structural "
            "placeholder — obtain API docs/credentials before implementing"
        )
