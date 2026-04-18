"""Tests for main.py — URL parsing and playtime helper."""

import pytest

from main import compute_total_playtime_hours, parse_profile_url


# -----------------------------------------------------------------------
# parse_profile_url
# -----------------------------------------------------------------------

class TestParseProfileUrl:

    def test_vanity_url(self):
        url_type, identifier = parse_profile_url(
            "https://steamcommunity.com/id/maraantonov"
        )
        assert url_type == "vanity"
        assert identifier == "maraantonov"

    def test_steamid64_url(self):
        url_type, identifier = parse_profile_url(
            "https://steamcommunity.com/profiles/76561198000000000"
        )
        assert url_type == "steamid64"
        assert identifier == "76561198000000000"

    def test_vanity_url_with_trailing_slash(self):
        url_type, identifier = parse_profile_url(
            "https://steamcommunity.com/id/testuser/"
        )
        assert url_type == "vanity"
        assert identifier == "testuser"

    def test_http_url(self):
        url_type, identifier = parse_profile_url(
            "http://steamcommunity.com/id/testuser"
        )
        assert url_type == "vanity"
        assert identifier == "testuser"

    def test_url_with_query_params(self):
        url_type, identifier = parse_profile_url(
            "https://steamcommunity.com/id/testuser?ref=abc"
        )
        assert url_type == "vanity"
        assert identifier == "testuser"

    def test_invalid_url_raises_value_error(self):
        with pytest.raises(ValueError, match="Unrecognised"):
            parse_profile_url("https://example.com/not-steam")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_profile_url("")

    def test_garbage_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_profile_url("not a url at all")

    def test_steamcommunity_without_profile_path_raises(self):
        with pytest.raises(ValueError):
            parse_profile_url("https://steamcommunity.com/market/listings")

    def test_url_embedded_in_text(self):
        """The regex uses search(), so it should find URLs in surrounding text."""
        url_type, identifier = parse_profile_url(
            "Check out https://steamcommunity.com/id/maraantonov please"
        )
        assert url_type == "vanity"
        assert identifier == "maraantonov"


# -----------------------------------------------------------------------
# compute_total_playtime_hours
# -----------------------------------------------------------------------

class TestComputeTotalPlaytimeHours:

    def test_single_game(self):
        resp = {"response": {"games": [{"playtime_forever": 120}]}}
        assert compute_total_playtime_hours(resp) == 2.0

    def test_multiple_games(self):
        resp = {
            "response": {
                "games": [
                    {"playtime_forever": 60},
                    {"playtime_forever": 90},
                    {"playtime_forever": 30},
                ]
            }
        }
        assert compute_total_playtime_hours(resp) == 3.0

    def test_zero_playtime(self):
        resp = {"response": {"games": [{"playtime_forever": 0}]}}
        assert compute_total_playtime_hours(resp) == 0.0

    def test_missing_playtime_field_defaults_to_zero(self):
        resp = {"response": {"games": [{"appid": 730}]}}
        assert compute_total_playtime_hours(resp) == 0.0

    def test_empty_games_list_returns_none(self):
        resp = {"response": {"games": []}}
        assert compute_total_playtime_hours(resp) is None

    def test_no_games_key_returns_none(self):
        resp = {"response": {}}
        assert compute_total_playtime_hours(resp) is None

    def test_no_response_key_returns_none(self):
        resp = {}
        assert compute_total_playtime_hours(resp) is None

    def test_none_games_returns_none(self):
        resp = {"response": {"games": None}}
        assert compute_total_playtime_hours(resp) is None

    def test_rounds_to_two_decimals(self):
        resp = {"response": {"games": [{"playtime_forever": 7}]}}
        result = compute_total_playtime_hours(resp)
        assert result == 0.12  # 7 / 60 = 0.11666... -> rounds to 0.12

    def test_large_playtime(self):
        # 10000 hours = 600000 minutes
        resp = {"response": {"games": [{"playtime_forever": 600000}]}}
        assert compute_total_playtime_hours(resp) == 10000.0
