"""WooCommerce connector — Phase 1's one platform integration.

WooCommerce exposes a REST API (wp-json/wc/v3) with HTTP Basic auth using a
consumer key/secret. This connector reads products in as ProductRecords and
writes finished dual-script descriptions back to the `description` field.

IMPLEMENTATION CONTRACT (implement `connectors.base.Connector`):

`WooCommerceConnector(base_url, consumer_key, consumer_secret, *,
transport=None)`
  - All HTTP goes through an injectable `transport` seam so the class is unit-
    testable with a fake (no live HTTP, no `requests` dependency). Define a
    small `Transport` Protocol with e.g.
    `request(method, url, *, params=None, json=None) -> dict | list` and a
    default implementation built on stdlib `urllib.request` + `json` +
    `base64` Basic auth. Do NOT add a third-party HTTP dependency.

`fetch_products() -> list[ProductRecord]`
  - GET wc/v3/products (handle pagination via per_page/page until a short
    page). Map each product to a ProductRecord: product_id = str(id);
    attributes from the useful fields (name, sku, brand/attributes, etc.,
    skipping empty); raw_row may keep the raw dict stringified.

`push_description(product_id, dual, *, publish_script=Script.LATINICA) -> None`
  - PUT wc/v3/products/{product_id} setting `description` to the chosen script
    rendering. Optionally store the other script (e.g. in a meta_data entry)
    so both scripts persist from the one generation.

Tests go in tests/connectors/test_woocommerce.py with a fake transport that
records calls and returns canned product JSON. Cover: fetch maps fields +
follows pagination, push issues a PUT to the right URL with the right script
text, and auth header is set. No network.

DESIGN NOTES (WHY it is shaped this way):

  - The `Transport` seam is the single point where the class touches the
    network. Everything above it — pagination, field mapping, the request
    bodies — is pure logic over plain dicts, so the whole connector is
    exercisable with an in-memory fake that records calls and replays canned
    JSON. That keeps the test suite hermetic (no live store, no `requests`)
    while still covering the behaviour that matters: that we walk every page
    and PUT the right text to the right URL.

  - The default transport is built only on stdlib (`urllib.request`, `json`,
    `base64`). WooCommerce Basic auth is just a base64 of "key:secret" in an
    Authorization header, which `urllib` does not add for us, so we build it
    explicitly via `_basic_auth_header` — a free function so the header logic
    can be asserted directly in a unit test without ever opening a socket.

  - Pagination follows the "short page" convention rather than parsing the
    `X-WP-TotalPages` response header: a transport returning a parsed body
    (dict | list) is far simpler to fake than one that must also surface
    headers, and "a page shorter than per_page means we are done" is a
    correct, header-free stop condition for the wc/v3/products list endpoint.

  - We persist the non-published script in a `meta_data` entry on the same
    PUT, so a single generation round-trips both Serbian scripts (the store's
    primary `description` plus the alternate) without a second write.
"""

from __future__ import annotations

import base64
import json as _json
import urllib.request
from typing import Protocol, runtime_checkable
from urllib.parse import urlencode

from pipeline.types import DualScript, ProductRecord, Script

# How many products to request per list call. WooCommerce caps `per_page` at
# 100; we ask for the max so the catalog is walked in as few round-trips as
# possible. A returned page shorter than this is the signal that we have
# reached the last page (see `fetch_products`).
_PER_PAGE = 100

# WooCommerce product fields worth lifting into ProductRecord.attributes. These
# are the structured, human-meaningful columns generation can be grounded to;
# everything else in the raw product dict (timestamps, image arrays, links) is
# kept only in `raw_row`. `brand` is included because many stores expose it as
# a top-level field even though it is not part of the core schema.
_SCALAR_ATTRIBUTE_FIELDS = (
    "name",
    "sku",
    "slug",
    "type",
    "brand",
    "short_description",
    "price",
    "regular_price",
    "sale_price",
)

# meta_data key under which we stash the non-published script so both Serbian
# renderings survive one generation. Namespaced to avoid clashing with store or
# plugin meta.
_ALT_SCRIPT_META_KEY = "_edg_description_alt_script"


def _basic_auth_header(consumer_key: str, consumer_secret: str) -> str:
    """Build the value of the HTTP Basic `Authorization` header.

    WooCommerce authenticates REST calls over HTTPS with the consumer
    key/secret supplied as Basic-auth credentials. The wire format is the
    literal "Basic " + base64("key:secret"). This is a free function (not a
    transport method) precisely so a unit test can assert the header bytes
    without performing any network I/O.
    """
    raw = f"{consumer_key}:{consumer_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


