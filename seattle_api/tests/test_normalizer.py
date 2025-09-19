"""Tests for data normalizer module."""

from datetime import datetime
from unittest.mock import patch

import pytest

from seattle_api.models import IncidentStatus, RawIncident
from seattle_api.normalizer import IncidentNormalizer, NormalizationError


class TestIncidentNormalizer:
    """Test cases for IncidentNormalizer."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = IncidentNormalizer()

    def test_normalize_valid_incident(self):
        """Test normalizing a valid raw incident."""
        raw_incident = RawIncident(
            datetime_str="9/17/2025 8:39:31 PM",
            incident_id="F250129499",
            priority_str="1",
            units_str="E25 L10",
            address="515 Minor Ave",
            incident_type="Auto Fire Alarm",
        )

        with patch("seattle_api.normalizer.datetime") as mock_datetime:
            mock_now = datetime(2025, 9, 17, 20, 39, 31)
            mock_datetime.utcnow.return_value = mock_now
            # Also need to allow strptime to work normally
            mock_datetime.strptime = datetime.strptime

            incident = self.normalizer.normalize_incident(raw_incident)

            assert incident.incident_id == "F250129499"
            assert incident.priority == 1
            assert incident.units == ["E25", "L10"]
            assert incident.address == "515 Minor Ave"
            assert incident.incident_type == "Auto Fire Alarm"
            assert incident.status == IncidentStatus.ACTIVE
            assert incident.first_seen == mock_now
            assert incident.last_seen == mock_now
            assert incident.closed_at is None

    def test_parse_datetime_standard_format(self):
        """Test parsing standard datetime format."""
        dt = self.normalizer._parse_datetime("9/17/2025 8:39:31 PM")

        # Should be converted to UTC
        assert isinstance(dt, datetime)
        assert dt.tzinfo is None  # Should be naive UTC

        # Verify the date/time is correct (accounting for timezone conversion)
        # 8:39:31 PM Pacific = 3:39:31 AM UTC next day (during DST)
        # or 4:39:31 AM UTC next day (during PST)
        assert dt.month == 9
        assert dt.day in [18]  # Next day due to timezone conversion
        assert dt.year == 2025

    def test_parse_datetime_24_hour_format(self):
        """Test parsing 24-hour datetime format."""
        dt = self.normalizer._parse_datetime("9/17/2025 20:39:31")

        assert isinstance(dt, datetime)
        assert dt.month == 9
        assert dt.day in [18]  # Next day due to timezone conversion
        assert dt.year == 2025

    def test_parse_datetime_two_digit_year(self):
        """Test parsing datetime with 2-digit year."""
        dt = self.normalizer._parse_datetime("9/17/25 8:39:31 PM")

        assert isinstance(dt, datetime)
        assert dt.year == 2025

    def test_parse_datetime_invalid_format(self):
        """Test parsing invalid datetime format."""
        with pytest.raises(NormalizationError, match="Unable to parse datetime"):
            self.normalizer._parse_datetime("Invalid Date")

    def test_parse_datetime_empty_string(self):
        """Test parsing empty datetime string."""
        with pytest.raises(NormalizationError, match="Empty datetime string"):
            self.normalizer._parse_datetime("")

    def test_parse_priority_valid_integer(self):
        """Test parsing valid priority strings."""
        assert self.normalizer._parse_priority("1") == 1
        assert self.normalizer._parse_priority("2") == 2
        assert self.normalizer._parse_priority("10") == 10

    def test_parse_priority_with_extra_text(self):
        """Test parsing priority with extra text."""
        assert self.normalizer._parse_priority("Priority 1") == 1
        assert self.normalizer._parse_priority("Level 3 Emergency") == 3

    def test_parse_priority_with_whitespace(self):
        """Test parsing priority with whitespace."""
        assert self.normalizer._parse_priority("  1  ") == 1
        assert self.normalizer._parse_priority("\t2\n") == 2

    def test_parse_priority_invalid(self):
        """Test parsing invalid priority strings."""
        with pytest.raises(NormalizationError, match="No number found"):
            self.normalizer._parse_priority("High")

        with pytest.raises(NormalizationError, match="Empty priority string"):
            self.normalizer._parse_priority("")

    def test_parse_units_simple(self):
        """Test parsing simple units strings."""
        assert self.normalizer._parse_units("E25") == ["E25"]
        assert self.normalizer._parse_units("E25 L10") == ["E25", "L10"]

    def test_parse_units_with_asterisk(self):
        """Test parsing units with asterisk."""
        assert self.normalizer._parse_units("E25*") == ["E25"]
        assert self.normalizer._parse_units("E25* L10*") == ["E25", "L10"]

    def test_parse_units_with_multiple_delimiters(self):
        """Test parsing units with various delimiters."""
        assert self.normalizer._parse_units("E25,L10") == ["E25", "L10"]
        assert self.normalizer._parse_units("E25;L10") == ["E25", "L10"]
        assert self.normalizer._parse_units("E25, L10") == ["E25", "L10"]

    def test_parse_units_complex(self):
        """Test parsing complex units strings."""
        assert self.normalizer._parse_units("E25* L10 BC4") == ["E25", "L10", "BC4"]
        assert self.normalizer._parse_units("E17, L9, BC1*") == ["E17", "L9", "BC1"]

    def test_parse_units_empty(self):
        """Test parsing empty units string."""
        assert self.normalizer._parse_units("") == []
        assert self.normalizer._parse_units("   ") == []

    def test_parse_units_single_spaces(self):
        """Test parsing units with single spaces."""
        assert self.normalizer._parse_units("E 25") == ["E", "25"]

    def test_normalize_incident_with_parsing_error(self):
        """Test normalization when datetime parsing fails."""
        raw_incident = RawIncident(
            datetime_str="Invalid Date",
            incident_id="F250129499",
            priority_str="1",
            units_str="E25",
            address="515 Minor Ave",
            incident_type="Auto Fire Alarm",
        )

        with pytest.raises(NormalizationError, match="Failed to normalize incident"):
            self.normalizer.normalize_incident(raw_incident)

    def test_normalize_incident_with_priority_error(self):
        """Test normalization when priority parsing fails."""
        raw_incident = RawIncident(
            datetime_str="9/17/2025 8:39:31 PM",
            incident_id="F250129499",
            priority_str="Invalid",
            units_str="E25",
            address="515 Minor Ave",
            incident_type="Auto Fire Alarm",
        )

        with pytest.raises(NormalizationError, match="Failed to normalize incident"):
            self.normalizer.normalize_incident(raw_incident)

    def test_parse_units_fallback_behavior(self):
        """Test units parsing fallback behavior when parsing fails."""
        # This should not raise an exception, but return the original string
        # The parser should handle this gracefully and split on spaces
        result = self.normalizer._parse_units("Some weird units string")
        assert result == ["Some", "weird", "units", "string"]

    def test_timezone_conversion_accuracy(self):
        """Test accuracy of timezone conversion."""
        # Test a specific date/time to ensure correct timezone handling
        dt_str = "12/15/2025 3:30:45 PM"  # Winter time (PST)
        dt = self.normalizer._parse_datetime(dt_str)

        # 3:30:45 PM PST should be 11:30:45 PM UTC
        expected_utc_hour = 23  # 3 PM + 8 hours (PST offset)
        assert dt.hour == expected_utc_hour
        assert dt.minute == 30
        assert dt.second == 45

    def test_timezone_conversion_dst(self):
        """Test timezone conversion during DST."""
        # Test a date during daylight saving time
        dt_str = "7/15/2025 3:30:45 PM"  # Summer time (PDT)
        dt = self.normalizer._parse_datetime(dt_str)

        # 3:30:45 PM PDT should be 10:30:45 PM UTC
        expected_utc_hour = 22  # 3 PM + 7 hours (PDT offset)
        assert dt.hour == expected_utc_hour
        assert dt.minute == 30
        assert dt.second == 45

    def test_normalize_incident_preserves_original_data(self):
        """Test that normalization preserves original string data correctly."""
        raw_incident = RawIncident(
            datetime_str="9/17/2025 8:39:31 PM",
            incident_id="F250129499",
            priority_str="1",
            units_str="E25 L10",
            address="515 Minor Ave Suite 100",
            incident_type="Auto Fire Alarm - Commercial",
        )

        with patch("seattle_api.normalizer.datetime") as mock_datetime:
            mock_now = datetime(2025, 9, 17, 20, 39, 31)
            mock_datetime.utcnow.return_value = mock_now
            # Also need to allow strptime to work normally
            mock_datetime.strptime = datetime.strptime

            incident = self.normalizer.normalize_incident(raw_incident)

            # Verify that string fields are preserved exactly
            assert incident.address == "515 Minor Ave Suite 100"
            assert incident.incident_type == "Auto Fire Alarm - Commercial"

    def test_edge_case_midnight_conversion(self):
        """Test timezone conversion around midnight."""
        # Test conversion that might cross date boundaries
        dt_str = "1/1/2025 11:30:00 PM"  # Late night PST
        dt = self.normalizer._parse_datetime(dt_str)

        # Should convert to next day in UTC
        assert dt.month == 1
        assert dt.day == 2  # Next day
        assert dt.year == 2025
