from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    from src.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


class SteamApiClient:
    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        self._limiter = rate_limiter

    @retry(
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get(self, interface: str, method: str, version: int, params: dict[str, Any]) -> dict:
        if self._limiter is not None:
            self._limiter.wait("api")
        url = f"https://api.steampowered.com/{interface}/{method}/v{version}/" # TODO: verify this is the correct endpoint
        base_params = {"key": self.api_key}
        response = self.session.get(url, params={**base_params, **params}, timeout=30)
        if response.status_code in _RETRYABLE_STATUS_CODES:
            logger.warning(
                "Retryable HTTP %d from %s/%s. Will retry.",
                response.status_code,
                interface,
                method,
            )
            raise requests.exceptions.HTTPError(
                f"HTTP {response.status_code}", response=response
            )
        response.raise_for_status()
        return response.json()

    def resolve_vanity_url(self, vanity: str) -> dict:
        return self._get("ISteamUser", "ResolveVanityURL", 1, {"vanityurl": vanity})

    def get_player_bans(self, steamids: list[str]) -> dict:
        return self._get("ISteamUser", "GetPlayerBans", 1, {"steamids": ",".join(steamids)})

    def get_player_summaries(self, steamids: list[str]) -> dict:
        return self._get("ISteamUser", "GetPlayerSummaries", 2, {"steamids": ",".join(steamids)})

    def get_steam_level(self, steamid: str) -> dict:
        return self._get("IPlayerService", "GetSteamLevel", 1, {"steamid": steamid})

    def get_owned_games(self, steamid: str) -> dict:
        return self._get(
            "IPlayerService",
            "GetOwnedGames",
            1,
            {"steamid": steamid, "include_played_free_games": 1},
        )

    def get_friend_list(self, steamid: str) -> dict:
        """Fetch the friend list for a Steam profile.

        Returns empty dict if the friend list is private or unavailable.
        The API returns {"friendslist": {"friends": [{"steamid": "...", "relationship": "friend", "friend_since": ...}, ...]}}
        """
        try:
            return self._get("ISteamUser", "GetFriendList", 1, {"steamid": steamid, "relationship": "friend"})
        except Exception:
            # Friend list is private or unavailable — return empty
            return {}

