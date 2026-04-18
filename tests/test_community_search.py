from __future__ import annotations

from unittest.mock import MagicMock

from src.discovery.community_search import CommunitySearcher


class TestGenerateQueries:
    def test_returns_list(self):
        page = MagicMock()
        searcher = CommunitySearcher(page)
        queries = searcher.generate_queries(max_queries=5)
        assert isinstance(queries, list)
        assert len(queries) == 5

    def test_queries_are_name_combinations(self):
        page = MagicMock()
        searcher = CommunitySearcher(page)
        queries = searcher.generate_queries(max_queries=100)
        for q in queries:
            assert q.isalpha()
            assert q.islower()

    def test_max_queries_limit(self):
        page = MagicMock()
        searcher = CommunitySearcher(page)
        queries = searcher.generate_queries(max_queries=3)
        assert len(queries) == 3


class TestSearchQuery:
    def test_navigation_error(self):
        page = MagicMock()
        page.goto.side_effect = Exception("timeout")
        searcher = CommunitySearcher(page)
        result = searcher._search_query("testquery")
        assert result == []

    def test_no_results(self):
        page = MagicMock()
        page.wait_for_selector.return_value = MagicMock()
        no_results_el = MagicMock()
        page.query_selector.return_value = no_results_el
        page.content.return_value = ""
        searcher = CommunitySearcher(page)
        result = searcher._search_query("testquery")
        assert result == []

    def test_extracts_profile_urls(self):
        page = MagicMock()
        page.wait_for_selector.return_value = MagicMock()
        page.query_selector.return_value = None  # no "no results" element
        page.content.return_value = (
            '<a href="https://steamcommunity.com/profiles/76561198000000001">'
            '<a href="https://steamcommunity.com/id/maraantonov">'
        )
        searcher = CommunitySearcher(page)
        result = searcher._search_query("testquery")
        assert len(result) == 2
        ids = {m.steamid64 for m in result}
        assert "76561198000000001" in ids
        assert "" in ids  # vanity URL, unresolved

    def test_max_results_limit(self):
        page = MagicMock()
        page.wait_for_selector.return_value = MagicMock()
        page.query_selector.return_value = None
        # Generate many profile links
        links = "".join(
            f'<a href="https://steamcommunity.com/profiles/7656119800000{i:04d}">'
            for i in range(100)
        )
        page.content.return_value = links
        searcher = CommunitySearcher(page, max_results_per_query=10)
        result = searcher._search_query("testquery")
        assert len(result) <= 10
