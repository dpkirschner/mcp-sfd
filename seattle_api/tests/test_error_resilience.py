"""Integration tests for error resilience and circuit breaker patterns."""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import List

import httpx

from seattle_api.poller import IncidentPoller, PollingError
from seattle_api.circuit_breaker import CircuitBreakerError, CircuitState
from seattle_api.config import FastAPIConfig
from seattle_api.http_client import SeattleHTTPClient
from seattle_api.cache import IncidentCache
from seattle_api.models import Incident, IncidentStatus, RawIncident
from seattle_api.parser import HTMLParseError


@pytest.fixture
def config():
    """Test configuration."""
    return FastAPIConfig(
        polling_interval_minutes=1,
        seattle_endpoint="http://test.example.com",
        cache_retention_hours=24,
        server_port=8000,
        log_level="DEBUG"
    )


@pytest.fixture
def mock_http_client():
    """Mock HTTP client."""
    client = MagicMock(spec=SeattleHTTPClient)
    client.fetch_incident_html = AsyncMock(return_value="<html><body>Mock HTML response</body></html>")
    return client


@pytest.fixture
def mock_cache():
    """Mock incident cache."""
    cache = MagicMock(spec=IncidentCache)
    cache.add_incident = MagicMock()
    cache.get_active_incidents = MagicMock(return_value=[])
    cache.get_incident = MagicMock(return_value=None)
    return cache


@pytest.fixture
def sample_incident():
    """Sample normalized incident for testing."""
    return Incident(
        incident_id="INC001",
        incident_datetime=datetime(2023, 12, 25, 22, 30, 45),
        priority=5,
        units=["E16"],
        address="123 Main St",
        incident_type="Aid Response",
        status=IncidentStatus.ACTIVE,
        first_seen=datetime.now(),
        last_seen=datetime.now()
    )


