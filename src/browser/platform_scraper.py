from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

STEAM_PROFILE_RE = re.compile(
    r"https?://steamcommunity\.com/(?:id|profiles)/[A-Za-z0-9_-]+"
)


class BasePlatformScraper(ABC):
    """Base class for CS:GO trading platform scrapers.

    Each subclass targets a specific marketplace and knows how to navigate
    its listing pages and extract Steam profile URLs belonging to the bot
    accounts that hold inventory items.
    """

    def __init__(self, page: Page, *, max_pages: int = 5) -> None:
        self.page = page
        self.max_pages = max_pages
        self._intercepted_urls: set[str] = set()

    @abstractmethod
    def extract_profile_urls(self) -> list[str]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _collect_steam_links(self) -> set[str]:
        """Extract Steam profile URLs from <a> hrefs on the current page."""
        links: set[str] = set()
        anchors = self.page.query_selector_all("a[href]")
        for anchor in anchors:
            href = anchor.get_attribute("href")
            if href and STEAM_PROFILE_RE.search(href):
                match = STEAM_PROFILE_RE.search(href)
                if match:
                    links.add(match.group(0))
        return links

    def _collect_from_page_content(self) -> set[str]:
        """Extract Steam profile URLs from the full page source.

        SPA frameworks often embed profile URLs in JavaScript data,
        inline JSON, or dynamically rendered HTML that isn't in <a> tags.
        """
        try:
            html = self.page.content()
        except Exception:
            logger.warning("Could not read page content")
            return set()
        return set(STEAM_PROFILE_RE.findall(html))

    def _collect_all(self) -> set[str]:
        """Combine all extraction methods."""
        links = self._collect_steam_links()
        links |= self._collect_from_page_content()
        links |= self._intercepted_urls
        return links

    def _start_response_interception(self) -> None:
        """Listen for network responses that may contain Steam profile URLs.

        Many SPAs load listing data via XHR/fetch.  Profile URLs embedded
        in API JSON responses won't be in the DOM at all.
        """
        def _on_response(response):
            try:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type or "text" in content_type:
                    body = response.text()
                    found = STEAM_PROFILE_RE.findall(body)
                    if found:
                        self._intercepted_urls.update(found)
                        logger.debug(
                            "Intercepted %d Steam URL(s) from %s",
                            len(found),
                            response.url[:80],
                        )
            except Exception:
                pass  # Some responses can't be read (e.g. redirects)

        self.page.on("response", _on_response)

    def _safe_goto(self, url: str, *, timeout: int = 30_000) -> bool:
        """Navigate to *url*, returning False on timeout or network error."""
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except PlaywrightTimeout:
            logger.warning("Timeout navigating to %s", url)
            return False
        except Exception:
            logger.exception("Failed to navigate to %s", url)
            return False

    def _wait_for_page_ready(self, *, extra_wait_ms: int = 5_000) -> None:
        """Wait for the SPA to finish rendering.

        Waits for network idle first, then an additional fixed delay
        to let client-side JS populate the DOM.
        """
        try:
            self.page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeout:
            logger.debug("networkidle timeout, proceeding anyway")
        self.page.wait_for_timeout(extra_wait_ms)

    def _click_next_page(self) -> bool:
        """Attempt to click a 'next page' pagination control.

        Tries several common selector patterns.
        """
        selectors = [
            "a.pagination-next", "a[rel='next']", ".next-page",
            "button.next", "li.next > a", "[aria-label='Next']",
            ".pagination__next", ".pager__next",
            "a:has-text('Next')", "button:has-text('Next')",
            "a:has-text('»')", "button:has-text('»')",
        ]
        for sel in selectors:
            btn = self.page.query_selector(sel)
            if btn and btn.is_visible():
                try:
                    btn.click()
                    self._wait_for_page_ready(extra_wait_ms=3_000)
                    return True
                except Exception:
                    continue
        return False

    def _scroll_to_load(self, scroll_count: int = 3) -> None:
        """Scroll down to trigger lazy-loading / infinite scroll."""
        for _ in range(scroll_count):
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self.page.wait_for_timeout(2_000)

    def _scrape_pages(self, label: str) -> list[str]:
        """Common multi-page scraping loop used by all scrapers."""
        collected: set[str] = set()

        for page_num in range(1, self.max_pages + 1):
            logger.info("%s: scraping page %d/%d", label, page_num, self.max_pages)

            # Scroll to trigger any lazy-loading
            self._scroll_to_load(scroll_count=2)

            links = self._collect_all()
            new_count = len(links - collected)
            collected.update(links)
            logger.info(
                "%s: found %d new profile(s) on page %d (total: %d)",
                label, new_count, page_num, len(collected),
            )

            if page_num >= self.max_pages:
                break

            if not self._click_next_page():
                logger.info("%s: no more pages available", label)
                break

        logger.info("%s: finished with %d unique profile(s)", label, len(collected))
        return sorted(collected)


class MarketCsgoScraper(BasePlatformScraper):
    """Scraper for market.csgo.com."""

    BASE_URL = "https://market.csgo.com/en/"

    def extract_profile_urls(self) -> list[str]:
        self._start_response_interception()

        if not self._safe_goto(self.BASE_URL):
            return []

        self._wait_for_page_ready()
        return self._scrape_pages("MarketCsgoScraper")


class LisSkinsScraper(BasePlatformScraper):
    """Scraper for lis-skins.com."""

    BASE_URL = "https://lis-skins.com/"

    def extract_profile_urls(self) -> list[str]:
        self._start_response_interception()

        if not self._safe_goto(self.BASE_URL):
            return []

        self._wait_for_page_ready()
        return self._scrape_pages("LisSkinsScraper")


class AvanMarketScraper(BasePlatformScraper):
    """Scraper for avan.market."""

    BASE_URL = "https://avan.market/en/"

    def extract_profile_urls(self) -> list[str]:
        self._start_response_interception()

        if not self._safe_goto(self.BASE_URL):
            return []

        self._wait_for_page_ready()
        return self._scrape_pages("AvanMarketScraper")
