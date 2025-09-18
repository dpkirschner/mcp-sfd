"""Simple tests for FastAPI incident endpoints."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from seattle_api.main import app
from seattle_api.models import Incident, IncidentStatus
from seattle_api.routes.incidents import get_cache


@pytest.fixture
def sample_incidents():
    """Sample incidents for testing."""
    return [
        Incident(
            incident_id="INC001",
            incident_datetime=datetime(2023, 12, 25, 22, 30, 45, tzinfo=UTC),
            priority=5,
            units=["E16", "L9"],
            address="123 Main St",
            incident_type="Aid Response",
            status=IncidentStatus.ACTIVE,
            first_seen=datetime(2023, 12, 25, 22, 30, 45, tzinfo=UTC),
            last_seen=datetime(2023, 12, 25, 22, 35, 45, tzinfo=UTC)
        ),
        Incident(
            incident_id="INC002",
            incident_datetime=datetime(2023, 12, 25, 23, 15, 30, tzinfo=UTC),
            priority=3,
            units=["E25", "BC4"],
            address="456 Oak Ave",
            incident_type="Structure Fire",
            status=IncidentStatus.ACTIVE,
            first_seen=datetime(2023, 12, 25, 23, 15, 30, tzinfo=UTC),
            last_seen=datetime(2023, 12, 25, 23, 20, 30, tzinfo=UTC)
        )
    ]


@pytest.fixture
def mock_cache(sample_incidents):
    """Mock cache that returns sample data."""
    cache = MagicMock()
    cache.get_active_incidents.return_value = sample_incidents
    cache.get_all_incidents.return_value = sample_incidents
    cache.get_incident.side_effect = lambda incident_id: next(
        (i for i in sample_incidents if i.incident_id == incident_id), None
    )
    return cache


@pytest.fixture
def client(mock_cache):
    """Test client with mocked cache dependency."""
    app.dependency_overrides[get_cache] = lambda: mock_cache
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides = {}  # Cleanup


def test_health_endpoint(client):
    """Test health endpoint works."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_root_endpoint(client):
    """Test root endpoint works."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "Seattle Fire Department" in data["message"]


def test_active_incidents(client, sample_incidents):
    """Test active incidents endpoint."""
    response = client.get("/incidents/active")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 2
    assert data["data"][0]["incident_id"] == "INC001"


def test_all_incidents(client, sample_incidents):
    """Test all incidents endpoint."""
    response = client.get("/incidents/all")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 2


def test_specific_incident(client, sample_incidents):
    """Test specific incident endpoint."""
    response = client.get("/incidents/INC001")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["data"]["incident_id"] == "INC001"


def test_incident_not_found(client):
    """Test incident not found."""
    response = client.get("/incidents/NONEXISTENT")
    assert response.status_code == 404


def test_cache_error():
    """Test cache error handling."""
    # Create a special mock that raises an exception
    error_cache = MagicMock()
    error_cache.get_active_incidents.side_effect = Exception("Cache error")

    # Override dependency for this specific test
    app.dependency_overrides[get_cache] = lambda: error_cache

    try:
        with TestClient(app) as test_client:
            response = test_client.get("/incidents/active")
            assert response.status_code == 500
    finally:
        app.dependency_overrides = {}  # Cleanup


def test_pagination_params(client):
    """Test pagination parameter validation."""
    # Invalid limit
    response = client.get("/incidents/active?limit=0")
    assert response.status_code == 422

    # Invalid offset
    response = client.get("/incidents/active?offset=-1")
    assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__])