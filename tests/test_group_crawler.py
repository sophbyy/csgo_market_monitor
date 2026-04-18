from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.discovery.group_crawler import GroupCrawler, GroupMember, GroupInfo


SAMPLE_XML_PAGE1 = """<?xml version="1.0" encoding="UTF-8"?>
<memberList>
    <groupID64>103582791429521412</groupID64>
    <memberCount>3</memberCount>
    <totalPages>1</totalPages>
    <currentPage>1</currentPage>
    <members>
        <steamID64>76561198000000001</steamID64>
        <steamID64>76561198000000002</steamID64>
        <steamID64>76561198000000003</steamID64>
    </members>
</memberList>"""

SAMPLE_XML_PAGE1_OF2 = """<?xml version="1.0" encoding="UTF-8"?>
<memberList>
    <groupID64>103582791429521412</groupID64>
    <memberCount>2000</memberCount>
    <totalPages>2</totalPages>
    <currentPage>1</currentPage>
    <members>
        <steamID64>76561198000000001</steamID64>
        <steamID64>76561198000000002</steamID64>
    </members>
</memberList>"""

SAMPLE_XML_PAGE2_OF2 = """<?xml version="1.0" encoding="UTF-8"?>
<memberList>
    <groupID64>103582791429521412</groupID64>
    <memberCount>2000</memberCount>
    <totalPages>2</totalPages>
    <currentPage>2</currentPage>
    <members>
        <steamID64>76561198000000003</steamID64>
    </members>
</memberList>"""


class TestParseGroupIdentifier:
    def test_plain_name(self):
        crawler = GroupCrawler(MagicMock())
        assert crawler.parse_group_identifier("market_csgo_com") == "market_csgo_com"

    def test_full_url(self):
        crawler = GroupCrawler(MagicMock())
        result = crawler.parse_group_identifier(
            "https://steamcommunity.com/groups/market_csgo_com"
        )
        assert result == "market_csgo_com"

    def test_url_with_trailing_slash(self):
        crawler = GroupCrawler(MagicMock())
        result = crawler.parse_group_identifier(
            "https://steamcommunity.com/groups/market_csgo_com/"
        )
        assert result == "market_csgo_com"


class TestExtractMembers:
    def test_extracts_steamids(self):
        import xml.etree.ElementTree as ET
        crawler = GroupCrawler(MagicMock())
        root = ET.fromstring(SAMPLE_XML_PAGE1)
        members = crawler._extract_members(root)
        assert len(members) == 3
        assert members[0] == GroupMember(
            steamid64="76561198000000001",
            profile_url="https://steamcommunity.com/profiles/76561198000000001",
        )

    def test_empty_members(self):
        import xml.etree.ElementTree as ET
        crawler = GroupCrawler(MagicMock())
        xml = "<memberList><members></members></memberList>"
        root = ET.fromstring(xml)
        assert crawler._extract_members(root) == []


class TestGetGroupInfo:
    def test_returns_info(self):
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.text = SAMPLE_XML_PAGE1
        session.get.return_value = response

        crawler = GroupCrawler(session)
        info = crawler.get_group_info("test_group")
        assert info is not None
        assert info.member_count == 3
        assert info.total_pages == 1


class TestCrawl:
    def test_single_page(self):
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.text = SAMPLE_XML_PAGE1
        session.get.return_value = response

        crawler = GroupCrawler(session, delay_seconds=0)
        pages = list(crawler.crawl("test_group"))
        assert len(pages) == 1
        assert len(pages[0]) == 3

    def test_multi_page(self):
        session = MagicMock()
        r1 = MagicMock()
        r1.status_code = 200
        r1.text = SAMPLE_XML_PAGE1_OF2
        r2 = MagicMock()
        r2.status_code = 200
        r2.text = SAMPLE_XML_PAGE2_OF2
        session.get.side_effect = [r1, r2]

        crawler = GroupCrawler(session, delay_seconds=0)
        pages = list(crawler.crawl("test_group"))
        assert len(pages) == 2
        assert len(pages[0]) == 2
        assert len(pages[1]) == 1

    def test_max_pages_limit(self):
        session = MagicMock()
        r1 = MagicMock()
        r1.status_code = 200
        r1.text = SAMPLE_XML_PAGE1_OF2
        session.get.return_value = r1

        crawler = GroupCrawler(session, delay_seconds=0, max_pages=1)
        pages = list(crawler.crawl("test_group"))
        assert len(pages) == 1

    def test_start_page(self):
        session = MagicMock()
        r = MagicMock()
        r.status_code = 200
        r.text = SAMPLE_XML_PAGE2_OF2
        session.get.return_value = r

        crawler = GroupCrawler(session, delay_seconds=0)
        pages = list(crawler.crawl("test_group", start_page=2))
        assert len(pages) == 1
        assert pages[0][0].steamid64 == "76561198000000003"
