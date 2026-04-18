from __future__ import annotations

import time

from src.rate_limiter import DomainConfig, RateLimiter


class TestRateLimiter:
    def test_first_request_no_wait(self):
        limiter = RateLimiter()
        delay = limiter.wait("api")
        assert delay == 0.0

    def test_second_request_waits(self):
        limiter = RateLimiter(overrides={
            "test": DomainConfig(min_delay=0.1, max_delay=0.1),
        })
        limiter.wait("test")
        start = time.monotonic()
        limiter.wait("test")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05

    def test_unknown_domain_no_wait(self):
        limiter = RateLimiter()
        delay = limiter.wait("nonexistent")
        assert delay == 0.0

    def test_different_domains_independent(self):
        limiter = RateLimiter(overrides={
            "a": DomainConfig(min_delay=0.1, max_delay=0.1),
            "b": DomainConfig(min_delay=0.1, max_delay=0.1),
        })
        limiter.wait("a")
        delay = limiter.wait("b")
        assert delay == 0.0

    def test_reset_clears_timing(self):
        limiter = RateLimiter(overrides={
            "test": DomainConfig(min_delay=10.0, max_delay=10.0),
        })
        limiter.wait("test")
        limiter.reset("test")
        delay = limiter.wait("test")
        assert delay == 0.0

    def test_reset_all(self):
        limiter = RateLimiter()
        limiter.wait("api")
        limiter.wait("market")
        limiter.reset()
        delay = limiter.wait("api")
        assert delay == 0.0

    def test_default_domains_exist(self):
        limiter = RateLimiter()
        for domain in ["api", "community", "market", "inventory", "profile"]:
            assert domain in limiter._configs
