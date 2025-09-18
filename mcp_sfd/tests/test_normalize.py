"""
Tests for data normalization functions.

This module tests the data transformation logic that converts
Socrata API responses into our standardized format.
"""

from datetime import datetime

import pytz

from mcp_sfd.normalize import (
    estimate_incident_active,
    normalize_full_response,
    normalize_incident,
    normalize_response_meta,
    parse_coordinate,
    parse_datetime,
    parse_report_location,
)
from mcp_sfd.schemas import Incident, ReportLocation


class TestParseDatetime:
    """Test datetime parsing for Socrata ISO format."""

    def test_parse_datetime_iso_format(self):
        """Test parsing ISO datetime format from Socrata API."""
        dt_str = "2025-09-15T22:58:00.000"
        result = parse_datetime(dt_str)

        # Should be converted to UTC
        assert result.tzinfo == pytz.UTC

    def test_parse_datetime_with_z_suffix(self):
        """Test parsing ISO format with Z suffix."""
        dt_str = "2025-09-15T22:58:00.000Z"
        result = parse_datetime(dt_str)

        assert isinstance(result, datetime)
        assert result.tzinfo == pytz.UTC

    def test_parse_datetime_invalid_format(self):
        """Test handling of invalid datetime format."""
        result = parse_datetime("invalid-date")

        # Should return current time as fallback
        assert isinstance(result, datetime)
        assert result.tzinfo == pytz.UTC

    def test_parse_datetime_empty_string(self):
        """Test handling of empty datetime strings."""
        # Test empty string
        result = parse_datetime("")
        assert isinstance(result, datetime)
        assert result.tzinfo == pytz.UTC

        # Test None-like strings
        result = parse_datetime("None")
        assert isinstance(result, datetime)
        assert result.tzinfo == pytz.UTC

    def test_parse_datetime_legacy_format_fallback(self):
        """Test fallback to legacy SFD format parsing."""
        dt_str = "2025-09-15 16:05:27"
        result = parse_datetime(dt_str)

        assert isinstance(result, datetime)
        assert result.tzinfo == pytz.UTC


class TestParseCoordinate:
    """Test coordinate parsing from Socrata string format."""

    def test_parse_coordinate_string(self):
        """Test parsing string coordinate from Socrata."""
        result = parse_coordinate("47.6062")
        assert result == 47.6062

    def test_parse_coordinate_float(self):
        """Test parsing float coordinate."""
        result = parse_coordinate(47.6062)
        assert result == 47.6062

    def test_parse_coordinate_none(self):
        """Test parsing None coordinate."""
        result = parse_coordinate(None)
        assert result is None

    def test_parse_coordinate_invalid(self):
        """Test parsing invalid coordinate."""
        result = parse_coordinate("invalid")
        assert result is None


class TestParseReportLocation:
    """Test report location parsing from Socrata format."""

    def test_parse_report_location_complete(self):
        """Test parsing complete report location."""
        location_data = {"type": "Point", "coordinates": [-122.336484, 47.611672]}

        result = parse_report_location(location_data)
        assert isinstance(result, ReportLocation)
        assert result.type == "Point"
        assert result.coordinates == [-122.336484, 47.611672]

    def test_parse_report_location_none(self):
        """Test parsing None location."""
        result = parse_report_location(None)
        assert result is None

    def test_parse_report_location_invalid(self):
        """Test parsing invalid location."""
        result = parse_report_location("invalid")
        assert result is None


class TestEstimateIncidentActive:
    """Test incident activity estimation."""

    def test_estimate_incident_active_recent(self):
        """Test that recent incidents are considered active."""
        # Create a recent datetime (5 minutes ago)
        recent_time = datetime.now(pytz.UTC)
        result = estimate_incident_active(recent_time)
        assert result is True

    def test_estimate_incident_active_old(self):
        """Test that old incidents are not considered active."""
        # Create an old datetime (2 hours ago)
        import datetime as dt

        old_time = datetime.now(pytz.UTC) - dt.timedelta(hours=2)
        result = estimate_incident_active(old_time)
        assert result is False


