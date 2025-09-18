"""Tests for main FastAPI application."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from seattle_api.main import app


@pytest.fixture
def client():
    """Create test client for FastAPI app."""
    return TestClient(app)


class TestFastAPIApp:
    """Test cases for FastAPI application."""

    @patch("seattle_api.main.poller")
    def test_health_check_endpoint(self, mock_poller, client):
        """Test health check endpoint returns correct response."""
        # Mock a healthy poller
        mock_poller.get_health_status.return_value = {"status": "healthy"}

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["service"] == "seattle-fire-api"
        assert data["version"] == "1.0.0"
        assert "config" in data
        assert "polling_interval_minutes" in data["config"]
        assert "cache_retention_hours" in data["config"]
        assert "server_port" in data["config"]

    def test_root_endpoint(self, client):
        """Test root endpoint returns service information."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert data["message"] == "Seattle Fire Department Incident API"
        assert data["version"] == "1.0.0"
        assert "endpoints" in data
        assert data["endpoints"]["health"] == "/health"
        assert data["endpoints"]["docs"] == "/docs"
        assert data["endpoints"]["redoc"] == "/redoc"

    def test_health_check_includes_config_values(self, client):
        """Test health check includes actual configuration values."""
        response = client.get("/health")
        data = response.json()

        config_data = data["config"]
        assert isinstance(config_data["polling_interval_minutes"], int)
        assert isinstance(config_data["cache_retention_hours"], int)
        assert isinstance(config_data["server_port"], int)
        assert config_data["polling_interval_minutes"] > 0
        assert config_data["cache_retention_hours"] > 0
        assert config_data["server_port"] > 0

    @patch("seattle_api.main.config")
    def test_health_check_with_custom_config(self, mock_config, client):
        """Test health check with custom configuration values."""
        # Mock configuration
        mock_config.polling_interval_minutes = 10
        mock_config.cache_retention_hours = 48
        mock_config.server_port = 9000

        response = client.get("/health")
        data = response.json()

        config_data = data["config"]
        assert config_data["polling_interval_minutes"] == 10
        assert config_data["cache_retention_hours"] == 48
        assert config_data["server_port"] == 9000


class TestLifespan:
    """Test cases for application lifespan management."""

    @patch("seattle_api.main.IncidentPoller")
    @patch("seattle_api.main.SeattleHTTPClient")
    @patch("seattle_api.main.IncidentCache")
    @patch("seattle_api.main.logger")
    @patch("seattle_api.main.config")
    def test_lifespan_startup_logging(
        self,
        mock_config,
        mock_logger,
        mock_cache_cls,
        mock_http_client_cls,
        mock_poller_cls,
    ):
        """Test that startup events are logged correctly."""
        mock_config.polling_interval_minutes = 5
        mock_config.cache_retention_hours = 24
        mock_config.server_port = 8000
        mock_config.seattle_endpoint = "http://test.example.com"
        mock_config.server_host = "localhost"
        mock_config.log_level = "INFO"
        mock_config.validate = MagicMock()

        # Mock the instances
        mock_cache = MagicMock()
        mock_cache.stop_background_cleanup = MagicMock()
        mock_cache_cls.return_value = mock_cache

        mock_http_client = MagicMock()
        mock_http_client.start = AsyncMock()
        mock_http_client.close = AsyncMock()
        mock_http_client_cls.return_value = mock_http_client

        mock_poller = MagicMock()
        mock_poller.start_polling = AsyncMock()
        mock_poller.shutdown = AsyncMock()
        mock_poller_cls.return_value = mock_poller

        # Test client creation triggers lifespan events
        with TestClient(app):
            pass

        # Verify startup logging calls
        mock_logger.info.assert_any_call("Starting Seattle Fire Department API service")
        mock_logger.info.assert_any_call("Configuration validation passed")
        mock_logger.info.assert_any_call(
            "Shutting down Seattle Fire Department API service"
        )

        # Verify config validation was called
        mock_config.validate.assert_called_once()

    @patch("seattle_api.main.logger")
    @patch("seattle_api.main.config")
    def test_lifespan_config_validation_failure(self, mock_config, mock_logger):
        """Test that configuration validation failures are handled."""
        mock_config.validate = MagicMock(side_effect=ValueError("Invalid config"))

        # Should raise the validation error
        with pytest.raises(ValueError, match="Invalid config"):
            with TestClient(app):
                pass

        # Verify error logging
        mock_logger.error.assert_called_with(
            "Configuration validation failed: Invalid config"
        )
