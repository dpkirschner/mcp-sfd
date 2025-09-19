"""Simple tests for FastAPI incident endpoints."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from seattle_api.models import Incident, IncidentStatus
from seattle_api.routes.incidents import get_cache
from .conftest import create_test_app


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


def test_active_incidents(client):
    """Test active incidents endpoint."""
    response = client.get("/incidents/active")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 3  # FIRE001, MED001, ALARM001 are active
    # Check that we get incident IDs (order may vary)
    incident_ids = [incident["incident_id"] for incident in data["data"]]
    assert "FIRE001" in incident_ids


def test_all_incidents(client):
    """Test all incidents endpoint."""
    response = client.get("/incidents/all")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 5  # All 5 incidents from shared data


def test_specific_incident(client):
    """Test specific incident endpoint."""
    response = client.get("/incidents/FIRE001")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["data"]["incident_id"] == "FIRE001"


def test_incident_not_found(client):
    """Test incident not found."""
    response = client.get("/incidents/NONEXISTENT")
    assert response.status_code == 404


def test_cache_error():
    """Test cache error handling."""
    # Create a special mock that raises an exception
    error_cache = MagicMock()
    error_cache.get_active_incidents.side_effect = Exception("Cache error")

    # Create test app for this specific test
    test_app = create_test_app()
    test_app.dependency_overrides[get_cache] = lambda: error_cache

    try:
        with TestClient(test_app) as test_client:
            response = test_client.get("/incidents/active")
            assert response.status_code == 500
    finally:
        test_app.dependency_overrides = {}  # Cleanup


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
