"""Tests for Pydantic model validation."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from seattle_api.models import (
    HealthStatus,
    Incident,
    IncidentSearchFilters,
    RawIncident,
)


class TestIncidentValidation:
    """Test cases for Incident model validation."""

    def test_incident_validation_required_fields(self):
        """Test validation fails when required fields are missing."""
        with pytest.raises(ValidationError):
            Incident()

    def test_incident_validation_empty_incident_id(self):
        """Test validation fails for empty incident ID."""
        now = datetime.now()
        with pytest.raises(
            ValidationError, match="String should have at least 1 character"
        ):
            Incident(
                incident_id="",
                incident_datetime=now,
                priority=1,
                address="123 Main St",
                incident_type="Test",
                first_seen=now,
                last_seen=now,
            )

    def test_incident_validation_empty_address(self):
        """Test validation fails for empty address."""
        now = datetime.now()
        with pytest.raises(
            ValidationError, match="String should have at least 1 character"
        ):
            Incident(
                incident_id="F123",
                incident_datetime=now,
                priority=1,
                address="",
                incident_type="Test",
                first_seen=now,
                last_seen=now,
            )

    def test_incident_validation_priority_range(self):
        """Test validation fails for priority outside valid range."""
        now = datetime.now()

        # Priority too low
        with pytest.raises(ValidationError):
            Incident(
                incident_id="F123",
                incident_datetime=now,
                priority=0,
                address="123 Main St",
                incident_type="Test",
                first_seen=now,
                last_seen=now,
            )

        # Priority too high
        with pytest.raises(ValidationError):
            Incident(
                incident_id="F123",
                incident_datetime=now,
                priority=11,
                address="123 Main St",
                incident_type="Test",
                first_seen=now,
                last_seen=now,
            )

    def test_incident_validation_cleans_fields(self):
        """Test that validation cleans string fields."""
        now = datetime.now()
        incident = Incident(
            incident_id="  F123  ",
            incident_datetime=now,
            priority=1,
            units=["  E17  ", "", "  L9  "],
            address="  123 Main St  ",
            incident_type="  Test Type  ",
            first_seen=now,
            last_seen=now,
        )

        assert incident.incident_id == "F123"
        assert incident.address == "123 Main St"
        assert incident.incident_type == "Test Type"
        assert incident.units == ["E17", "L9"]  # Empty strings filtered out


class TestRawIncidentValidation:
    """Test cases for RawIncident model validation."""

    def test_raw_incident_validation_required_fields(self):
        """Test validation fails when required fields are missing."""
        with pytest.raises(ValidationError):
            RawIncident()

    def test_raw_incident_validation_empty_fields(self):
        """Test validation fails for empty required fields."""
        with pytest.raises(ValidationError):
            RawIncident(
                datetime_str="",
                incident_id="F123",
                priority_str="1",
                address="123 Main St",
                incident_type="Test",
            )

    def test_raw_incident_validation_cleans_fields(self):
        """Test that validation cleans fields."""
        raw = RawIncident(
            datetime_str="  9/17/2025 8:39:31 PM  ",
            incident_id="  F123  ",
            priority_str="  1  ",
            units_str="  E17  ",
            address="  123 Main St  ",
            incident_type="  Test  ",
        )

        assert raw.datetime_str == "9/17/2025 8:39:31 PM"
        assert raw.incident_id == "F123"
        assert raw.priority_str == "1"
        assert raw.units_str == "E17"
        assert raw.address == "123 Main St"
        assert raw.incident_type == "Test"


class TestIncidentSearchFiltersValidation:
    """Test cases for IncidentSearchFilters model validation."""

    def test_filters_validation_priority_range(self):
        """Test validation fails for priority outside valid range."""
        with pytest.raises(ValidationError):
            IncidentSearchFilters(priority=0)

        with pytest.raises(ValidationError):
            IncidentSearchFilters(priority=11)

    def test_filters_validation_cleans_strings(self):
        """Test that validation cleans string filters."""
        filters = IncidentSearchFilters(
            incident_type="  Fire  ", address_contains="  Main St  "
        )

        assert filters.incident_type == "Fire"
        assert filters.address_contains == "Main St"


class TestHealthStatusValidation:
    """Test cases for HealthStatus model validation."""

    def test_health_status_validation_status_values(self):
        """Test validation fails for invalid status values."""
        with pytest.raises(ValidationError, match="Status must be one of"):
            HealthStatus(status="invalid", service="test", version="1.0.0")

    def test_health_status_validation_valid_statuses(self):
        """Test validation passes for valid status values."""
        for status in ["healthy", "degraded", "unhealthy"]:
            health = HealthStatus(status=status, service="test", version="1.0.0")
            assert health.status == status


class TestDataIntegrity:
    """Test cases for data integrity validation."""

    def test_incident_json_serialization(self):
        """Test that incidents can be serialized to JSON properly."""
        now = datetime.now()
        incident = Incident(
            incident_id="F123",
            incident_datetime=now,
            priority=3,
            units=["E17", "L9"],
            address="123 Main St",
            incident_type="Aid Response",
            first_seen=now,
            last_seen=now,
        )

        # Test JSON serialization
        json_data = incident.model_dump_json()
        assert isinstance(json_data, str)
        assert "F123" in json_data

    def test_incident_model_roundtrip(self):
        """Test that incidents can be serialized and deserialized."""
        now = datetime.now()
        original = Incident(
            incident_id="F123",
            incident_datetime=now,
            priority=3,
            units=["E17", "L9"],
            address="123 Main St",
            incident_type="Aid Response",
            first_seen=now,
            last_seen=now,
        )

        # Serialize to dict and back
        data = original.model_dump()
        restored = Incident(**data)

        assert restored.incident_id == original.incident_id
        assert restored.incident_datetime == original.incident_datetime
        assert restored.priority == original.priority
        assert restored.units == original.units
        assert restored.address == original.address
        assert restored.incident_type == original.incident_type
