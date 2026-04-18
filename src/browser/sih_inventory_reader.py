from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

_CURRENCY_PATTERN = re.compile(r"([0-9][0-9,]*\.?[0-9]*)")

_INVENTORY_PAGE_URL = "https://steamcommunity.com/profiles/{steamid}/inventory/#730"

# Multiple candidate selectors for SIH's total value element.
# SIH is closed-source and may change DOM structure across versions.
# Try each in order; the first match wins.
_SIH_SELECTORS = [
    "#inventory_market_helper_total",
    ".sih-total-value",
    "#sih_inventory_value",
    "[data-sih-inventory-value]",
    ".inventory_market_helper_total",
]

# Broader fallback: search for elements that look like SIH injected price totals
_SIH_FALLBACK_XPATH = (
    "//div[contains(@id, 'sih') or contains(@class, 'sih') "
    "or contains(@id, 'inventory_market_helper') "
    "or contains(@class, 'inventory_market_helper')]"
)


def _parse_currency(text: str) -> Optional[float]:
    """Extract numeric value from currency text like '$1,234.56'."""
    match = _CURRENCY_PATTERN.search(text.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


@dataclass(frozen=True)
class SihReadResult:
    value_usd: Optional[float]
    source: str  # "sih_dom", "sih_fallback", "sih_timeout", "sih_not_found", "sih_parse_error"


class SihInventoryReader:
    """Read inventory value from SIH-injected DOM elements."""

    def __init__(
        self,
        page: Page,
        *,
        navigation_timeout_ms: int = 30_000,
        sih_inject_timeout_ms: int = 20_000,
        poll_interval_ms: int = 2_000,
    ) -> None:
        self._page = page
        self._nav_timeout = navigation_timeout_ms
        self._sih_timeout = sih_inject_timeout_ms
        self._poll_interval = poll_interval_ms

    def read_value(self, steamid: str) -> SihReadResult:
        """Navigate to inventory page and read SIH total value."""
        url = _INVENTORY_PAGE_URL.format(steamid=steamid)

        # Navigate to inventory page
        try:
            self._page.goto(url, timeout=self._nav_timeout, wait_until="domcontentloaded")
        except Exception:
            logger.warning("Failed to navigate to inventory page for %s", steamid)
            return SihReadResult(value_usd=None, source="sih_navigation_error")

        # Wait for inventory to load (Steam's own loading)
        try:
            self._page.wait_for_selector(
                "#inventories, .inventory_page, .inventory_ctn",
                timeout=self._nav_timeout,
            )
        except Exception:
            logger.debug("Inventory container not found for %s", steamid)

        # Check if inventory is private
        privacy_el = self._page.query_selector(".profile_private_info")
        if privacy_el:
            logger.debug("Inventory is private for %s", steamid)
            return SihReadResult(value_usd=None, source="sih_private_inventory")

        # Poll for SIH-injected elements
        matched_selector = self._wait_for_sih_element()
        if matched_selector:
            value = self._extract_value(matched_selector)
            if value is not None:
                logger.info("SIH value for %s: $%.2f (selector: %s)", steamid, value, matched_selector)
                return SihReadResult(value_usd=value, source="sih_dom")
            return SihReadResult(value_usd=None, source="sih_parse_error")

        # Try fallback XPath search
        value = self._try_fallback_xpath()
        if value is not None:
            logger.info("SIH value for %s: $%.2f (fallback xpath)", steamid, value)
            return SihReadResult(value_usd=value, source="sih_fallback")

        logger.debug("SIH did not inject value element for %s within timeout", steamid)
        return SihReadResult(value_usd=None, source="sih_timeout")

    def _wait_for_sih_element(self) -> Optional[str]:
        """Poll for any known SIH selector. Returns matched selector or None."""
        elapsed = 0
        while elapsed < self._sih_timeout:
            for selector in _SIH_SELECTORS:
                element = self._page.query_selector(selector)
                if element:
                    return selector
            self._page.wait_for_timeout(self._poll_interval)
            elapsed += self._poll_interval
        return None

    def _extract_value(self, selector: str) -> Optional[float]:
        """Read text from matched element and parse as currency value."""
        element = self._page.query_selector(selector)
        if not element:
            return None
        try:
            text = element.inner_text()
        except Exception:
            return None
        return _parse_currency(text)

    def _try_fallback_xpath(self) -> Optional[float]:
        """Search for SIH elements via broad XPath as last resort."""
        try:
            elements = self._page.query_selector_all(f"xpath={_SIH_FALLBACK_XPATH}")
        except Exception:
            return None
        for el in elements:
            try:
                text = el.inner_text()
            except Exception:
                continue
            value = _parse_currency(text)
            if value is not None and value > 0:
                return value
        return None
