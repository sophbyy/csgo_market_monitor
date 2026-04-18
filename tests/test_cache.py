"""Tests for src.storage.cache and src.storage.profile_cache."""

import json
import threading

from src.storage.cache import FileCache
from src.storage.profile_cache import ProfileCache


# -----------------------------------------------------------------------
# FileCache
# -----------------------------------------------------------------------

class TestFileCache:

    def test_get_returns_none_for_missing_key(self, tmp_path):
        cache = FileCache(str(tmp_path / "cache.json"))
        assert cache.get("nonexistent") is None

    def test_set_and_get(self, tmp_path):
        cache = FileCache(str(tmp_path / "cache.json"))
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_set_overwrites_existing(self, tmp_path):
        cache = FileCache(str(tmp_path / "cache.json"))
        cache.set("key1", "old")
        cache.set("key1", "new")
        assert cache.get("key1") == "new"

    def test_persistence_to_disk(self, tmp_path):
        path = str(tmp_path / "cache.json")
        cache1 = FileCache(path)
        cache1.set("persisted_key", 42)

        # Create a new FileCache instance that loads from the same file
        cache2 = FileCache(path)
        assert cache2.get("persisted_key") == 42

    def test_stores_complex_values(self, tmp_path):
        cache = FileCache(str(tmp_path / "cache.json"))
        cache.set("nested", {"a": [1, 2, 3], "b": {"c": True}})
        result = cache.get("nested")
        assert result == {"a": [1, 2, 3], "b": {"c": True}}

    def test_creates_parent_directories(self, tmp_path):
        path = str(tmp_path / "sub" / "dir" / "cache.json")
        cache = FileCache(path)
        cache.set("key", "val")
        assert cache.get("key") == "val"

    def test_thread_safety_concurrent_writes(self, tmp_path):
        """Multiple threads writing concurrently should not corrupt the cache."""
        cache = FileCache(str(tmp_path / "cache.json"))
        errors = []

        def writer(thread_id):
            try:
                for i in range(20):
                    cache.set(f"thread_{thread_id}_key_{i}", i)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(tid,)) for tid in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

        # Verify all keys are present
        for tid in range(5):
            for i in range(20):
                assert cache.get(f"thread_{tid}_key_{i}") == i

    def test_load_empty_file_does_not_exist(self, tmp_path):
        """FileCache should start empty if the file doesn't exist."""
        cache = FileCache(str(tmp_path / "nonexistent.json"))
        assert cache.get("anything") is None


# -----------------------------------------------------------------------
# ProfileCache
# -----------------------------------------------------------------------

class TestProfileCache:

    def test_get_steamid_returns_none_when_uncached(self, tmp_path):
        cache = ProfileCache(str(tmp_path / "profiles.json"))
        assert cache.get_steamid("unknownvanity") is None

    def test_set_and_get_steamid(self, tmp_path):
        cache = ProfileCache(str(tmp_path / "profiles.json"))
        cache.set_steamid("maraantonov", "76561198000000001")
        assert cache.get_steamid("maraantonov") == "76561198000000001"

    def test_steamid_case_insensitive(self, tmp_path):
        cache = ProfileCache(str(tmp_path / "profiles.json"))
        cache.set_steamid("MaraAntonov", "76561198000000001")
        assert cache.get_steamid("maraantonov") == "76561198000000001"
        assert cache.get_steamid("MARAANTONOV") == "76561198000000001"

    def test_is_checked_returns_false_initially(self, tmp_path):
        cache = ProfileCache(str(tmp_path / "profiles.json"))
        assert cache.is_checked("76561198000000001") is False

    def test_mark_checked_and_is_checked(self, tmp_path):
        cache = ProfileCache(str(tmp_path / "profiles.json"))
        cache.mark_checked("76561198000000001")
        assert cache.is_checked("76561198000000001") is True

    def test_mark_checked_idempotent(self, tmp_path):
        cache = ProfileCache(str(tmp_path / "profiles.json"))
        cache.mark_checked("76561198000000001")
        cache.mark_checked("76561198000000001")
        cache.mark_checked("76561198000000001")

        # Should only appear once in the underlying list
        checked = cache._cache.get("checked_steamids")
        count = checked.count("76561198000000001")
        assert count == 1

    def test_persistence_across_instances(self, tmp_path):
        path = str(tmp_path / "profiles.json")
        cache1 = ProfileCache(path)
        cache1.set_steamid("testvanity", "76561198000000002")
        cache1.mark_checked("76561198000000002")

        cache2 = ProfileCache(path)
        assert cache2.get_steamid("testvanity") == "76561198000000002"
        assert cache2.is_checked("76561198000000002") is True

    def test_multiple_steamids_independent(self, tmp_path):
        cache = ProfileCache(str(tmp_path / "profiles.json"))
        cache.set_steamid("user_a", "111")
        cache.set_steamid("user_b", "222")
        cache.mark_checked("111")

        assert cache.get_steamid("user_a") == "111"
        assert cache.get_steamid("user_b") == "222"
        assert cache.is_checked("111") is True
        assert cache.is_checked("222") is False
