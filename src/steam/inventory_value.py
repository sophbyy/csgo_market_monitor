from __future__ import annotations

import logging
import re
import time
from collections import Counter
from typing import TYPE_CHECKING, Optional


import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from src.storage.cache import FileCache

if TYPE_CHECKING:
    from src.rate_limiter import RateLimiter


class _RateLimitedError(Exception):
    """Raised when the Steam Market returns HTTP 429."""

logger = logging.getLogger(__name__)

_CURRENCY_PATTERN = re.compile(r"([0-9][0-9,]*\.?[0-9]*)")

# Steam inventory endpoint is heavily rate-limited.  Requests that arrive too
# quickly receive HTTP 429 responses.  Keep a generous delay between price
# lookups (~1 s) and between inventory fetches (~2 s) to avoid being blocked.

_PRICE_LOOKUP_DELAY: float = 1.0
_INVENTORY_URL = "https://steamcommunity.com/inventory/{steamid}/730/2" # TODO: verify this is the correct endpoint
_PRICE_URL = "https://steamcommunity.com/market/priceoverview/" # TODO: verify this is the correct endpoint

# _INVENTORY_URL = "http://steamcommunity.com/profiles/{steamid}/inventory/json/753/6"


def parse_currency_value(text: str) -> Optional[float]:
    """Extract a numeric value from a currency string like ``$1,234.56``."""
    match = _CURRENCY_PATTERN.search(text.replace(" ", ""))
    if not match:
        return None
    return float(match.group(1).replace(",", ""))



class _InventoryRateLimitedError(Exception):
    """Raised when the inventory endpoint returns 403 or 429 (rate-limited)."""


_MAX_INVENTORY_RETRIES = 3
_INVENTORY_RETRY_DELAY = 5.0  # seconds between retries


def fetch_inventory_items(
    session: requests.Session,
    steamid: str,
    rate_limiter: RateLimiter | None = None,
) -> list[dict]:
    """Fetch CS2/CS:GO inventory items for *steamid* via the community endpoint.

    Returns a list of dicts, each containing:
    - ``market_hash_name``: the market hash name of the item
    - ``amount``: quantity of that item in the inventory

    Returns an empty list when the profile is private, the inventory is
    inaccessible, or an unexpected error occurs.

    Retries on HTTP 403/429 since the Steam inventory endpoint uses 403
    for both private inventories AND rate limiting.
    """
    url = _INVENTORY_URL.format(steamid=steamid)
    params = {"l": "english", "count": "5000"}

    for attempt in range(_MAX_INVENTORY_RETRIES):
        if rate_limiter is not None:
            rate_limiter.wait("inventory")

        try:
            response = session.get(url, params=params, timeout=30)
        except requests.RequestException:
            logger.warning("Network error fetching inventory for %s", steamid)
            return []

        if response.status_code == 200:
            break

        if response.status_code in (403, 429):
            if attempt < _MAX_INVENTORY_RETRIES - 1:
                logger.info(
                    "Inventory HTTP %d for %s, retrying in %.0fs (attempt %d/%d)",
                    response.status_code, steamid,
                    _INVENTORY_RETRY_DELAY, attempt + 1, _MAX_INVENTORY_RETRIES,
                )
                time.sleep(_INVENTORY_RETRY_DELAY)
                continue
            # Final attempt still failed — likely genuinely private
            logger.debug("Inventory inaccessible for %s after %d attempts", steamid, _MAX_INVENTORY_RETRIES)
            return []

        logger.warning(
            "Unexpected status %d fetching inventory for %s",
            response.status_code,
            steamid,
        )
        return []
    else:
        return []

    try:
        data = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        logger.warning("Invalid JSON in inventory response for %s", steamid)
        return []

    if not isinstance(data, dict):
        return []

    assets = data.get("assets", [])
    descriptions = data.get("descriptions", [])

    if not assets or not descriptions:
        return []

    # Build a lookup: (classid, instanceid) -> description
    desc_lookup: dict[tuple[str, str], dict] = {}
    for desc in descriptions:
        key = (desc.get("classid", ""), desc.get("instanceid", ""))
        desc_lookup[key] = desc

    # Count items by market_hash_name
    name_counts: Counter[str] = Counter()
    for asset in assets:
        key = (asset.get("classid", ""), asset.get("instanceid", ""))
        desc = desc_lookup.get(key)
        if desc is None:
            continue
        name = desc.get("market_hash_name")
        if not name:
            continue
        # Each asset entry has an "amount" field (usually "1" as a string)
        try:
            amount = int(asset.get("amount", 1))
        except (ValueError, TypeError):
            amount = 1
        name_counts[name] += amount

    return [
        {"market_hash_name": name, "amount": count}
        for name, count in name_counts.items()
    ]


