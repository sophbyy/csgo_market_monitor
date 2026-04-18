from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ProfileData:
    steam_id: str
    profile_url: str
    nickname: str
    steam_level: int
    vac_banned: bool
    last_logoff: Optional[int]
    total_playtime_hours: Optional[float]
    inventory_value_usd: Optional[float]
    source_platform: str
    name_pattern_match: str = ""
    name_pattern_confidence: float = 0.0


@dataclass
class EvaluationResult:
    is_candidate: bool
    days_since_active: Optional[int]
    reasons: list[str]


def compute_days_since(last_logoff: Optional[int]) -> Optional[int]:
    if not last_logoff:
        return None
    last_seen = datetime.fromtimestamp(last_logoff, tz=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - last_seen
    return delta.days


def evaluate_profile(profile: ProfileData) -> EvaluationResult:
    reasons: list[str] = []
    days_since_active = compute_days_since(profile.last_logoff)

    # Hard criteria — reject if violated
    if profile.steam_level > 10:
        reasons.append("level_above_10")
    if profile.inventory_value_usd is not None and profile.inventory_value_usd < 500:
        reasons.append("inventory_value_below_500")
    if days_since_active is not None and days_since_active < 30:
        reasons.append("active_within_30_days")
    if profile.total_playtime_hours is not None and profile.total_playtime_hours > 10:
        reasons.append("playtime_above_10_hours")

    # Require inventory value — this is the core bot indicator.
    # Without knowing inventory value we cannot confirm the ≥$500 criterion.
    if profile.inventory_value_usd is None:
        reasons.append("inventory_unknown")

    return EvaluationResult(is_candidate=not reasons, days_since_active=days_since_active, reasons=reasons)

