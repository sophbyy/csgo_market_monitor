from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterator

from src.discovery.group_crawler import GroupMember
from src.steam.client import SteamApiClient
from src.storage.profile_cache import ProfileCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrawlStats:
    seeds: int
    discovered: int
    depth_reached: int
    api_calls: int


class FriendCrawler:
    """BFS crawl of Steam friend networks to discover bot accounts."""

    def __init__(
        self,
        client: SteamApiClient,
        *,
        max_depth: int = 2,
        max_friends_per_profile: int = 100,
        delay_seconds: float = 1.0,
    ) -> None:
        self._client = client
        self._max_depth = max_depth
        self._max_friends = max_friends_per_profile
        self._delay = delay_seconds

    def crawl(
        self,
        seed_ids: list[str],
        profile_cache: ProfileCache | None = None,
    ) -> Iterator[list[GroupMember]]:
        """BFS crawl from seed SteamID64s, yielding batches of discovered members.

        Yields lists of ~100 members at a time for batch pre-filtering.
        Skips already-checked profiles (via profile_cache).
        """
        visited: set[str] = set()
        # Queue entries: (steamid64, depth)
        queue: deque[tuple[str, int]] = deque()

        # Add seeds to queue
        for sid in seed_ids:
            if sid not in visited:
                visited.add(sid)
                queue.append((sid, 0))

        batch: list[GroupMember] = []
        api_calls = 0
        max_depth_reached = 0

        while queue:
            steamid, depth = queue.popleft()

            if depth > self._max_depth:
                continue

            max_depth_reached = max(max_depth_reached, depth)

            # Fetch friend list
            if api_calls > 0:
                time.sleep(self._delay)

            try:
                resp = self._client.get_friend_list(steamid)
            except Exception:
                logger.debug("Could not fetch friends for %s", steamid)
                continue
            api_calls += 1

            friends_list = resp.get("friendslist", {}).get("friends", [])
            if not friends_list:
                logger.debug("No friends (or private) for %s", steamid)
                continue

            logger.info(
                "  Friends for %s: %d found (depth=%d)",
                steamid, len(friends_list), depth,
            )

            # Process friends
            added = 0
            for friend in friends_list:
                friend_id = friend.get("steamid", "")
                if not friend_id or friend_id in visited:
                    continue

                visited.add(friend_id)

                # Skip already-checked profiles
                if profile_cache is not None and profile_cache.is_checked(friend_id):
                    continue

                member = GroupMember(
                    steamid64=friend_id,
                    profile_url=f"https://steamcommunity.com/profiles/{friend_id}",
                )
                batch.append(member)
                added += 1

                # Add to BFS queue for next depth level
                if depth + 1 <= self._max_depth and added <= self._max_friends:
                    queue.append((friend_id, depth + 1))

                # Yield batch when it reaches 100
                if len(batch) >= 100:
                    yield batch
                    batch = []

        # Yield remaining batch
        if batch:
            yield batch

        logger.info(
            "Friend crawl complete: %d seeds, %d discovered, depth=%d, %d API calls",
            len(seed_ids), len(visited) - len(seed_ids), max_depth_reached, api_calls,
        )
