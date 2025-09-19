"""Shared test fixtures for Seattle API tests."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seattle_api.api_models import HealthResponse
from seattle_api.models import Incident, IncidentStatus
from seattle_api.routes import incidents_router
from seattle_api.routes.incidents import get_cache


def create_test_app() -> FastAPI:
    """Create a lightweight FastAPI test app without production lifespan dependencies.

    This app avoids expensive startup operations like:
    - HTTP client initialization
    - Background polling services
    - Network connections
    - Database connections
    """
    test_app = FastAPI(
        title="Test Seattle Fire Department Incident API",
        description="Test API service for Seattle Fire Department live incident data",
        version="1.0.0",
        # No lifespan parameter - this avoids the expensive startup/shutdown
    )

    # Include incident routes
    test_app.include_router(incidents_router)

    # Add basic health endpoint for testing
    @test_app.get("/health", response_model=HealthResponse)
    async def health_check() -> HealthResponse:
        return HealthResponse(
            status="healthy",
            service="seattle-fire-api",
            version="1.0.0",
            config={
                "polling_interval_minutes": 5,
                "cache_retention_hours": 24,
                "server_port": 8000,
                "server_host": "0.0.0.0",
            },
            poller_status=None,
        )

    @test_app.get("/")
    async def root():
        return {
            "message": "Test Seattle Fire Department Incident API",
            "version": "1.0.0",
            "description": "Test API service for Seattle Fire Department live incident data",
        }

    return test_app


@pytest.fixture(scope="session")
def sample_incidents():
    """Sample incidents data used across multiple test files."""
    return [
        Incident(
            incident_id="FIRE001",
            incident_datetime=datetime(2023, 12, 25, 22, 30, 45, tzinfo=UTC),
            priority=3,
            units=["E16", "L9", "BC4"],
            address="123 Main St, Seattle",
            incident_type="Structure Fire",
            status=IncidentStatus.ACTIVE,
            first_seen=datetime(2023, 12, 25, 22, 30, 45, tzinfo=UTC),
            last_seen=datetime(2023, 12, 25, 22, 35, 45, tzinfo=UTC),
        ),
        Incident(
            incident_id="MED001",
            incident_datetime=datetime(2023, 12, 25, 23, 15, 30, tzinfo=UTC),
            priority=5,
            units=["M32", "E25"],
            address="456 Pine Ave, Bellevue",
            incident_type="Aid Response",
            status=IncidentStatus.ACTIVE,
            first_seen=datetime(2023, 12, 25, 23, 15, 30, tzinfo=UTC),
            last_seen=datetime(2023, 12, 25, 23, 20, 30, tzinfo=UTC),
        ),
        Incident(
            incident_id="FIRE002",
            incident_datetime=datetime(2023, 12, 25, 20, 45, 15, tzinfo=UTC),
            priority=2,
            units=["E10", "L6"],
            address="789 Oak Blvd, Seattle",
            incident_type="Brush Fire",
            status=IncidentStatus.CLOSED,
            first_seen=datetime(2023, 12, 25, 20, 45, 15, tzinfo=UTC),
            last_seen=datetime(2023, 12, 25, 21, 15, 15, tzinfo=UTC),
            closed_at=datetime(2023, 12, 25, 21, 15, 15, tzinfo=UTC),
        ),
        Incident(
            incident_id="ALARM001",
            incident_datetime=datetime(2023, 12, 26, 8, 30, 0, tzinfo=UTC),
            priority=7,
            units=["E8"],
            address="321 First St, Redmond",
            incident_type="Alarm Response",
            status=IncidentStatus.ACTIVE,
            first_seen=datetime(2023, 12, 26, 8, 30, 0, tzinfo=UTC),
            last_seen=datetime(2023, 12, 26, 8, 45, 0, tzinfo=UTC),
        ),
        Incident(
            incident_id="RESCUE001",
            incident_datetime=datetime(2023, 12, 24, 14, 20, 0, tzinfo=UTC),
            priority=4,
            units=["L12", "BC2"],
            address="555 Water St, Seattle",
            incident_type="Water Rescue",
            status=IncidentStatus.CLOSED,
            first_seen=datetime(2023, 12, 24, 14, 20, 0, tzinfo=UTC),
            last_seen=datetime(2023, 12, 24, 15, 30, 0, tzinfo=UTC),
            closed_at=datetime(2023, 12, 24, 15, 30, 0, tzinfo=UTC),
        ),
    ]


@pytest.fixture(scope="session")
def mock_cache(sample_incidents):
    """Mock cache that returns sample data - session scoped for performance."""
    cache = MagicMock()
    cache.get_all_incidents.return_value = sample_incidents
    cache.get_active_incidents.return_value = [
        i for i in sample_incidents if i.status == IncidentStatus.ACTIVE
    ]
    cache.get_incident.side_effect = lambda incident_id: next(
        (i for i in sample_incidents if i.incident_id == incident_id), None
    )
    return cache


@pytest.fixture(scope="session")
def test_client(mock_cache):
    """Session-scoped test client with mocked dependencies for optimal performance.

    This fixture provides a FastAPI test client that:
    - Uses a lightweight test app (no expensive lifespan operations)
    - Is session-scoped to avoid repeated app startup/shutdown
    - Has mocked cache dependencies
    - Provides significant performance improvements for endpoint testing
    """
    test_app = create_test_app()
    test_app.dependency_overrides[get_cache] = lambda: mock_cache

    with TestClient(test_app) as client:
        yield client

    # Clean up dependency overrides
    test_app.dependency_overrides = {}


# Convenience fixture aliases for backward compatibility
@pytest.fixture(scope="session")
def client(test_client):
    """Alias for test_client fixture for backward compatibility."""
    return test_client