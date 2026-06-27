"""Tests for the TAU Commerce connector placeholder.

`TauCommerceConnector` is not a working integration (see its module
docstring): no public TAU Commerce API documentation exists, so every method
raises `NotImplementedError` rather than guessing at an API shape. These
tests cover exactly that contract — Protocol conformance, constructor
storage, and that both methods raise with a message naming "TAU Commerce" —
and nothing else, since there is no behaviour beyond that to exercise.
"""

from __future__ import annotations

import pytest

from connectors.base import Connector
from connectors.tau_commerce import TauCommerceConnector
from pipeline.types import DualScript, Script


def _make_connector(*, transport: object | None = None) -> TauCommerceConnector:
    return TauCommerceConnector(
        "https://shop.example.rs",
        "tau_test_key",
        transport=transport,
    )


class TestConnectorProtocol:
    def test_satisfies_connector_protocol(self):
        connector = _make_connector()
        # runtime_checkable Protocol: structural check only, so this holds
        # even though every method body raises.
        assert isinstance(connector, Connector)


class TestConstructorStoresArguments:
    def test_stores_base_url_and_api_key(self):
        connector = _make_connector()
        assert connector._base_url == "https://shop.example.rs"
        assert connector._api_key == "tau_test_key"

    def test_stores_optional_transport(self):
        sentinel = object()
        connector = _make_connector(transport=sentinel)
        assert connector._transport is sentinel

    def test_transport_defaults_to_none(self):
        connector = _make_connector()
        assert connector._transport is None


class TestFetchProductsRaises:
    def test_raises_not_implemented_error_naming_platform(self):
        connector = _make_connector()
        with pytest.raises(NotImplementedError, match="TAU Commerce"):
            connector.fetch_products()

    def test_error_names_the_method(self):
        connector = _make_connector()
        with pytest.raises(NotImplementedError, match="fetch_products"):
            connector.fetch_products()


class TestPushDescriptionRaises:
    def test_raises_not_implemented_error_naming_platform(self):
        connector = _make_connector()
        dual = DualScript(cirilica="Тест", latinica="Test")
        with pytest.raises(NotImplementedError, match="TAU Commerce"):
            connector.push_description("1", dual)

    def test_error_names_the_method(self):
        connector = _make_connector()
        dual = DualScript(cirilica="Тест", latinica="Test")
        with pytest.raises(NotImplementedError, match="push_description"):
            connector.push_description("1", dual, publish_script=Script.CIRILICA)
