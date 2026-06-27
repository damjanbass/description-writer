"""Tests for the WooCommerce connector.

Every test drives the connector through a `FakeTransport` that records each
call and replays canned product JSON, so the suite is fully hermetic — no
sockets, no `requests`, no live store. The three behaviours the contract
singles out are covered: fetch maps fields, fetch follows pagination, and push
PUTs the right script text to the right URL. The Basic-auth header is asserted
against the `_basic_auth_header` helper directly, which is why no request is
ever sent.
"""

from __future__ import annotations

import base64

from connectors.base import Connector
from connectors.woocommerce import (
    WooCommerceConnector,
    _basic_auth_header,
    _UrllibTransport,
)
from pipeline.types import DualScript, ProductRecord, Script


class FakeTransport:
    """In-memory `Transport`: records calls, replays queued responses.

    `responses` is consumed in order, one per `request` call; once exhausted it
    falls back to `default_response`. Every call is appended to `calls` as a
    dict so tests can assert on method, URL, params, and JSON body.
    """

    def __init__(
        self,
        responses: list[dict | list] | None = None,
        *,
        default_response: dict | list | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._default = {} if default_response is None else default_response
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, object] | None = None,
        json: object | None = None,
    ) -> dict | list:
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": json}
        )
        if self._responses:
            return self._responses.pop(0)
        return self._default


def _product(product_id: int, **fields: object) -> dict:
    """Build a minimal raw WooCommerce product dict for canned responses."""
    base: dict[str, object] = {"id": product_id, "name": f"Proizvod {product_id}"}
    base.update(fields)
    return base


def _make_connector(transport: FakeTransport) -> WooCommerceConnector:
    return WooCommerceConnector(
        "https://shop.example.com",
        "ck_key",
        "cs_secret",
        transport=transport,
    )


class TestConnectorProtocol:
    def test_satisfies_connector_protocol(self):
        connector = _make_connector(FakeTransport())
        # runtime_checkable Protocol: confirms the public surface matches base.
        assert isinstance(connector, Connector)


class TestFetchProductsMapping:
    def test_maps_scalar_fields_into_attributes(self):
        transport = FakeTransport(
            responses=[[_product(7, sku="ABC-1", brand="Samsung", price="999")]]
        )
        records = _make_connector(transport).fetch_products()

        assert len(records) == 1
        record = records[0]
        assert isinstance(record, ProductRecord)
        assert record.product_id == "7"
        assert record.attributes["name"] == "Proizvod 7"
        assert record.attributes["sku"] == "ABC-1"
        assert record.attributes["brand"] == "Samsung"
        assert record.attributes["price"] == "999"

    def test_empty_fields_are_skipped(self):
        transport = FakeTransport(
            responses=[[_product(7, sku="", brand=None, sale_price="")]]
        )
        record = _make_connector(transport).fetch_products()[0]
        assert "sku" not in record.attributes
        assert "brand" not in record.attributes
        assert "sale_price" not in record.attributes

    def test_variable_attributes_are_flattened(self):
        transport = FakeTransport(
            responses=[
                [
                    _product(
                        7,
                        attributes=[
                            {"name": "Boja", "options": ["Crna", "Bela"]},
                            {"name": "Empty", "options": []},
                        ],
                    )
                ]
            ]
        )
        record = _make_connector(transport).fetch_products()[0]
        assert record.attributes["attr:Boja"] == "Crna, Bela"
        assert "attr:Empty" not in record.attributes

    def test_raw_row_preserves_full_dict_stringified(self):
        transport = FakeTransport(responses=[[_product(7, sku="ABC-1")]])
        record = _make_connector(transport).fetch_products()[0]
        # raw_row keeps every field (incl. id) as strings for provenance.
        assert record.raw_row["id"] == "7"
        assert record.raw_row["sku"] == "ABC-1"

    def test_product_id_is_stringified(self):
        transport = FakeTransport(responses=[[_product(123)]])
        record = _make_connector(transport).fetch_products()[0]
        assert record.product_id == "123"
        assert isinstance(record.product_id, str)


