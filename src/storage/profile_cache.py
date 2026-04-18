"""Profile-specific caching layer built on top of FileCache.

Provides two cache domains:
- **vanity -> steamid64** mappings (permanent; vanity URLs never change owner).
- **checked profile steamids** so re-runs can skip already-processed profiles.
"""

from __future__ import annotations

from typing import Optional

from src.storage.cache import FileCache

_DEFAULT_CACHE_PATH = ".cache/profiles.json"

# Keys used inside the single JSON file to separate domains.
_KEY_VANITY = "vanity_to_steamid"
_KEY_CHECKED = "checked_steamids"
_KEY_GROUP_PROGRESS = "group_progress"


class ProfileCache:
    """Thin wrapper around :class:`FileCache` for profile pipeline caching."""

    def __init__(self, path: str = _DEFAULT_CACHE_PATH) -> None:
        self._cache = FileCache(path)
        # Ensure top-level keys exist.
        if self._cache.get(_KEY_VANITY) is None:
            self._cache.set(_KEY_VANITY, {})
        if self._cache.get(_KEY_CHECKED) is None:
            self._cache.set(_KEY_CHECKED, [])
        if self._cache.get(_KEY_GROUP_PROGRESS) is None:
            self._cache.set(_KEY_GROUP_PROGRESS, {})

    # ------------------------------------------------------------------
    # Vanity URL -> SteamID64 resolution cache
    # ------------------------------------------------------------------

    def get_steamid(self, vanity: str) -> Optional[str]:
        """Return cached steamid64 for *vanity*, or ``None`` if not cached."""
        mapping: dict[str, str] = self._cache.get(_KEY_VANITY) or {}
        return mapping.get(vanity.lower())

    def set_steamid(self, vanity: str, steamid: str) -> None:
        """Permanently cache the *vanity* -> *steamid* mapping."""
        mapping: dict[str, str] = self._cache.get(_KEY_VANITY) or {}
        mapping[vanity.lower()] = steamid
        self._cache.set(_KEY_VANITY, mapping)

    # ------------------------------------------------------------------
    # Already-checked profile tracking
    # ------------------------------------------------------------------

    def is_checked(self, steamid: str) -> bool:
        """Return ``True`` if *steamid* has already been processed."""
        checked: list[str] = self._cache.get(_KEY_CHECKED) or []
        return steamid in set(checked)

    def mark_checked(self, steamid: str) -> None:
        """Record that *steamid* has been fully processed."""
        checked: list[str] = self._cache.get(_KEY_CHECKED) or []
        checked_set = set(checked)
        if steamid not in checked_set:
            checked.append(steamid)
            self._cache.set(_KEY_CHECKED, checked)

    # ------------------------------------------------------------------
    # Group crawl progress tracking
    # ------------------------------------------------------------------

    def get_group_last_page(self, group_name: str) -> int:
        """Return the last fully-processed page number for *group_name*, or 0."""
        progress = self._cache.get(_KEY_GROUP_PROGRESS) or {}
        return progress.get(group_name.lower(), 0)

    def set_group_last_page(self, group_name: str, page: int) -> None:
        """Record that *page* was the last fully-processed page for *group_name*."""
        progress = self._cache.get(_KEY_GROUP_PROGRESS) or {}
        progress[group_name.lower()] = page
        self._cache.set(_KEY_GROUP_PROGRESS, progress)
