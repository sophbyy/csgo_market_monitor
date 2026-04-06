"""Tests for src.pipeline.exporter — CSV export."""

import csv
from datetime import datetime, timezone

from src.pipeline.evaluator import EvaluationResult, ProfileData
from src.pipeline.exporter import CSV_HEADERS, write_csv_row


def _make_profile() -> ProfileData:
    return ProfileData(
        steam_id="76561198000000000",
        profile_url="https://steamcommunity.com/id/testuser",
        nickname="TestUser",
        steam_level=5,
        vac_banned=True,
        last_logoff=1700000000,
        total_playtime_hours=3.5,
        inventory_value_usd=1200.50,
        source_platform="market.csgo.com",
        name_pattern_match="russian_name",
        name_pattern_confidence=0.9,
    )


def _make_evaluation() -> EvaluationResult:
    return EvaluationResult(is_candidate=True, days_since_active=90, reasons=[])


class TestWriteCsvRow:

    def test_writes_headers_on_first_call(self, tmp_path):
        csv_file = str(tmp_path / "output.csv")
        write_csv_row(csv_file, _make_profile(), _make_evaluation(), "2024-01-01T00:00:00+00:00")

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header_row = next(reader)

        assert header_row == CSV_HEADERS

    def test_no_duplicate_headers_on_second_call(self, tmp_path):
        csv_file = str(tmp_path / "output.csv")
        write_csv_row(csv_file, _make_profile(), _make_evaluation(), "2024-01-01T00:00:00+00:00")
        write_csv_row(csv_file, _make_profile(), _make_evaluation(), "2024-01-02T00:00:00+00:00")

        with open(csv_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # First line is headers, second and third are data rows
        assert len(lines) == 3
        # Only the first line should contain "steam_id" as a plain header
        header_count = sum(1 for line in lines if line.startswith("steam_id,"))
        assert header_count == 1

    def test_correct_field_values(self, tmp_path):
        csv_file = str(tmp_path / "output.csv")
        profile = _make_profile()
        evaluation = _make_evaluation()
        collected_at = "2024-06-15T12:00:00+00:00"

        write_csv_row(csv_file, profile, evaluation, collected_at)

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["steam_id"] == "76561198000000000"
        assert row["profile_url"] == "https://steamcommunity.com/id/testuser"
        assert row["nickname"] == "TestUser"
        assert row["steam_level"] == "5"
        assert row["vac_banned"] == "True"
        assert row["last_logoff_utc"] == "2023-11-14T22:13:20+00:00"
        assert row["days_since_active"] == "90"
        assert row["total_playtime_hours"] == "3.5"
        assert row["inventory_value_usd"] == "1200.5"
        assert row["source_platform"] == "market.csgo.com"
        assert row["name_pattern_match"] == "russian_name"
        assert row["name_pattern_confidence"] == "0.9"
        assert row["collected_at_utc"] == collected_at

    def test_creates_parent_directories(self, tmp_path):
        csv_file = str(tmp_path / "subdir" / "nested" / "output.csv")
        write_csv_row(csv_file, _make_profile(), _make_evaluation(), "2024-01-01T00:00:00+00:00")

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["steam_id"] == "76561198000000000"

    def test_none_values_written_as_empty(self, tmp_path):
        csv_file = str(tmp_path / "output.csv")
        profile = ProfileData(
            steam_id="76561198000000000",
            profile_url="https://steamcommunity.com/profiles/76561198000000000",
            nickname="Anon",
            steam_level=0,
            vac_banned=False,
            last_logoff=None,
            total_playtime_hours=None,
            inventory_value_usd=None,
            source_platform="lis-skins.com",
        )
        evaluation = EvaluationResult(is_candidate=False, days_since_active=None, reasons=["inventory_value_below_500"])

        write_csv_row(csv_file, profile, evaluation, "2024-01-01T00:00:00+00:00")

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["last_logoff_utc"] == ""
        assert row["days_since_active"] == ""
        assert row["total_playtime_hours"] == ""
        assert row["inventory_value_usd"] == ""
