"""Tests for src.patterns — Russian name pattern detection."""

from src.patterns import NamePatternResult, detect_name_pattern


# -----------------------------------------------------------------------
# Known bot names from tz.txt — all should match with high confidence
# -----------------------------------------------------------------------

class TestKnownBotNames:
    """Names taken directly from tz.txt example profiles."""

    def test_maraantonov(self):
        result = detect_name_pattern("maraantonov")
        assert result.matches is True
        assert result.pattern_type == "russian_name"
        assert result.confidence >= 0.9

    def test_fomakrukov242(self):
        result = detect_name_pattern("fomakrukov242")
        assert result.matches is True
        assert result.pattern_type == "russian_name_digits"
        assert result.confidence >= 0.9

    def test_magdasurkov153(self):
        result = detect_name_pattern("magdasurkov153")
        assert result.matches is True
        assert result.pattern_type == "russian_name_digits"
        assert result.confidence >= 0.9

    def test_hakimchistyakov(self):
        result = detect_name_pattern("hakimchistyakov")
        assert result.matches is True
        assert result.pattern_type == "russian_name"
        assert result.confidence >= 0.9

    def test_bertadmitriev944(self):
        result = detect_name_pattern("bertadmitriev944")
        assert result.matches is True
        assert result.pattern_type == "russian_name_digits"
        assert result.confidence >= 0.9

    def test_bekumugilysaqo(self):
        result = detect_name_pattern("bekumugilysaqo")
        assert result.matches is True
        # Partial match (only "bekum" first name found), not full firstname+lastname
        assert result.confidence >= 0.4


# -----------------------------------------------------------------------
# Regular player names — should NOT match with high confidence
# -----------------------------------------------------------------------

class TestRegularPlayerNames:
    """Typical gamer handles that should not be flagged as bot names."""

    def test_gamer_tag_with_special_chars(self):
        result = detect_name_pattern("xXx_sniper_xXx")
        assert result.matches is False
        assert result.confidence == 0.0

    def test_generic_player_name(self):
        result = detect_name_pattern("player123")
        # "player" is not a Russian first name, and it's short; should not match
        assert result.confidence < 0.5

    def test_short_name(self):
        result = detect_name_pattern("john")
        assert result.matches is False
        assert result.confidence == 0.0

    def test_all_caps_name(self):
        # Case-insensitive lowering should still not match non-Russian names
        result = detect_name_pattern("GAMERKING")
        # 9 chars, no name match; below 10-char heuristic threshold
        assert result.confidence < 0.5

    def test_name_with_hyphens(self):
        result = detect_name_pattern("cool-dude-99")
        assert result.matches is False
        assert result.confidence == 0.0


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_string(self):
        result = detect_name_pattern("")
        assert result.matches is False
        assert result.confidence == 0.0

    def test_whitespace_only(self):
        result = detect_name_pattern("   ")
        assert result.matches is False
        assert result.confidence == 0.0

    def test_single_russian_first_name_only(self):
        """A bare first name with nothing after it should not match as full pattern."""
        result = detect_name_pattern("ivan")
        # Just "ivan" alone — no last name, no digits; too short for heuristic
        assert result.confidence < 0.9

    def test_very_long_string(self):
        result = detect_name_pattern("a" * 100)
        # Well beyond the 25-char heuristic limit, no name match
        assert result.matches is False
        assert result.confidence == 0.0

    def test_special_characters_only(self):
        result = detect_name_pattern("!@#$%^&*()")
        assert result.matches is False
        assert result.confidence == 0.0

    def test_digits_only(self):
        result = detect_name_pattern("123456")
        assert result.matches is False
        assert result.confidence == 0.0

    def test_case_insensitivity(self):
        """Should work regardless of input casing."""
        lower = detect_name_pattern("fomakrukov242")
        upper = detect_name_pattern("FOMAKRUKOV242")
        mixed = detect_name_pattern("FomaKrukov242")
        assert lower.matches == upper.matches == mixed.matches
        assert lower.confidence == upper.confidence == mixed.confidence

    def test_leading_trailing_whitespace(self):
        result = detect_name_pattern("  maraantonov  ")
        assert result.matches is True
        assert result.confidence >= 0.9


# -----------------------------------------------------------------------
# Return type structure
# -----------------------------------------------------------------------

class TestReturnType:

    def test_returns_name_pattern_result(self):
        result = detect_name_pattern("fomakrukov242")
        assert isinstance(result, NamePatternResult)

    def test_pattern_type_values(self):
        """pattern_type should be one of the known values."""
        for name in ["maraantonov", "fomakrukov242", "xXx_sniper_xXx"]:
            result = detect_name_pattern(name)
            assert result.pattern_type in {
                "russian_name",
                "russian_name_digits",
                "unknown",
            }

    def test_confidence_range(self):
        """Confidence must always be between 0.0 and 1.0."""
        test_names = [
            "maraantonov", "fomakrukov242", "player123",
            "", "xXx_sniper_xXx", "a" * 50,
        ]
        for name in test_names:
            result = detect_name_pattern(name)
            assert 0.0 <= result.confidence <= 1.0, (
                f"confidence={result.confidence} for name={name!r}"
            )
