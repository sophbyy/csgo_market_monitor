from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.discovery.group_crawler import GroupMember
from src.pipeline.evaluator import compute_days_since
from src.steam.client import SteamApiClient
from src.storage.profile_cache import ProfileCache

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


@dataclass(frozen=True)
class PrefilterResult:
    steamid64: str
    profile_url: str
    nickname: str
    last_logoff: int | None
    vac_banned: bool
    passed: bool
    reject_reason: str


def batch_prefilter(
    client: SteamApiClient,
    members: list[GroupMember],
    profile_cache: ProfileCache | None = None,
) -> list[PrefilterResult]:
    """Batch-filter group members using Steam API batch endpoints.

    Quick rejection criteria (before expensive per-profile calls):
    - Already checked (via profile_cache)
    - Profile not public (communityvisibilitystate != 3)
    - Last logoff within 30 days (too recently active)

    Does NOT reject on level, playtime, or inventory (those need per-profile calls).
    """
    # Filter out already-checked profiles
    to_check = []
    for member in members:
        if profile_cache is not None and profile_cache.is_checked(member.steamid64):
            continue
        to_check.append(member)

    if not to_check:
        return []

    results: list[PrefilterResult] = []

    # Process in batches of 100
    for i in range(0, len(to_check), _BATCH_SIZE):
        batch = to_check[i : i + _BATCH_SIZE]
        steamids = [m.steamid64 for m in batch]
        member_lookup = {m.steamid64: m for m in batch}

        # Fetch summaries and bans in batch
        summaries_by_id: dict[str, dict] = {}
        bans_by_id: dict[str, dict] = {}

        try:
            summary_resp = client.get_player_summaries(steamids)
            for player in summary_resp.get("response", {}).get("players", []):
                summaries_by_id[player["steamid"]] = player
        except Exception:
            logger.exception("Failed to batch-fetch summaries for %d profiles", len(steamids))

        try:
            bans_resp = client.get_player_bans(steamids)
            for player in bans_resp.get("players", []):
                bans_by_id[player["SteamId"]] = player
        except Exception:
            logger.exception("Failed to batch-fetch bans for %d profiles", len(steamids))

        # Evaluate each member in the batch
        for steamid in steamids:
            member = member_lookup[steamid]
            summary = summaries_by_id.get(steamid)
            ban_info = bans_by_id.get(steamid)

            if summary is None:
                results.append(PrefilterResult(
                    steamid64=steamid,
                    profile_url=member.profile_url,
                    nickname="",
                    last_logoff=None,
                    vac_banned=False,
                    passed=False,
                    reject_reason="no_summary_data",
                ))
                continue

            nickname = summary.get("personaname", "")
            visibility = summary.get("communityvisibilitystate", 1)
            last_logoff = summary.get("lastlogoff")
            vac_banned = ban_info.get("VACBanned", False) if ban_info else False

            # Reject private profiles (can't evaluate inventory/games)
            if visibility != 3:
                results.append(PrefilterResult(
                    steamid64=steamid,
                    profile_url=member.profile_url,
                    nickname=nickname,
                    last_logoff=last_logoff,
                    vac_banned=vac_banned,
                    passed=False,
                    reject_reason="profile_not_public",
                ))
                continue

            # Reject recently active profiles
            days_since = compute_days_since(last_logoff)
            if days_since is not None and days_since < 30:
                results.append(PrefilterResult(
                    steamid64=steamid,
                    profile_url=member.profile_url,
                    nickname=nickname,
                    last_logoff=last_logoff,
                    vac_banned=vac_banned,
                    passed=False,
                    reject_reason="active_within_30_days",
                ))
                continue

            # Passed pre-filter
            results.append(PrefilterResult(
                steamid64=steamid,
                profile_url=member.profile_url,
                nickname=nickname,
                last_logoff=last_logoff,
                vac_banned=vac_banned,
                passed=True,
                reject_reason="",
            ))

    passed_count = sum(1 for r in results if r.passed)
    logger.info(
        "Pre-filter: %d/%d passed (checked %d, skipped %d already-checked)",
        passed_count, len(to_check), len(to_check), len(members) - len(to_check),
    )

    return results
