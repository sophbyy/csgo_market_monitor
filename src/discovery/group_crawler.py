from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

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

_GROUP_XML_URL = "https://steamcommunity.com/groups/{group_name}/memberslistxml/?xml=1&p={page}"
_GROUP_URL_PATTERN = re.compile(
    r"(?:https?://)?steamcommunity\.com/groups/([^/?\s]+)"
)


@dataclass(frozen=True)
class GroupMember:
    steamid64: str
    profile_url: str


@dataclass(frozen=True)
class GroupInfo:
    group_name: str
    member_count: int
    total_pages: int


class GroupCrawler:
    """Crawl Steam Community group member lists via the XML API."""

    def __init__(
        self,
        session: requests.Session,
        *,
        delay_seconds: float = 2.0,
        max_pages: int | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._session = session
        self._delay = delay_seconds
        self._max_pages = max_pages
        self._limiter = rate_limiter

    def parse_group_identifier(self, raw: str) -> str:
        """Extract group name from a URL or return raw string as-is."""
        match = _GROUP_URL_PATTERN.search(raw)
        if match:
            return match.group(1)
        return raw.strip().lower()

    def get_group_info(self, group_name: str) -> GroupInfo | None:
        """Fetch first page to get group metadata."""
        html = self._fetch_page(group_name, 1)
        if html is None:
            return None
        root = self._parse_xml(html)
        if root is None:
            return None
        member_count = int(root.findtext("memberCount", "0").replace(",", ""))
        total_pages = int(root.findtext("totalPages", "1"))
        return GroupInfo(
            group_name=group_name,
            member_count=member_count,
            total_pages=total_pages,
        )

    def crawl(
        self, group_identifier: str, *, start_page: int = 1
    ) -> Iterator[list[GroupMember]]:
        """Yield pages of group members as lists of GroupMember.

        Each yield corresponds to one XML page (~1000 members).
        """
        group_name = self.parse_group_identifier(group_identifier)

        # Fetch first page to get total_pages
        xml_text = self._fetch_page(group_name, start_page)
        if xml_text is None:
            logger.error("Failed to fetch group '%s' page %d", group_name, start_page)
            return

        root = self._parse_xml(xml_text)
        if root is None:
            return

        total_pages = int(root.findtext("totalPages", "1"))
        member_count = root.findtext("memberCount", "?")
        logger.info(
            "Group '%s': %s members, %d pages. Starting from page %d.",
            group_name, member_count, total_pages, start_page,
        )

        # Determine how many pages to crawl
        end_page = total_pages
        if self._max_pages is not None:
            end_page = min(total_pages, start_page + self._max_pages - 1)

        # Process first page
        members = self._extract_members(root)
        if members:
            yield members

        # Process remaining pages
        for page in range(start_page + 1, end_page + 1):
            if self._limiter is not None:
                self._limiter.wait("community")
            else:
                time.sleep(self._delay)
            xml_text = self._fetch_page(group_name, page)
            if xml_text is None:
                logger.warning("Failed to fetch page %d of group '%s'. Stopping.", page, group_name)
                break
            root = self._parse_xml(xml_text)
            if root is None:
                break
            members = self._extract_members(root)
            if members:
                yield members
            logger.info("  Crawled page %d/%d (%d members)", page, end_page, len(members))

    @retry(
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _fetch_page(self, group_name: str, page: int) -> str | None:
        """Fetch a single XML page of group members."""
        url = _GROUP_XML_URL.format(group_name=group_name, page=page)
        try:
            response = self._session.get(url, timeout=30)
        except requests.RequestException:
            logger.warning("Network error fetching group page: %s p=%d", group_name, page)
            raise

        if response.status_code == 429:
            logger.warning("Rate-limited on group page %s p=%d", group_name, page)
            raise requests.exceptions.HTTPError(
                f"HTTP 429 for group {group_name} page {page}",
                response=response,
            )

        if response.status_code != 200:
            logger.warning(
                "HTTP %d fetching group %s page %d",
                response.status_code, group_name, page,
            )
            return None

        return response.text

    def _parse_xml(self, xml_text: str) -> ET.Element | None:
        """Parse XML text into an ElementTree root, or None on error."""
        try:
            return ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning("Failed to parse XML response from Steam group.")
            return None

    def _extract_members(self, root: ET.Element) -> list[GroupMember]:
        """Extract GroupMember list from parsed XML root."""
        members_el = root.find("members")
        if members_el is None:
            return []
        result = []
        for steamid_el in members_el.findall("steamID64"):
            steamid = steamid_el.text
            if steamid and steamid.strip():
                steamid = steamid.strip()
                result.append(GroupMember(
                    steamid64=steamid,
                    profile_url=f"https://steamcommunity.com/profiles/{steamid}",
                ))
        return result
