"""Tests for src.steam.inventory_value — currency parsing, inventory fetching, price lookup."""

from unittest.mock import MagicMock, patch

import requests

from src.steam.inventory_value import (
    fetch_inventory_items,
    fetch_item_price,
    parse_currency_value,
)


# -----------------------------------------------------------------------
# parse_currency_value
# -----------------------------------------------------------------------

class TestParseCurrencyValue:

    def test_dollar_with_commas(self):
        assert parse_currency_value("$1,234.56") == 1234.56

    def test_small_value(self):
        assert parse_currency_value("$0.03") == 0.03

    def test_plain_integer(self):
        assert parse_currency_value("1234") == 1234.0

    def test_value_without_dollar_sign(self):
        assert parse_currency_value("567.89") == 567.89

    def test_value_with_spaces(self):
        assert parse_currency_value("$ 1 234.56") == 1234.56

    def test_empty_string_returns_none(self):
        assert parse_currency_value("") is None

    def test_no_digits_returns_none(self):
        assert parse_currency_value("abc") is None

    def test_just_dollar_sign_returns_none(self):
        assert parse_currency_value("$") is None

    def test_large_value(self):
        assert parse_currency_value("$99,999.99") == 99999.99

    def test_zero(self):
        assert parse_currency_value("$0.00") == 0.0

    def test_no_decimal(self):
        assert parse_currency_value("$500") == 500.0


# -----------------------------------------------------------------------
# fetch_inventory_items
# -----------------------------------------------------------------------

class TestFetchInventoryItems:

    def _make_session(self, status_code=200, json_data=None, raise_exc=None):
        session = MagicMock(spec=requests.Session)
        if raise_exc:
            session.get.side_effect = raise_exc
        else:
            response = MagicMock()
            response.status_code = status_code
            response.json.return_value = json_data
            session.get.return_value = response
        return session

    def test_successful_inventory_parsing(self):
        json_data = {
            "assets": [
                {"classid": "1", "instanceid": "0", "amount": "2"},
                {"classid": "2", "instanceid": "0", "amount": "1"},
            ],
            "descriptions": [
                {"classid": "1", "instanceid": "0", "market_hash_name": "AK-47 | Redline (Field-Tested)"},
                {"classid": "2", "instanceid": "0", "market_hash_name": "AWP | Asiimov (Field-Tested)"},
            ],
        }
        session = self._make_session(json_data=json_data)
        result = fetch_inventory_items(session, "76561198000000000")

        assert len(result) == 2
        names = {item["market_hash_name"] for item in result}
        assert "AK-47 | Redline (Field-Tested)" in names
        assert "AWP | Asiimov (Field-Tested)" in names

    def test_amounts_aggregated_for_same_item(self):
        json_data = {
            "assets": [
                {"classid": "1", "instanceid": "0", "amount": "3"},
                {"classid": "1", "instanceid": "0", "amount": "2"},
            ],
            "descriptions": [
                {"classid": "1", "instanceid": "0", "market_hash_name": "Sticker | Natus Vincere"},
            ],
        }
        session = self._make_session(json_data=json_data)
        result = fetch_inventory_items(session, "76561198000000000")

        assert len(result) == 1
        assert result[0]["amount"] == 5

    def test_private_inventory_returns_empty(self):
        session = self._make_session(status_code=403)
        result = fetch_inventory_items(session, "76561198000000000")
        assert result == []

    def test_rate_limited_returns_empty(self):
        session = self._make_session(status_code=429)
        result = fetch_inventory_items(session, "76561198000000000")
        assert result == []

    def test_unexpected_status_returns_empty(self):
        session = self._make_session(status_code=500)
        result = fetch_inventory_items(session, "76561198000000000")
        assert result == []

    def test_network_error_returns_empty(self):
        session = self._make_session(raise_exc=requests.ConnectionError("timeout"))
        result = fetch_inventory_items(session, "76561198000000000")
        assert result == []

    def test_invalid_json_returns_empty(self):
        session = MagicMock(spec=requests.Session)
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = ValueError("No JSON")
        session.get.return_value = response
        result = fetch_inventory_items(session, "76561198000000000")
        assert result == []

    def test_empty_assets_returns_empty(self):
        json_data = {"assets": [], "descriptions": []}
        session = self._make_session(json_data=json_data)
        result = fetch_inventory_items(session, "76561198000000000")
        assert result == []

    def test_non_dict_json_returns_empty(self):
        session = self._make_session(json_data=["not", "a", "dict"])
        result = fetch_inventory_items(session, "76561198000000000")
        assert result == []


# -----------------------------------------------------------------------
# fetch_item_price
# -----------------------------------------------------------------------

class TestFetchItemPrice:

    def _make_session(self, status_code=200, json_data=None, raise_exc=None):
        session = MagicMock(spec=requests.Session)
        if raise_exc:
            session.get.side_effect = raise_exc
        else:
            response = MagicMock()
            response.status_code = status_code
            response.json.return_value = json_data
            session.get.return_value = response
        return session

    def test_returns_median_price(self):
        json_data = {
            "success": True,
            "median_price": "$12.34",
            "lowest_price": "$10.00",
        }
        session = self._make_session(json_data=json_data)
        price = fetch_item_price(session, "AK-47 | Redline (Field-Tested)")
        assert price == 12.34

    def test_falls_back_to_lowest_price(self):
        json_data = {
            "success": True,
            "lowest_price": "$8.50",
        }
        session = self._make_session(json_data=json_data)
        price = fetch_item_price(session, "AK-47 | Redline (Field-Tested)")
        assert price == 8.50

    def test_no_price_fields_returns_none(self):
        json_data = {"success": True}
        session = self._make_session(json_data=json_data)
        price = fetch_item_price(session, "SomeItem")
        assert price is None

    def test_success_false_returns_none(self):
        json_data = {"success": False}
        session = self._make_session(json_data=json_data)
        price = fetch_item_price(session, "SomeItem")
        assert price is None

    def test_rate_limited_raises_after_retries(self):
        session = self._make_session(status_code=429)
        from src.steam.inventory_value import _RateLimitedError
        import pytest
        with pytest.raises(_RateLimitedError):
            fetch_item_price(session, "SomeItem")

    def test_non_200_returns_none(self):
        session = self._make_session(status_code=500)
        price = fetch_item_price(session, "SomeItem")
        assert price is None

    def test_network_error_returns_none(self):
        session = self._make_session(raise_exc=requests.Timeout("timeout"))
        price = fetch_item_price(session, "SomeItem")
        assert price is None

    def test_invalid_json_returns_none(self):
        session = MagicMock(spec=requests.Session)
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = ValueError("bad json")
        session.get.return_value = response
        price = fetch_item_price(session, "SomeItem")
        assert price is None

    def test_non_dict_response_returns_none(self):
        session = self._make_session(json_data="not a dict")
        price = fetch_item_price(session, "SomeItem")
        assert price is None
