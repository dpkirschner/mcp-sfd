"""Tests for configuration management."""

import os
from unittest.mock import patch

import pytest

from seattle_api.config import FastAPIConfig


class TestFastAPIConfig:
    """Test cases for FastAPIConfig class."""

    def test_default_config_values(self):
        """Test that default configuration values are set correctly."""
        config = FastAPIConfig()

        assert config.polling_interval_minutes == 5
        assert (
            config.seattle_endpoint
            == "https://web.seattle.gov/sfd/realtime911/getRecsForDatePub.asp?action=Today&incDate=&rad1=des"
        )
        assert config.cache_retention_hours == 24
        assert config.server_port == 8000
        assert config.server_host == "0.0.0.0"
        assert config.log_level == "INFO"

    def test_config_from_env_with_defaults(self):
        """Test configuration creation from environment with default values."""
        with patch.dict(os.environ, {}, clear=True):
            config = FastAPIConfig.from_env()

            assert config.polling_interval_minutes == 5
            assert config.cache_retention_hours == 24
            assert config.server_port == 8000
            assert config.server_host == "0.0.0.0"
            assert config.log_level == "INFO"

    def test_config_from_env_with_custom_values(self):
        """Test configuration creation from environment with custom values."""
        env_vars = {
            "POLLING_INTERVAL_MINUTES": "10",
            "SEATTLE_ENDPOINT_URL": "https://custom.endpoint.com",
            "CACHE_RETENTION_HOURS": "48",
            "SERVER_PORT": "9000",
            "SERVER_HOST": "127.0.0.1",
            "LOG_LEVEL": "DEBUG",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = FastAPIConfig.from_env()

            assert config.polling_interval_minutes == 10
            assert config.seattle_endpoint == "https://custom.endpoint.com"
            assert config.cache_retention_hours == 48
            assert config.server_port == 9000
            assert config.server_host == "127.0.0.1"
            assert config.log_level == "DEBUG"

    def test_config_validation_success(self):
        """Test successful configuration validation."""
        config = FastAPIConfig(
            polling_interval_minutes=5,
            seattle_endpoint="https://valid.endpoint.com",
            cache_retention_hours=24,
            server_port=8000,
            server_host="0.0.0.0",
            log_level="INFO",
        )

        # Should not raise any exception
        config.validate()

    def test_config_validation_invalid_polling_interval(self):
        """Test configuration validation with invalid polling interval."""
        config = FastAPIConfig(polling_interval_minutes=0)

        with pytest.raises(ValueError, match="Polling interval must be positive"):
            config.validate()

    def test_config_validation_invalid_cache_retention(self):
        """Test configuration validation with invalid cache retention."""
        config = FastAPIConfig(cache_retention_hours=-1)

        with pytest.raises(ValueError, match="Cache retention hours must be positive"):
            config.validate()

    def test_config_validation_empty_endpoint(self):
        """Test configuration validation with empty endpoint."""
        config = FastAPIConfig(seattle_endpoint="")

        with pytest.raises(ValueError, match="Seattle endpoint URL is required"):
            config.validate()

    def test_config_validation_invalid_port_zero(self):
        """Test configuration validation with port zero."""
        config = FastAPIConfig(server_port=0)

        with pytest.raises(ValueError, match="Server port must be between 1 and 65535"):
            config.validate()

    def test_config_validation_invalid_port_too_high(self):
        """Test configuration validation with port too high."""
        config = FastAPIConfig(server_port=70000)

        with pytest.raises(ValueError, match="Server port must be between 1 and 65535"):
            config.validate()
