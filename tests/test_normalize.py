"""
Tests for data normalization functions.

This module tests the complex data transformation logic that converts
upstream API responses into our standardized format.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
import pytz

from mcp_sfd.normalize import (
    flatten_data_array,
    normalize_full_response,
    normalize_incident,
    normalize_response_meta,
    parse_boolean,
    parse_coordinate,
    parse_datetime,
    parse_unit_status,
    parse_units,
)
from mcp_sfd.schemas import Incident, UnitStatus


class TestParseDatetime:
    """Test datetime parsing with timezone conversion."""

    def test_parse_datetime_standard_format(self):
        """Test parsing standard datetime format from API."""
        dt_str = "2025-09-15 16:05:27"
        result = parse_datetime(dt_str)

        # Should be converted to UTC
        assert result.tzinfo == pytz.UTC
        # Should represent the correct time (PDT is UTC-7 in September)
        assert result.hour == 23  # 16 + 7 = 23 UTC

    def test_parse_datetime_invalid_format(self):
        """Test handling of invalid datetime format."""
        result = parse_datetime("invalid-date")

        # Should return current time as fallback
        assert isinstance(result, datetime)
        assert result.tzinfo == pytz.UTC

    def test_parse_datetime_iso_fallback(self):
        """Test fallback to ISO format parsing."""
        dt_str = "2025-09-15T16:05:27Z"
        result = parse_datetime(dt_str)

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

        # Test whitespace-only string
        result = parse_datetime("   ")
        assert isinstance(result, datetime)
        assert result.tzinfo == pytz.UTC

        # Test null string
        result = parse_datetime("null")
        assert isinstance(result, datetime)
        assert result.tzinfo == pytz.UTC


class TestParseCoordinate:
    """Test coordinate parsing from various formats."""

    def test_parse_coordinate_float(self):
        """Test parsing float coordinate."""
        result = parse_coordinate(47.6062)
        assert result == 47.6062

    def test_parse_coordinate_string(self):
        """Test parsing string coordinate."""
        result = parse_coordinate("47.6062")
        assert result == 47.6062

    def test_parse_coordinate_dict_with_parsed_value(self):
        """Test parsing dict format with parsedValue."""
        coord_dict = {"source": "address", "parsedValue": 47.6062}
        result = parse_coordinate(coord_dict)
        assert result == 47.6062

    def test_parse_coordinate_dict_alternative_keys(self):
        """Test parsing dict with alternative keys."""
        coord_dict = {"latitude": 47.6062}
        result = parse_coordinate(coord_dict)
        assert result == 47.6062

    def test_parse_coordinate_none(self):
        """Test parsing None coordinate."""
        result = parse_coordinate(None)
        assert result is None

    def test_parse_coordinate_invalid(self):
        """Test parsing invalid coordinate."""
        result = parse_coordinate("invalid")
        assert result is None


class TestParseUnits:
    """Test unit string parsing."""

    def test_parse_units_with_markers(self):
        """Test parsing units with trailing markers."""
        result = parse_units("E16*, L15, E32")
        assert result == ["E16", "L15", "E32"]

    def test_parse_units_comma_separated(self):
        """Test parsing comma-separated units."""
        result = parse_units("E16,L15,E32")
        assert result == ["E16", "L15", "E32"]

    def test_parse_units_mixed_separators(self):
        """Test parsing with mixed separators."""
        result = parse_units("E16* L15,E32")
        assert result == ["E16", "L15", "E32"]

    def test_parse_units_empty(self):
        """Test parsing empty string."""
        result = parse_units("")
        assert result == []

    def test_parse_units_none_value(self):
        """Test parsing None value."""
        result = parse_units("None")
        assert result == []


class TestParseBoolean:
    """Test boolean parsing from various formats."""

    def test_parse_boolean_integer(self):
        """Test parsing integer booleans."""
        assert parse_boolean(1) is True
        assert parse_boolean(0) is False

    def test_parse_boolean_string(self):
        """Test parsing string booleans."""
        assert parse_boolean("true") is True
        assert parse_boolean("false") is False
        assert parse_boolean("1") is True
        assert parse_boolean("0") is False

    def test_parse_boolean_actual_boolean(self):
        """Test parsing actual boolean values."""
        assert parse_boolean(True) is True
        assert parse_boolean(False) is False


class TestParseUnitStatus:
    """Test unit status parsing."""

    def test_parse_unit_status_complete(self):
        """Test parsing complete unit status."""
        status_data = {
            "E16": {
                "dispatched": "2025-09-15 16:05:30",
                "arrived": "2025-09-15 16:08:15",
                "transport": None,
                "in_service": None,
            }
        }

        result = parse_unit_status(status_data)
        assert "E16" in result
        assert isinstance(result["E16"], UnitStatus)
        assert result["E16"].dispatched == "2025-09-15 16:05:30"
        assert result["E16"].arrived == "2025-09-15 16:08:15"

    def test_parse_unit_status_empty(self):
        """Test parsing empty unit status."""
        result = parse_unit_status({})
        assert result == {}

    def test_parse_unit_status_invalid(self):
        """Test parsing invalid unit status."""
        result = parse_unit_status("invalid")
        assert result == {}


class TestFlattenDataArray:
    """Test flattening of upstream data array format."""

    def test_flatten_data_array_standard(self):
        """Test flattening standard format."""
        data = [{"0": {"id": 1, "type": "Fire"}}, {"1": {"id": 2, "type": "Medical"}}]

        result = flatten_data_array(data)
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_flatten_data_array_alternative_keys(self):
        """Test flattening with alternative keys."""
        data = [{"incident": {"id": 1, "type": "Fire"}}]

        result = flatten_data_array(data)
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_flatten_data_array_empty(self):
        """Test flattening empty array."""
        result = flatten_data_array([])
        assert result == []


class TestNormalizeIncident:
    """Test complete incident normalization."""

    def test_normalize_incident_complete(self):
        """Test normalizing a complete incident."""
        raw_incident = {
            "id": 12345,
            "incident_number": "F250915-001",
            "type": "Fire in Building",
            "type_code": "FIR",
            "description": "STRUCTURE FIRE - COMMERCIAL BUILDING",
            "datetime": "2025-09-15 16:05:27",
            "latitude": 47.6062,
            "longitude": -122.3321,
            "address": "123 Main St, Seattle, WA",
            "units_dispatched": "E16*, L15",
            "active": 1,
            "late": 0,
            "unit_status": {
                "E16": {
                    "dispatched": "2025-09-15 16:05:30",
                    "arrived": "2025-09-15 16:08:15",
                    "transport": None,
                    "in_service": None,
                }
            },
        }

        result = normalize_incident(raw_incident)

        assert isinstance(result, Incident)
        assert result.id == 12345
        assert result.incident_number == "F250915-001"
        assert result.type == "Fire in Building"
        assert result.units == ["E16", "L15"]
        assert result.active is True
        assert result.late is False
        assert result.latitude == 47.6062
        assert result.longitude == -122.3321

    def test_normalize_incident_minimal(self):
        """Test normalizing minimal incident data."""
        raw_incident = {
            "id": 1,
            "incident_number": "TEST-001",
            "type": "Test",
            "description": "Test incident",
            "datetime": "2025-09-15 12:00:00",
            "address": "Test Address",
        }

        result = normalize_incident(raw_incident)

        assert isinstance(result, Incident)
        assert result.id == 1
        assert result.units == []
        assert result.active is False


class TestFullNormalization:
    """Test complete response normalization using example data."""

    @pytest.fixture
    def example_response(self):
        """Load example response data."""
        example_path = Path(__file__).parent / "data" / "example_payload.json"
        with open(example_path) as f:
            return json.load(f)

    def test_normalize_full_response(self, example_response):
        """Test complete response normalization."""
        result = normalize_full_response(
            example_response, "https://test.example.com", False
        )

        # Check structure
        assert "meta" in result
        assert "incidents" in result
        assert "source" in result

        # Check meta
        meta = result["meta"]
        assert meta["page"] == 1
        assert meta["results_per_page"] == 100
        assert meta["order"] == "new"

        # Check incidents
        incidents = result["incidents"]
        assert len(incidents) == 4

        # Check first incident (fire)
        fire_incident = incidents[0]
        assert fire_incident["type"] == "Fire in Building"
        assert fire_incident["active"] is True
        assert fire_incident["units"] == ["E16", "L15", "E32"]

        # Check source
        source = result["source"]
        assert source["url"] == "https://test.example.com"
        assert source["cache_hit"] is False

    def test_normalize_response_meta(self, example_response):
        """Test response metadata normalization."""
        result = normalize_response_meta(example_response)

        assert result.page == 1
        assert result.results_per_page == 100
        assert result.order == "new"
        assert result.total_incidents == 156