class TestNormalizeIncident:
    """Test complete incident normalization for Socrata data."""

    def test_normalize_incident_complete(self):
        """Test normalizing a complete Socrata incident."""
        raw_incident = {
            "incident_number": "F250128483",
            "type": "Auto Fire Alarm",
            "address": "1601 5th Ave",
            "datetime": "2025-09-15T22:58:00.000",
            "latitude": "47.611672",
            "longitude": "-122.336484",
            "report_location": {
                "type": "Point",
                "coordinates": [-122.336484, 47.611672],
            },
            ":@computed_region_ru88_fbhk": "14",
            ":@computed_region_kuhn_3gp2": "31",
            ":@computed_region_q256_3sug": "18081",
        }

        result = normalize_incident(raw_incident)

        assert isinstance(result, Incident)
        assert result.incident_number == "F250128483"
        assert result.type == "Auto Fire Alarm"
        assert result.address == "1601 5th Ave"
        assert result.latitude == 47.611672
        assert result.longitude == -122.336484
        assert result.computed_region_ru88_fbhk == "14"
        assert isinstance(result.estimated_active, bool)
        assert result.raw == raw_incident

    def test_normalize_incident_minimal(self):
        """Test normalizing minimal Socrata incident data."""
        raw_incident = {
            "incident_number": "TEST-001",
            "type": "Test",
            "address": "Test Address",
            "datetime": "2025-09-15T12:00:00.000",
        }

        result = normalize_incident(raw_incident)

        assert isinstance(result, Incident)
        assert result.incident_number == "TEST-001"
        assert result.type == "Test"
        assert result.address == "Test Address"
        assert result.latitude is None
        assert result.longitude is None


class TestSocrataFullNormalization:
    """Test complete response normalization for Socrata format."""

    def test_normalize_full_response_socrata(self):
        """Test complete Socrata response normalization."""
        # Create sample Socrata incident data
        raw_incidents = [
            {
                "incident_number": "F250128483",
                "type": "Auto Fire Alarm",
                "address": "1601 5th Ave",
                "datetime": "2025-09-15T22:58:00.000",
                "latitude": "47.611672",
                "longitude": "-122.336484",
                "report_location": {
                    "type": "Point",
                    "coordinates": [-122.336484, 47.611672],
                },
            },
            {
                "incident_number": "M250128484",
                "type": "Medical Aid",
                "address": "456 Pine St",
                "datetime": "2025-09-15T22:30:00.000",
                "latitude": "47.612345",
                "longitude": "-122.345678",
            },
        ]

        query_params = {"$order": "datetime DESC", "$limit": 2, "$offset": 0}

        result = normalize_full_response(
            raw_incidents,
            "https://data.seattle.gov/resource/kzjm-xkqj.json",
            False,
            query_params,
        )

        # Check structure
        assert "meta" in result
        assert "incidents" in result
        assert "source" in result

        # Check meta
        meta = result["meta"]
        assert meta["results_returned"] == 2
        assert meta["order"] == "new"  # DESC converted to "new"
        assert meta["limit"] == 2

        # Check incidents
        incidents = result["incidents"]
        assert len(incidents) == 2

        # Check first incident
        first_incident = incidents[0]
        assert first_incident["incident_number"] == "F250128483"
        assert first_incident["type"] == "Auto Fire Alarm"

        # Check source
        source = result["source"]
        assert "data.seattle.gov" in source["url"]
        assert source["cache_hit"] is False

    def test_normalize_response_meta_socrata(self):
        """Test response metadata normalization for Socrata."""
        query_params = {"$order": "datetime ASC", "$limit": 50, "$offset": 10}

        result = normalize_response_meta(25, query_params)

        assert result.results_returned == 25
        assert result.order == "old"  # ASC converted to "old"
        assert result.limit == 50
        assert result.offset == 10
