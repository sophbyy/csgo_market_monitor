from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.pipeline.evaluator import EvaluationResult, ProfileData


def _format_logoff(timestamp: Optional[int]) -> str:
    """Convert a Unix timestamp to an ISO 8601 UTC string, or empty if None."""
    if timestamp is None:
        return ""
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OSError, ValueError):
        return ""


CSV_HEADERS = [
    "steam_id",
    "profile_url",
    "nickname",
    "steam_level",
    "vac_banned",
    "last_logoff_utc",
    "days_since_active",
    "total_playtime_hours",
    "inventory_value_usd",
    "source_platform",
    "name_pattern_match",
    "name_pattern_confidence",
    "collected_at_utc",
]


def write_csv_row(
    output_path: str,
    profile: ProfileData,
    evaluation: EvaluationResult,
    collected_at_utc: str,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "steam_id": profile.steam_id,
                "profile_url": profile.profile_url,
                "nickname": profile.nickname,
                "steam_level": profile.steam_level,
                "vac_banned": profile.vac_banned,
                "last_logoff_utc": _format_logoff(profile.last_logoff),
                "days_since_active": evaluation.days_since_active,
                "total_playtime_hours": profile.total_playtime_hours,
                "inventory_value_usd": profile.inventory_value_usd,
                "source_platform": profile.source_platform,
                "name_pattern_match": profile.name_pattern_match,
                "name_pattern_confidence": profile.name_pattern_confidence,
                "collected_at_utc": collected_at_utc,
            }
        )

