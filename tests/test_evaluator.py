"""Tests for src.pipeline.evaluator — profile evaluation logic."""

import time
from datetime import datetime, timezone

from src.pipeline.evaluator import (
    EvaluationResult,
    ProfileData,
    compute_days_since,
    evaluate_profile,
)


# -----------------------------------------------------------------------
# Helper to build a ProfileData with sensible bot-like defaults
# -----------------------------------------------------------------------

def _make_profile(**overrides) -> ProfileData:
    """Create a ProfileData with defaults that pass all candidate criteria."""
    ninety_days_ago = int(
        (datetime.now(tz=timezone.utc)).timestamp() - 90 * 86400
    )
    defaults = dict(
        steam_id="76561198000000000",
        profile_url="https://steamcommunity.com/id/testuser",
        nickname="testuser",
        steam_level=3,
        vac_banned=False,
        last_logoff=ninety_days_ago,      # 90 days ago — passes the 30-day check
        total_playtime_hours=2.0,         # under 10 hours
        inventory_value_usd=1500.0,       # above $500
        source_platform="market.csgo.com",
        name_pattern_match="russian_name",
        name_pattern_confidence=0.9,
    )
    defaults.update(overrides)
    return ProfileData(**defaults)


# -----------------------------------------------------------------------
# evaluate_profile tests
# -----------------------------------------------------------------------

class TestEvaluateProfile:

    def test_ideal_bot_candidate_passes(self):
        """A profile meeting all criteria should be a candidate."""
        profile = _make_profile()
        result = evaluate_profile(profile)
        assert result.is_candidate is True
        assert result.reasons == []
        assert result.days_since_active is not None
        assert result.days_since_active >= 89  # ~90 days ago

    def test_level_above_10_rejected(self):
        profile = _make_profile(steam_level=15)
        result = evaluate_profile(profile)
        assert result.is_candidate is False
        assert "level_above_10" in result.reasons

    def test_level_exactly_10_passes(self):
        profile = _make_profile(steam_level=10)
        result = evaluate_profile(profile)
        assert "level_above_10" not in result.reasons

    def test_level_exactly_11_rejected(self):
        profile = _make_profile(steam_level=11)
        result = evaluate_profile(profile)
        assert "level_above_10" in result.reasons

    def test_inventory_below_500_rejected(self):
        profile = _make_profile(inventory_value_usd=250.0)
        result = evaluate_profile(profile)
        assert result.is_candidate is False
        assert "inventory_value_below_500" in result.reasons

    def test_inventory_exactly_500_passes(self):
        profile = _make_profile(inventory_value_usd=500.0)
        result = evaluate_profile(profile)
        assert "inventory_value_below_500" not in result.reasons

    def test_inventory_none_rejected_as_unknown(self):
        """Unknown inventory should be rejected — can't confirm ≥$500."""
        profile = _make_profile(inventory_value_usd=None)
        result = evaluate_profile(profile)
        assert result.is_candidate is False
        assert "inventory_unknown" in result.reasons
        assert "inventory_value_below_500" not in result.reasons

    def test_recent_activity_rejected(self):
        """Active within last 30 days should be rejected."""
        five_days_ago = int(datetime.now(tz=timezone.utc).timestamp() - 5 * 86400)
        profile = _make_profile(last_logoff=five_days_ago)
        result = evaluate_profile(profile)
        assert result.is_candidate is False
        assert "active_within_30_days" in result.reasons

    def test_activity_exactly_30_days_passes(self):
        """Exactly 30 days ago should pass (not < 30)."""
        thirty_days_ago = int(datetime.now(tz=timezone.utc).timestamp() - 30 * 86400)
        profile = _make_profile(last_logoff=thirty_days_ago)
        result = evaluate_profile(profile)
        assert "active_within_30_days" not in result.reasons

    def test_none_last_logoff_passes(self):
        """Unknown last_logoff should not trigger the activity rejection."""
        profile = _make_profile(last_logoff=None)
        result = evaluate_profile(profile)
        assert "active_within_30_days" not in result.reasons
        assert result.days_since_active is None

    def test_playtime_above_10_hours_rejected(self):
        profile = _make_profile(total_playtime_hours=15.0)
        result = evaluate_profile(profile)
        assert result.is_candidate is False
        assert "playtime_above_10_hours" in result.reasons

    def test_playtime_exactly_10_passes(self):
        profile = _make_profile(total_playtime_hours=10.0)
        result = evaluate_profile(profile)
        assert "playtime_above_10_hours" not in result.reasons

    def test_playtime_none_passes(self):
        """Unknown playtime should not trigger rejection."""
        profile = _make_profile(total_playtime_hours=None)
        result = evaluate_profile(profile)
        assert "playtime_above_10_hours" not in result.reasons

    def test_multiple_rejection_reasons(self):
        five_days_ago = int(datetime.now(tz=timezone.utc).timestamp() - 5 * 86400)
        profile = _make_profile(
            steam_level=20,
            inventory_value_usd=100.0,
            last_logoff=five_days_ago,
            total_playtime_hours=50.0,
        )
        result = evaluate_profile(profile)
        assert result.is_candidate is False
        assert len(result.reasons) == 4
        assert "level_above_10" in result.reasons
        assert "inventory_value_below_500" in result.reasons
        assert "active_within_30_days" in result.reasons
        assert "playtime_above_10_hours" in result.reasons


# -----------------------------------------------------------------------
# compute_days_since tests
# -----------------------------------------------------------------------

class TestComputeDaysSince:

    def test_none_returns_none(self):
        assert compute_days_since(None) is None

    def test_zero_returns_none(self):
        """0 is falsy, so compute_days_since should return None."""
        assert compute_days_since(0) is None

    def test_recent_timestamp(self):
        two_days_ago = int(datetime.now(tz=timezone.utc).timestamp() - 2 * 86400)
        result = compute_days_since(two_days_ago)
        assert result is not None
        assert result in (1, 2, 3)  # allow for rounding near midnight

    def test_old_timestamp(self):
        one_year_ago = int(datetime.now(tz=timezone.utc).timestamp() - 365 * 86400)
        result = compute_days_since(one_year_ago)
        assert result is not None
        assert 364 <= result <= 366

    def test_returns_integer(self):
        ts = int(datetime.now(tz=timezone.utc).timestamp() - 10 * 86400)
        result = compute_days_since(ts)
        assert isinstance(result, int)