class TestFetchProductsPagination:
    def test_follows_pagination_until_short_page(self):
        # First page is full (100 products) -> connector must request page 2;
        # second page is short (2 products) -> connector must stop there.
        full_page = [_product(i) for i in range(1, 101)]
        short_page = [_product(101), _product(102)]
        transport = FakeTransport(responses=[full_page, short_page])

        records = _make_connector(transport).fetch_products()

        assert len(records) == 102
        # Exactly two GETs were issued: page 1 then page 2.
        assert len(transport.calls) == 2
        assert transport.calls[0]["params"] == {"per_page": 100, "page": 1}
        assert transport.calls[1]["params"] == {"per_page": 100, "page": 2}
        # All calls hit the collection endpoint with GET.
        for call in transport.calls:
            assert call["method"] == "GET"
            assert call["url"] == "https://shop.example.com/wp-json/wc/v3/products"

    def test_stops_after_single_short_page(self):
        transport = FakeTransport(responses=[[_product(1), _product(2)]])
        records = _make_connector(transport).fetch_products()
        assert len(records) == 2
        assert len(transport.calls) == 1

    def test_exact_full_then_empty_page_terminates(self):
        # A page of exactly per_page items can't tell us it's the last, so the
        # connector asks again; an empty page then ends the walk.
        full_page = [_product(i) for i in range(1, 101)]
        transport = FakeTransport(responses=[full_page, []])
        records = _make_connector(transport).fetch_products()
        assert len(records) == 100
        assert len(transport.calls) == 2

    def test_no_products_yields_empty_list(self):
        transport = FakeTransport(responses=[[]])
        records = _make_connector(transport).fetch_products()
        assert records == []
        assert len(transport.calls) == 1


class TestPushDescription:
    def test_puts_to_correct_url_with_published_script(self):
        transport = FakeTransport()
        dual = DualScript(cirilica="Црна мајица", latinica="Crna majica")

        _make_connector(transport).push_description("42", dual)

        assert len(transport.calls) == 1
        call = transport.calls[0]
        assert call["method"] == "PUT"
        assert call["url"] == "https://shop.example.com/wp-json/wc/v3/products/42"
        # Default publish script is LATINICA.
        assert call["json"]["description"] == "Crna majica"

    def test_default_publish_script_is_latinica(self):
        transport = FakeTransport()
        dual = DualScript(cirilica="Ћирилица", latinica="Latinica")
        _make_connector(transport).push_description("1", dual)
        assert transport.calls[0]["json"]["description"] == "Latinica"

    def test_explicit_cirilica_is_published(self):
        transport = FakeTransport()
        dual = DualScript(cirilica="Ћирилица", latinica="Latinica")
        _make_connector(transport).push_description(
            "1", dual, publish_script=Script.CIRILICA
        )
        assert transport.calls[0]["json"]["description"] == "Ћирилица"

    def test_alternate_script_is_persisted_in_meta(self):
        transport = FakeTransport()
        dual = DualScript(cirilica="Црна мајица", latinica="Crna majica")
        # Publish latinica -> the cirilica rendering must survive in meta_data.
        _make_connector(transport).push_description("1", dual)
        meta = transport.calls[0]["json"]["meta_data"]
        assert any(entry["value"] == "Црна мајица" for entry in meta)

    def test_returns_none(self):
        transport = FakeTransport()
        dual = DualScript(cirilica="a", latinica="a")
        result = _make_connector(transport).push_description("1", dual)
        assert result is None


class TestDefaultTransportAuth:
    def test_basic_auth_header_encodes_key_and_secret(self):
        header = _basic_auth_header("ck_abc", "cs_xyz")
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode("ascii")
        assert decoded == "ck_abc:cs_xyz"

    def test_default_transport_stores_auth_header(self):
        # Constructed without sending anything: we only assert the header the
        # transport would attach, so the test needs no network.
        transport = _UrllibTransport("ck_abc", "cs_xyz")
        assert transport._auth_header == _basic_auth_header("ck_abc", "cs_xyz")

    def test_connector_builds_default_transport_when_none(self):
        # transport=None must construct the stdlib default rather than leave it
        # unset (so a real run has a working transport).
        connector = WooCommerceConnector(
            "https://shop.example.com", "ck_abc", "cs_xyz"
        )
        assert isinstance(connector._transport, _UrllibTransport)
