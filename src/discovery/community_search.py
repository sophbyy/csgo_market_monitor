from __future__ import annotations

import logging
import random
import re
import time
from typing import Iterator

from playwright.sync_api import Page

from src.discovery.group_crawler import GroupMember
from src.patterns import RUSSIAN_FIRST_NAMES, RUSSIAN_LAST_NAMES

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://steamcommunity.com/search/users/#text={query}"
_PROFILE_URL_PATTERN = re.compile(
    r"https?://steamcommunity\.com/(?:id|profiles)/([^/?\s\"']+)"
)


class CommunitySearcher:
    """Search Steam Community for profiles matching Russian name patterns."""

    def __init__(
        self,
        page: Page,
        *,
        delay_seconds: float = 5.0,
        max_results_per_query: int = 50,
    ) -> None:
        self._page = page
        self._delay = delay_seconds
        self._max_results = max_results_per_query

    def generate_queries(self, max_queries: int = 50) -> list[str]:
        """Generate search queries from Russian name combinations.

        Uses first+last name combinations from the patterns database.
        Returns a randomized subset to avoid predictable patterns.
        """
        first_list = sorted(RUSSIAN_FIRST_NAMES)
        last_list = sorted(RUSSIAN_LAST_NAMES)
        queries = []
        for first in first_list:
            for last in last_list:
                queries.append(f"{first}{last}")

        random.shuffle(queries)
        return queries[:max_queries]

    def search(
        self,
        queries: list[str] | None = None,
        max_queries: int = 50,
    ) -> Iterator[list[GroupMember]]:
        """Search Steam Community with generated or provided queries.

        Yields batches of discovered GroupMember objects.
        """
        if queries is None:
            queries = self.generate_queries(max_queries)

        logger.info("Community search: %d queries to run", len(queries))

        for i, query in enumerate(queries):
            logger.info("  Searching [%d/%d]: '%s'", i + 1, len(queries), query)

            members = self._search_query(query)
            if members:
                yield members

            if i < len(queries) - 1:
                # Add jitter to delay for natural behavior
                jitter = random.uniform(0.8, 1.2)
                time.sleep(self._delay * jitter)

    def _search_query(self, query: str) -> list[GroupMember]:
        """Execute a single search query and extract profile URLs."""
        url = _SEARCH_URL.format(query=query)

        try:
            self._page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        except Exception:
            logger.warning("Failed to navigate to search page for '%s'", query)
            return []

        # Wait for search results to load
        try:
            self._page.wait_for_selector(
                ".search_row, .searchPersonaName, .search_results_none",
                timeout=15_000,
            )
        except Exception:
            logger.debug("Search results did not load for '%s'", query)
            return []

        # Check for "no results"
        no_results = self._page.query_selector(".search_results_none")
        if no_results:
            logger.debug("No results for '%s'", query)
            return []

        # Extract profile links from search results
        content = self._page.content()
        urls = set(_PROFILE_URL_PATTERN.findall(content))

        members = []
        for identifier in urls:
            if identifier.isdigit() and len(identifier) > 10:
                members.append(GroupMember(
                    steamid64=identifier,
                    profile_url=f"https://steamcommunity.com/profiles/{identifier}",
                ))
            else:
                # Vanity URL — steamid64 will be resolved during enrichment
                members.append(GroupMember(
                    steamid64="",
                    profile_url=f"https://steamcommunity.com/id/{identifier}",
                ))

        logger.info("  Found %d profiles for '%s'", len(members), query)
        return members[:self._max_results]
