from __future__ import annotations

import logging
import random
import time
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DomainConfig:
    """Rate limit configuration for a specific domain/endpoint type."""
    min_delay: float  # minimum seconds between requests
    max_delay: float  # maximum seconds (jitter range)
    burst_size: int = 1  # how many requests before enforcing delay
    burst_window: float = 0.0  # seconds for burst window


class RateLimiter:
    """Centralized rate limiter with per-domain tracking and jitter.

    Domains:
    - "api": Steam Web API (api.steampowered.com) — generous limits, ~1 req/s
    - "community": Steam Community pages (steamcommunity.com) — group pages, profiles
    - "market": Steam Market price lookups — strictest limits, ~1 req/3s
    - "inventory": Steam inventory endpoint — very strict, ~1 req/2s
    - "profile": Full profile enrichment cycle — 5-9s between profiles
    """

    # Default configurations per domain
    _DEFAULTS: dict[str, DomainConfig] = {
        "api": DomainConfig(min_delay=0.25, max_delay=0.5),
        "community": DomainConfig(min_delay=2.0, max_delay=4.0),
        "market": DomainConfig(min_delay=1.0, max_delay=2.0),
        "inventory": DomainConfig(min_delay=2.0, max_delay=3.0),
        "profile": DomainConfig(min_delay=5.0, max_delay=9.0),
    }

    def __init__(self, overrides: dict[str, DomainConfig] | None = None) -> None:
        self._configs: dict[str, DomainConfig] = dict(self._DEFAULTS)
        if overrides:
            self._configs.update(overrides)
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str = "api") -> float:
        """Wait the appropriate amount of time for the given domain.

        Returns the actual delay in seconds (0.0 if no wait was needed).
        """
        config = self._configs.get(domain)
        if config is None:
            return 0.0

        with self._lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            elapsed = now - last

            # Calculate target delay with jitter
            target_delay = random.uniform(config.min_delay, config.max_delay)

            # If enough time already passed, no wait needed
            remaining = target_delay - elapsed
            if remaining <= 0:
                self._last_request[domain] = time.monotonic()
                return 0.0

        # Sleep outside the lock
        time.sleep(remaining)
        with self._lock:
            self._last_request[domain] = time.monotonic()

        logger.debug("Rate limiter: waited %.2fs for domain '%s'", remaining, domain)
        return remaining

    def reset(self, domain: str | None = None) -> None:
        """Reset timing for a domain, or all domains if None."""
        with self._lock:
            if domain:
                self._last_request.pop(domain, None)
            else:
                self._last_request.clear()