@runtime_checkable
class Transport(Protocol):
    """The single network seam the connector depends on.

    An implementation takes a fully-qualified URL plus optional query
    parameters and a JSON body, performs the HTTP request, and returns the
    already-parsed JSON response (a dict for a single resource, a list for a
    collection). Keeping the contract at "parsed body in, parsed body out"
    means a test double is a few lines of plain Python.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, object] | None = None,
        json: object | None = None,
    ) -> dict | list:
        """Issue one HTTP request and return the decoded JSON body."""
        ...


class _UrllibTransport:
    """Default stdlib transport: `urllib.request` + `json` + Basic auth.

    Deliberately minimal — it exists so the package has zero third-party HTTP
    dependencies. It attaches the Basic `Authorization` header on every call
    (WooCommerce requires auth for both reads and writes), encodes query params
    onto the URL, and JSON-encodes the request body. All higher-level
    behaviour lives in `WooCommerceConnector`, so this class is intentionally
    not where the interesting logic — or the tests — sit.
    """

    def __init__(self, consumer_key: str, consumer_secret: str) -> None:
        self._auth_header = _basic_auth_header(consumer_key, consumer_secret)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, object] | None = None,
        json: object | None = None,
    ) -> dict | list:
        if params:
            url = f"{url}?{urlencode(params)}"
        data = _json.dumps(json).encode("utf-8") if json is not None else None
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req) as response:  # noqa: S310 - URL is our own base_url
            body = response.read()
        return _json.loads(body) if body else {}


class WooCommerceConnector:
    """Read products from / write descriptions to a WooCommerce store.

    Satisfies `connectors.base.Connector`. All HTTP is delegated to an
    injectable `transport` (defaulting to the stdlib `_UrllibTransport`), so
    the pagination and field-mapping logic here is fully unit-testable with an
    in-memory fake.
    """

    def __init__(
        self,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        transport: Transport | None = None,
    ) -> None:
        # Normalise the base URL once so every endpoint join is a clean
        # f-string. `rstrip("/")` tolerates callers passing a trailing slash.
        self._base_url = base_url.rstrip("/")
        self._transport = (
            transport
            if transport is not None
            else _UrllibTransport(consumer_key, consumer_secret)
        )

    @property
    def _products_url(self) -> str:
        return f"{self._base_url}/wp-json/wc/v3/products"

    def fetch_products(self) -> list[ProductRecord]:
        """Read the whole catalog as ProductRecords, walking every page.

        We page through wc/v3/products with `per_page=_PER_PAGE`, incrementing
        `page` until the store returns a page shorter than `_PER_PAGE` (or an
        empty one) — the header-free stop condition that means "last page".
        Each raw product dict is mapped to a ProductRecord by lifting the
        useful, non-empty fields into `attributes`; the verbatim dict is kept
        (stringified) in `raw_row` for provenance/round-tripping.
        """
        records: list[ProductRecord] = []
        page = 1
        while True:
            payload = self._transport.request(
                "GET",
                self._products_url,
                params={"per_page": _PER_PAGE, "page": page},
            )
            # The collection endpoint returns a JSON array; guard against a
            # non-list (e.g. an error object) so a malformed response stops the
            # loop cleanly instead of raising deep in the mapping code.
            if not isinstance(payload, list):
                break
            for raw in payload:
                if isinstance(raw, dict):
                    records.append(self._to_record(raw))
            if len(payload) < _PER_PAGE:
                break
            page += 1
        return records

    def push_description(
        self,
        product_id: str,
        dual: DualScript,
        *,
        publish_script: Script = Script.LATINICA,
    ) -> None:
        """Write the finished dual-script description back to one product.

        The chosen `publish_script` rendering becomes the store's primary
        `description`; the other script is stashed in a namespaced `meta_data`
        entry on the same PUT so both Serbian renderings persist from a single
        generation. Issued against wc/v3/products/{product_id}.
        """
        alt_script = (
            Script.CIRILICA if publish_script is Script.LATINICA else Script.LATINICA
        )
        body = {
            "description": dual.in_script(publish_script),
            "meta_data": [
                {"key": _ALT_SCRIPT_META_KEY, "value": dual.in_script(alt_script)}
            ],
        }
        self._transport.request(
            "PUT",
            f"{self._products_url}/{product_id}",
            json=body,
        )

    @staticmethod
    def _to_record(raw: dict) -> ProductRecord:
        """Map one raw WooCommerce product dict to a ProductRecord.

        Only the useful, non-empty scalar fields land in `attributes` (the
        structured data generation is grounded to). Variable product
        attributes (the `attributes` array of name/options objects) are
        flattened into `attr:<name>` keys so e.g. a "Boja" attribute is
        grounded just like a top-level column. The full raw dict is stringified
        into `raw_row` for provenance.
        """
        attributes: dict[str, str] = {}
        for field_name in _SCALAR_ATTRIBUTE_FIELDS:
            value = raw.get(field_name)
            if value not in (None, "", [], {}):
                attributes[field_name] = str(value)

        # WooCommerce product attributes arrive as a list of
        # {"name": ..., "options": [...]} dicts; flatten them so each becomes a
        # grounded attribute keyed by its display name.
        for attr in raw.get("attributes", []) or []:
            if not isinstance(attr, dict):
                continue
            name = attr.get("name")
            options = attr.get("options")
            if not name or not options:
                continue
            rendered = ", ".join(str(opt) for opt in options) if isinstance(
                options, list
            ) else str(options)
            if rendered:
                attributes[f"attr:{name}"] = rendered

        raw_row = {key: str(value) for key, value in raw.items()}
        return ProductRecord(
            product_id=str(raw.get("id", "")),
            attributes=attributes,
            raw_row=raw_row,
        )