@retry(
    wait=wait_fixed(3),
    stop=stop_after_attempt(2),
    retry=retry_if_exception_type(_RateLimitedError),
    reraise=True,
)
def fetch_item_price(
    session: requests.Session,
    market_hash_name: str,
    rate_limiter: RateLimiter | None = None,
) -> Optional[float]:
    """Look up the current market price for a single item.

    Returns the price in USD or ``None`` if the item is not marketable or the
    request fails.  Prefers ``median_price``; falls back to ``lowest_price``.
    """
    params = {
        "appid": "730",
        "currency": "1",  # USD
        "market_hash_name": market_hash_name,
    }

    if rate_limiter is not None:
        rate_limiter.wait("market")

    try:
        response = session.get(_PRICE_URL, params=params, timeout=30)
    except requests.RequestException:
        logger.warning("Network error fetching price for %s", market_hash_name)
        return None

    if response.status_code == 429:
        logger.warning("Rate-limited while fetching price for %s. Retrying.", market_hash_name)
        raise _RateLimitedError(f"HTTP 429 for {market_hash_name}")

    if response.status_code != 200:
        logger.debug(
            "Status %d fetching price for %s",
            response.status_code,
            market_hash_name,
        )
        return None

    try:
        data = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        return None

    if not isinstance(data, dict) or not data.get("success"):
        return None

    # Prefer median_price, fall back to lowest_price
    price_text = data.get("median_price") or data.get("lowest_price")
    if not price_text:
        return None

    return parse_currency_value(price_text)


def calculate_inventory_value(
    session: requests.Session,
    steamid: str,
    cache: Optional[FileCache] = None,
    rate_limiter: RateLimiter | None = None,
) -> Optional[float]:
    """Calculate the total CS2/CS:GO inventory value for *steamid*.

    Fetches the inventory, looks up prices on the Steam Market, and sums up
    the total.  A :class:`FileCache` can be provided to persist price lookups
    across runs and avoid redundant requests.

    Returns the total value in USD, or ``None`` if the inventory is
    inaccessible (private profile, rate-limited, etc.).
    """
    items = fetch_inventory_items(session, steamid, rate_limiter=rate_limiter)
    if not items:
        return None

    total: float = 0.0
    looked_up = 0

    for item in items:
        name: str = item["market_hash_name"]
        amount: int = item["amount"]

        # Try cache first
        price: Optional[float] = None
        cache_key = f"price:{name}"
        if cache is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                price = float(cached)

        if price is None:
            # Throttle between price lookups to avoid rate limiting.
            # fetch_item_price handles its own rate_limiter.wait("market"),
            # so we only sleep here as a fallback when no limiter is set.
            if looked_up > 0 and rate_limiter is None:
                time.sleep(_PRICE_LOOKUP_DELAY)

            try:
                price = fetch_item_price(session, name, rate_limiter=rate_limiter)
            except _RateLimitedError:
                logger.warning("Exhausted retries for price lookup: %s", name)
                price = None
            looked_up += 1

            if price is not None and cache is not None:
                cache.set(cache_key, price)

        if price is not None:
            total += price * amount

    return total