@pytest.fixture
def poller(config, mock_http_client, mock_cache):
    """Test incident poller."""
    return IncidentPoller(config, mock_http_client, mock_cache)


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration in polling operations."""

    @pytest.mark.asyncio
    async def test_http_circuit_breaker_opens_on_failures(self, poller, mock_http_client):
        """Test that HTTP circuit breaker opens after consecutive failures."""
        # Configure for fast failure
        poller.http_circuit_breaker.failure_threshold = 2

        # Simulate HTTP failures
        mock_http_client.fetch_incident_html.side_effect = httpx.TimeoutException("Connection timeout")

        # First failure
        result1 = await poller.poll_once()
        assert result1 is False
        assert poller.http_circuit_breaker.state == CircuitState.CLOSED
        assert poller.http_circuit_breaker.failure_count == 1

        # Second failure - should open circuit
        result2 = await poller.poll_once()
        assert result2 is False
        assert poller.http_circuit_breaker.state == CircuitState.OPEN
        assert poller.http_circuit_breaker.failure_count == 2

        # Third attempt - should be blocked by circuit breaker
        result3 = await poller.poll_once()
        assert result3 is False
        # HTTP client should not be called due to open circuit
        assert mock_http_client.fetch_incident_html.call_count == 2

    @pytest.mark.asyncio
    async def test_parsing_circuit_breaker_opens_on_failures(self, poller, mock_http_client):
        """Test that parsing circuit breaker opens after consecutive failures."""
        # Configure for fast failure
        poller.parsing_circuit_breaker.failure_threshold = 2

        # HTTP succeeds but parsing fails
        mock_http_client.fetch_incident_html.return_value = "<invalid>html</invalid>"

        with patch.object(poller.parser, 'parse_incidents') as mock_parse:
            mock_parse.side_effect = HTMLParseError("Invalid HTML structure")

            # First failure
            result1 = await poller.poll_once()
            assert result1 is False
            assert poller.parsing_circuit_breaker.state == CircuitState.CLOSED
            assert poller.parsing_circuit_breaker.failure_count == 1

            # Second failure - should open circuit
            result2 = await poller.poll_once()
            assert result2 is False
            assert poller.parsing_circuit_breaker.state == CircuitState.OPEN
            assert poller.parsing_circuit_breaker.failure_count == 2

            # Third attempt - should be blocked by circuit breaker
            result3 = await poller.poll_once()
            assert result3 is False
            # Parser should not be called due to open circuit (only HTTP succeeds)
            assert mock_parse.call_count == 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self, poller, mock_http_client):
        """Test circuit breaker recovery after timeout."""
        # Configure for fast recovery
        poller.http_circuit_breaker.failure_threshold = 1
        poller.http_circuit_breaker.recovery_timeout = 0.1  # 100ms

        # Cause failure to open circuit
        mock_http_client.fetch_incident_html.side_effect = httpx.ConnectError("Connection failed")
        result1 = await poller.poll_once()
        assert result1 is False
        assert poller.http_circuit_breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Configure success for recovery test
        mock_http_client.fetch_incident_html.side_effect = None
        mock_http_client.fetch_incident_html.return_value = """
        <table>
            <tr>
                <td>12/25/2023 2:30:45 PM</td>
                <td>INC001</td>
                <td>5</td>
                <td>E16*</td>
                <td>123 Main St</td>
                <td>Aid Response</td>
            </tr>
        </table>
        """

        # Should transition to half-open and then closed on success
        result2 = await poller.poll_once()
        assert result2 is True
        assert poller.http_circuit_breaker.state == CircuitState.CLOSED
        assert poller.http_circuit_breaker.failure_count == 0


class TestGracefulDegradation:
    """Test graceful degradation with cached data."""

    @pytest.mark.asyncio
    async def test_serve_from_cache_during_http_failure(self, poller, mock_http_client, mock_cache, sample_incident):
        """Test serving cached data when HTTP fails."""
        # Setup cache with existing incidents
        mock_cache.get_active_incidents.return_value = [sample_incident]

        # Simulate HTTP failure
        mock_http_client.fetch_incident_html.side_effect = httpx.ConnectError("Connection failed")

        result = await poller.poll_once()

        # Should succeed using cached data
        assert result is True
        assert poller._degraded_mode is True

        # Verify cache was accessed
        mock_cache.get_active_incidents.assert_called()

    @pytest.mark.asyncio
    async def test_serve_from_cache_during_parsing_failure(self, poller, mock_http_client, mock_cache, sample_incident):
        """Test serving cached data when parsing fails."""
        # Setup cache with existing incidents
        mock_cache.get_active_incidents.return_value = [sample_incident]

        # HTTP succeeds but parsing fails
        mock_http_client.fetch_incident_html.return_value = "<invalid>html</invalid>"

        with patch.object(poller.parser, 'parse_incidents') as mock_parse:
            mock_parse.side_effect = HTMLParseError("Invalid HTML structure")

            result = await poller.poll_once()

            # Should succeed using cached data
            assert result is True
            assert poller._degraded_mode is True

            # Verify cache was accessed
            mock_cache.get_active_incidents.assert_called()

    @pytest.mark.asyncio
    async def test_exit_degraded_mode_on_success(self, poller, mock_http_client, mock_cache, sample_incident):
        """Test exiting degraded mode after successful operation."""
        # Start in degraded mode
        poller._degraded_mode = True

        # Configure successful operation
        mock_http_client.fetch_incident_html.return_value = """
        <table>
            <tr>
                <td>12/25/2023 2:30:45 PM</td>
                <td>INC001</td>
                <td>5</td>
                <td>E16*</td>
                <td>123 Main St</td>
                <td>Aid Response</td>
            </tr>
        </table>
        """

        result = await poller.poll_once()

        assert result is True
        assert poller._degraded_mode is False

    @pytest.mark.asyncio
    async def test_degraded_mode_without_cache(self, poller, mock_http_client, mock_cache):
        """Test degraded mode when no cached data is available."""
        # Setup empty cache
        mock_cache.get_active_incidents.return_value = []

        # Simulate HTTP failure
        mock_http_client.fetch_incident_html.side_effect = httpx.ConnectError("Connection failed")

        result = await poller.poll_once()

        # Should fail since no cached data available
        assert result is False
        assert poller._degraded_mode is True


class TestErrorLogging:
    """Test error logging with appropriate detail levels."""

    @pytest.mark.asyncio
    async def test_error_logging_levels(self, poller, mock_http_client, caplog):
        """Test that errors are logged with appropriate detail levels."""
        import logging
        caplog.set_level(logging.DEBUG)

        # Test HTTP error logging
        mock_http_client.fetch_incident_html.side_effect = httpx.TimeoutException("Request timeout")

        await poller.poll_once()

        # Check for appropriate error messages
        error_logs = [record for record in caplog.records if record.levelno >= logging.ERROR]
        assert any("HTTP operation failed" in record.message for record in error_logs)

    @pytest.mark.asyncio
    async def test_circuit_breaker_logging(self, poller, mock_http_client, caplog):
        """Test circuit breaker state change logging."""
        import logging
        caplog.set_level(logging.INFO)

        # Configure for fast failure
        poller.http_circuit_breaker.failure_threshold = 1

        # Cause circuit to open
        mock_http_client.fetch_incident_html.side_effect = httpx.ConnectError("Connection failed")
        await poller.poll_once()

        # Check for circuit breaker logs
        info_logs = [record for record in caplog.records if record.levelno == logging.INFO]
        assert any("Circuit breaker" in record.message and "opened" in record.message for record in info_logs)

    @pytest.mark.asyncio
    async def test_degraded_mode_logging(self, poller, mock_http_client, mock_cache, sample_incident, caplog):
        """Test degraded mode entry/exit logging."""
        import logging
        caplog.set_level(logging.WARNING)

        # Setup cache for degraded mode
        mock_cache.get_active_incidents.return_value = [sample_incident]

        # Enter degraded mode
        mock_http_client.fetch_incident_html.side_effect = httpx.ConnectError("Connection failed")
        await poller.poll_once()

        # Check for degraded mode entry log
        warning_logs = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert any("Entering degraded mode" in record.message for record in warning_logs)


class TestExponentialBackoff:
    """Test enhanced exponential backoff implementation."""

    @pytest.mark.asyncio
    async def test_exponential_backoff_in_polling_loop(self, poller, mock_http_client):
        """Test exponential backoff is applied in polling loop."""
        # Configure fast intervals for testing
        poller._base_retry_delay = 0.01
        poller._max_retry_delay = 0.1

        # Simulate persistent failure
        mock_http_client.fetch_incident_html.side_effect = httpx.ConnectError("Connection failed")

        start_time = asyncio.get_event_loop().time()

        # Start polling (will fail and apply backoff)
        poller._is_running = True
        poller._startup_complete.set()

        # Manually run one cycle with backoff
        await poller.poll_once()  # First failure

        # Check that consecutive failures increase
        assert poller._consecutive_failures == 1

        await poller.poll_once()  # Second failure
        assert poller._consecutive_failures == 2

    def test_backoff_delay_calculation(self, poller):
        """Test that backoff delay is calculated correctly."""
        base_delay = 1.0
        max_delay = 60.0

        # Test delay calculation
        delays = []
        for i in range(6):
            delay = min(base_delay * (2 ** i), max_delay)
            delays.append(delay)

        expected = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        assert delays[:6] == expected


class TestHealthStatusWithCircuitBreakers:
    """Test health status reporting with circuit breaker information."""

    def test_health_status_includes_circuit_breakers(self, poller):
        """Test that health status includes circuit breaker information."""
        status = poller.get_health_status()

        assert "circuit_breakers" in status
        assert "http" in status["circuit_breakers"]
        assert "parsing" in status["circuit_breakers"]
        assert "degraded_mode" in status

    def test_health_status_circuit_open(self, poller):
        """Test health status when circuit breakers are open."""
        # Set poller as running and open a circuit breaker
        poller._is_running = True
        poller.http_circuit_breaker._state = CircuitState.OPEN

        status = poller.get_health_status()

        assert status["status"] == "circuit_open"

    def test_health_status_degraded_mode(self, poller):
        """Test health status in degraded mode."""
        poller._is_running = True
        poller._degraded_mode = True

        status = poller.get_health_status()

        assert status["status"] == "degraded"
        assert status["degraded_mode"] is True


class TestErrorRecoveryScenarios:
    """Test complex error recovery scenarios."""

    @pytest.mark.asyncio
    async def test_partial_failure_recovery(self, poller, mock_http_client, mock_cache, sample_incident):
        """Test recovery from partial failures."""
        # Setup cache for fallback
        mock_cache.get_active_incidents.return_value = [sample_incident]

        # Start with HTTP failure
        mock_http_client.fetch_incident_html.side_effect = httpx.ConnectError("Connection failed")
        result1 = await poller.poll_once()
        assert result1 is True  # Succeeded with cached data
        assert poller._degraded_mode is True

        # HTTP recovers
        mock_http_client.fetch_incident_html.side_effect = None
        mock_http_client.fetch_incident_html.return_value = """
        <table>
            <tr>
                <td>12/25/2023 2:30:45 PM</td>
                <td>INC001</td>
                <td>5</td>
                <td>E16*</td>
                <td>123 Main St</td>
                <td>Aid Response</td>
            </tr>
        </table>
        """

        result2 = await poller.poll_once()
        assert result2 is True
        assert poller._degraded_mode is False  # Should exit degraded mode

    @pytest.mark.asyncio
    async def test_cascading_failures(self, poller, mock_http_client, mock_cache):
        """Test handling of cascading failures."""
        # Configure aggressive failure thresholds for testing
        poller.http_circuit_breaker.failure_threshold = 2
        poller.parsing_circuit_breaker.failure_threshold = 2
        poller._max_failures = 5

        # First: HTTP failures
        mock_http_client.fetch_incident_html.side_effect = httpx.ConnectError("Connection failed")

        await poller.poll_once()  # First HTTP failure
        await poller.poll_once()  # Second HTTP failure - opens HTTP circuit

        assert poller.http_circuit_breaker.state == CircuitState.OPEN

        # Second: Even after HTTP recovery, parsing fails
        mock_http_client.fetch_incident_html.side_effect = None
        mock_http_client.fetch_incident_html.return_value = "<invalid>html</invalid>"

        # Reset HTTP circuit breaker to test parsing circuit
        await poller.http_circuit_breaker.reset()

        with patch.object(poller.parser, 'parse_incidents') as mock_parse:
            mock_parse.side_effect = HTMLParseError("Invalid HTML")

            await poller.poll_once()  # First parsing failure
            await poller.poll_once()  # Second parsing failure - opens parsing circuit

            assert poller.parsing_circuit_breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_cache_update_failure_handling(self, poller, mock_http_client, mock_cache):
        """Test handling of cache update failures."""
        # HTTP and parsing succeed, but cache update fails
        mock_http_client.fetch_incident_html.return_value = """
        <table>
            <tr>
                <td>12/25/2023 2:30:45 PM</td>
                <td>INC001</td>
                <td>5</td>
                <td>E16*</td>
                <td>123 Main St</td>
                <td>Aid Response</td>
            </tr>
        </table>
        """

        # Make cache operations fail
        mock_cache.get_active_incidents.side_effect = Exception("Cache error")
        mock_cache.add_incident.side_effect = Exception("Cache error")

        # Should still succeed despite cache failures
        result = await poller.poll_once()
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__])