from __future__ import annotations

from unittest.mock import MagicMock

from src.discovery.batch_prefilter import batch_prefilter, PrefilterResult
from src.discovery.group_crawler import GroupMember


def _make_member(steamid: str) -> GroupMember:
    return GroupMember(
        steamid64=steamid,
        profile_url=f"https://steamcommunity.com/profiles/{steamid}",
    )


class TestBatchPrefilter:
    def test_filters_private_profiles(self):
        client = MagicMock()
        client.get_player_summaries.return_value = {
            "response": {
                "players": [
                    {"steamid": "111", "personaname": "bot1", "communityvisibilitystate": 1},
                ]
            }
        }
        client.get_player_bans.return_value = {"players": []}

        members = [_make_member("111")]
        results = batch_prefilter(client, members)
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].reject_reason == "profile_not_public"

    def test_filters_recently_active(self):
        import time
        recent_logoff = int(time.time()) - 86400  # 1 day ago

        client = MagicMock()
        client.get_player_summaries.return_value = {
            "response": {
                "players": [
                    {
                        "steamid": "222",
                        "personaname": "activeuser",
                        "communityvisibilitystate": 3,
                        "lastlogoff": recent_logoff,
                    },
                ]
            }
        }
        client.get_player_bans.return_value = {
            "players": [{"SteamId": "222", "VACBanned": False}]
        }

        members = [_make_member("222")]
        results = batch_prefilter(client, members)
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].reject_reason == "active_within_30_days"

    def test_passes_valid_candidate(self):
        import time
        old_logoff = int(time.time()) - 86400 * 90  # 90 days ago

        client = MagicMock()
        client.get_player_summaries.return_value = {
            "response": {
                "players": [
                    {
                        "steamid": "333",
                        "personaname": "botaccount",
                        "communityvisibilitystate": 3,
                        "lastlogoff": old_logoff,
                    },
                ]
            }
        }
        client.get_player_bans.return_value = {
            "players": [{"SteamId": "333", "VACBanned": True}]
        }

        members = [_make_member("333")]
        results = batch_prefilter(client, members)
        assert len(results) == 1
        assert results[0].passed
        assert results[0].vac_banned is True
        assert results[0].nickname == "botaccount"

    def test_skips_already_checked(self):
        client = MagicMock()
        cache = MagicMock()
        cache.is_checked.return_value = True

        members = [_make_member("444")]
        results = batch_prefilter(client, members, profile_cache=cache)
        assert results == []
        client.get_player_summaries.assert_not_called()

    def test_handles_missing_summary(self):
        client = MagicMock()
        client.get_player_summaries.return_value = {"response": {"players": []}}
        client.get_player_bans.return_value = {"players": []}

        members = [_make_member("555")]
        results = batch_prefilter(client, members)
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].reject_reason == "no_summary_data"
