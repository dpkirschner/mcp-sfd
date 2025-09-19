"""Tests for data models."""

from datetime import datetime

from seattle_api.models import (
    HealthStatus,
    Incident,
    IncidentSearchFilters,
    IncidentStatus,
    RawIncident,
)


class TestIncidentStatus:
    """Test cases for IncidentStatus enum."""

    def test_incident_status_values(self):
        """Test that IncidentStatus enum has correct values."""
        assert IncidentStatus.ACTIVE.value == "active"
        assert IncidentStatus.CLOSED.value == "closed"


class TestIncident:
    """Test cases for Incident dataclass."""

    def test_incident_creation(self):
        """Test creating an Incident instance."""
        now = datetime.now()
        incident = Incident(
            incident_id="F240001234",
            incident_datetime=now,
            priority=3,
            units=["E17", "L9"],
            address="123 Main St",
            incident_type="Aid Response",
            status=IncidentStatus.ACTIVE,
            first_seen=now,
            last_seen=now,
        )

        assert incident.incident_id == "F240001234"
        assert incident.incident_datetime == now
        assert incident.priority == 3
        assert incident.units == ["E17", "L9"]
        assert incident.address == "123 Main St"
        assert incident.incident_type == "Aid Response"
        assert incident.status == "active"
        assert incident.first_seen == now
        assert incident.last_seen == now
        assert incident.closed_at is None

    def test_incident_serialization(self):
        """Test Pydantic model serialization."""
        now = datetime(2024, 1, 15, 10, 30, 0)
        closed_time = datetime(2024, 1, 15, 11, 0, 0)

        incident = Incident(
            incident_id="F240001234",
            incident_datetime=now,
            priority=3,
            units=["E17", "L9"],
            address="123 Main St",
            incident_type="Aid Response",
            status=IncidentStatus.CLOSED,
            first_seen=now,
            last_seen=now,
            closed_at=closed_time,
        )

        # Test model_dump
        result = incident.model_dump()

        assert result["incident_id"] == "F240001234"
        assert result["incident_datetime"] == now.isoformat()
        assert result["priority"] == 3
        assert result["units"] == ["E17", "L9"]
        assert result["address"] == "123 Main St"
        assert result["incident_type"] == "Aid Response"
        assert result["status"] == "closed"
        assert result["first_seen"] == now.isoformat()
        assert result["last_seen"] == now.isoformat()
        assert result["closed_at"] == closed_time.isoformat()


class TestRawIncident:
    """Test cases for RawIncident dataclass."""

    def test_raw_incident_creation(self):
        """Test creating a RawIncident instance."""
        raw_incident = RawIncident(
            datetime_str="01/15/2024 10:30:00 AM",
            incident_id="F240001234",
            priority_str="3",
            units_str="E17,L9",
            address="123 Main St",
            incident_type="Aid Response",
        )

        assert raw_incident.datetime_str == "01/15/2024 10:30:00 AM"
        assert raw_incident.incident_id == "F240001234"
        assert raw_incident.priority_str == "3"
        assert raw_incident.units_str == "E17,L9"
        assert raw_incident.address == "123 Main St"
        assert raw_incident.incident_type == "Aid Response"


class TestIncidentSearchFilters:
    """Test cases for IncidentSearchFilters dataclass."""

    def test_incident_search_filters_defaults(self):
        """Test IncidentSearchFilters with default values."""
        filters = IncidentSearchFilters()

        assert filters.incident_type is None
        assert filters.address_contains is None
        assert filters.since is None
        assert filters.until is None
        assert filters.status is None
        assert filters.priority is None

    def test_incident_search_filters_with_values(self):
        """Test IncidentSearchFilters with custom values."""
        since_time = datetime(2024, 1, 15, 10, 0, 0)
        until_time = datetime(2024, 1, 15, 12, 0, 0)

        filters = IncidentSearchFilters(
            incident_type="Aid Response",
            address_contains="Main St",
            since=since_time,
            until=until_time,
            status=IncidentStatus.ACTIVE,
            priority=3,
        )

        assert filters.incident_type == "Aid Response"
        assert filters.address_contains == "Main St"
        assert filters.since == since_time
        assert filters.until == until_time
        assert filters.status == IncidentStatus.ACTIVE
        assert filters.priority == 3


class TestHealthStatus:
    """Test cases for HealthStatus dataclass."""

    def test_health_status_creation(self):
        """Test creating a HealthStatus instance."""
        config_dict = {"polling_interval": 5, "port": 8000}

        health = HealthStatus(
            status="healthy",
            service="seattle-fire-api",
            version="1.0.0",
            config=config_dict,
        )

        assert health.status == "healthy"
        assert health.service == "seattle-fire-api"
        assert health.version == "1.0.0"
        assert health.config == config_dict
