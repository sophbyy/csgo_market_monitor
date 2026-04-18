from __future__ import annotations

from unittest.mock import MagicMock

from src.discovery.friend_crawler import FriendCrawler


def _make_friend_response(friend_ids: list[str]) -> dict:
    return {
        "friendslist": {
            "friends": [
                {"steamid": sid, "relationship": "friend", "friend_since": 0}
                for sid in friend_ids
            ]
        }
    }


class TestFriendCrawler:
    def test_single_seed_no_friends(self):
        client = MagicMock()
        client.get_friend_list.return_value = {}
        crawler = FriendCrawler(client, delay_seconds=0)
        batches = list(crawler.crawl(["111"]))
        assert batches == []

    def test_single_seed_with_friends(self):
        client = MagicMock()
        client.get_friend_list.return_value = _make_friend_response(["222", "333"])
        crawler = FriendCrawler(client, max_depth=0, delay_seconds=0)
        batches = list(crawler.crawl(["111"]))
        assert len(batches) == 1
        assert len(batches[0]) == 2
        ids = {m.steamid64 for m in batches[0]}
        assert ids == {"222", "333"}

    def test_bfs_depth_limit(self):
        client = MagicMock()
        # Seed 111 -> friends 222, 333
        # 222 -> friends 444
        # 333 -> friends 555
        # 444 -> friends 666 (should not be reached at depth=1)
        def get_friends(steamid):
            return {
                "111": _make_friend_response(["222", "333"]),
                "222": _make_friend_response(["444"]),
                "333": _make_friend_response(["555"]),
                "444": _make_friend_response(["666"]),
            }.get(steamid, {})

        client.get_friend_list.side_effect = get_friends
        crawler = FriendCrawler(client, max_depth=1, delay_seconds=0)
        all_members = []
        for batch in crawler.crawl(["111"]):
            all_members.extend(batch)

        discovered_ids = {m.steamid64 for m in all_members}
        assert "222" in discovered_ids
        assert "333" in discovered_ids
        assert "444" in discovered_ids
        assert "555" in discovered_ids
        # 666 should NOT be discovered (depth 2, but max_depth=1)
        assert "666" not in discovered_ids

    def test_skips_visited(self):
        client = MagicMock()
        # Circular: 111 -> 222 -> 111
        def get_friends(steamid):
            if steamid == "111":
                return _make_friend_response(["222"])
            if steamid == "222":
                return _make_friend_response(["111"])
            return {}

        client.get_friend_list.side_effect = get_friends
        crawler = FriendCrawler(client, max_depth=5, delay_seconds=0)
        all_members = []
        for batch in crawler.crawl(["111"]):
            all_members.extend(batch)

        # Only 222 should be discovered (111 is seed, not re-discovered)
        assert len(all_members) == 1
        assert all_members[0].steamid64 == "222"

    def test_skips_already_checked(self):
        client = MagicMock()
        client.get_friend_list.return_value = _make_friend_response(["222", "333"])

        cache = MagicMock()
        cache.is_checked.side_effect = lambda sid: sid == "222"

        crawler = FriendCrawler(client, max_depth=0, delay_seconds=0)
        batches = list(crawler.crawl(["111"], profile_cache=cache))
        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert batches[0][0].steamid64 == "333"

    def test_multiple_seeds(self):
        client = MagicMock()
        def get_friends(steamid):
            if steamid == "111":
                return _make_friend_response(["aaa"])
            if steamid == "222":
                return _make_friend_response(["bbb"])
            return {}

        client.get_friend_list.side_effect = get_friends
        crawler = FriendCrawler(client, max_depth=0, delay_seconds=0)
        all_members = []
        for batch in crawler.crawl(["111", "222"]):
            all_members.extend(batch)

        ids = {m.steamid64 for m in all_members}
        assert "aaa" in ids
        assert "bbb" in ids
