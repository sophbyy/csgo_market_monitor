from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.browser.sih_inventory_reader import (
    SihInventoryReader,
    SihReadResult,
    _parse_currency,
)


class TestParseCurrency:
    def test_simple_value(self):
        assert _parse_currency("$1234.56") == 1234.56

    def test_with_commas(self):
        assert _parse_currency("$1,234.56") == 1234.56

    def test_no_decimal(self):
        assert _parse_currency("$500") == 500.0

    def test_no_match(self):
        assert _parse_currency("no value here") is None

    def test_with_spaces(self):
        assert _parse_currency("$ 1 234.56") == 1234.56

    def test_large_value(self):
        assert _parse_currency("$12,345,678.90") == 12345678.90


class TestSihInventoryReader:
    def _make_reader(self, page=None, **kwargs):
        if page is None:
            page = MagicMock()
        return SihInventoryReader(page, **kwargs)

    def test_navigation_error(self):
        page = MagicMock()
        page.goto.side_effect = Exception("timeout")
        reader = self._make_reader(page)
        result = reader.read_value("76561198000000001")
        assert result.value_usd is None
        assert result.source == "sih_navigation_error"

    def test_private_inventory(self):
        page = MagicMock()
        page.wait_for_selector.return_value = MagicMock()
        privacy_el = MagicMock()
        def query_selector_side_effect(sel):
            if sel == ".profile_private_info":
                return privacy_el
            return None
        page.query_selector.side_effect = query_selector_side_effect
        reader = self._make_reader(page, sih_inject_timeout_ms=100, poll_interval_ms=50)
        result = reader.read_value("76561198000000001")
        assert result.value_usd is None
        assert result.source == "sih_private_inventory"

    def test_sih_element_found(self):
        page = MagicMock()
        page.wait_for_selector.return_value = MagicMock()

        call_count = 0
        def query_selector_side_effect(sel):
            nonlocal call_count
            if sel == ".profile_private_info":
                return None
            # Return an element for the first SIH selector
            if sel == "#inventory_market_helper_total":
                call_count += 1
                el = MagicMock()
                el.inner_text.return_value = "$1,234.56"
                return el
            return None

        page.query_selector.side_effect = query_selector_side_effect
        reader = self._make_reader(page, sih_inject_timeout_ms=5000, poll_interval_ms=100)
        result = reader.read_value("76561198000000001")
        assert result.value_usd == 1234.56
        assert result.source == "sih_dom"

    def test_sih_timeout_no_element(self):
        page = MagicMock()
        page.wait_for_selector.return_value = MagicMock()
        page.query_selector.return_value = None
        page.query_selector_all.return_value = []

        reader = self._make_reader(
            page, sih_inject_timeout_ms=100, poll_interval_ms=50
        )
        result = reader.read_value("76561198000000001")
        assert result.value_usd is None
        assert result.source == "sih_timeout"

    def test_sih_parse_error(self):
        page = MagicMock()
        page.wait_for_selector.return_value = MagicMock()

        call_count = 0
        def query_selector_side_effect(sel):
            nonlocal call_count
            if sel == ".profile_private_info":
                return None
            if sel == "#inventory_market_helper_total":
                el = MagicMock()
                el.inner_text.return_value = "Loading..."
                return el
            return None

        page.query_selector.side_effect = query_selector_side_effect
        reader = self._make_reader(page, sih_inject_timeout_ms=5000, poll_interval_ms=100)
        result = reader.read_value("76561198000000001")
        assert result.value_usd is None
        assert result.source == "sih_parse_error"
