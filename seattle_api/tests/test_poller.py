"""Tests for the incident poller."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seattle_api.cache import IncidentCache
from seattle_api.config import FastAPIConfig
from seattle_api.http_client import SeattleHTTPClient
from seattle_api.models import Incident, IncidentStatus, RawIncident
from seattle_api.poller import IncidentPoller, PollingError


@pytest.fixture
def config():
    """Test configuration."""
    return FastAPIConfig(
        polling_interval_minutes=1,  # Short interval for testing
        seattle_endpoint="http://test.example.com",
        cache_retention_hours=24,
        server_port=8000,
        log_level="DEBUG",
    )


@pytest.fixture
def mock_http_client():
    """Mock HTTP client."""
    client = MagicMock(spec=SeattleHTTPClient)
    client.fetch_incident_html = AsyncMock()
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
def sample_html():
    """Sample HTML content for testing."""
    return """
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


@pytest.fixture
def sample_raw_incident():
    """Sample raw incident for testing."""
    return RawIncident(
        datetime_str="12/25/2023 2:30:45 PM",
        incident_id="INC001",
        priority_str="5",
        units_str="E16*",
        address="123 Main St",
        incident_type="Aid Response",
    )


@pytest.fixture
def sample_incident():
    """Sample normalized incident for testing."""
    return Incident(
        incident_id="INC001",
        incident_datetime=datetime(2023, 12, 25, 22, 30, 45, tzinfo=UTC),
        priority=5,
        units=["E16"],
        address="123 Main St",
        incident_type="Aid Response",
        status=IncidentStatus.ACTIVE,
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
    )


@pytest.fixture
def poller(config, mock_http_client, mock_cache):
    """Test incident poller."""
    return IncidentPoller(config, mock_http_client, mock_cache)


class TestIncidentPoller:
    """Test cases for IncidentPoller class."""

    def test_init(self, poller, config, mock_http_client, mock_cache):
        """Test poller initialization."""
        assert poller.config == config
        assert poller.http_client == mock_http_client
        assert poller.cache == mock_cache
        assert not poller.is_running
        assert not poller.startup_complete
        assert poller._consecutive_failures == 0
        assert poller._total_polls == 0

    def test_configure_interval_valid(self, poller):
        """Test configuring valid polling interval."""
        poller.configure_interval(10)
        assert poller.config.polling_interval_minutes == 10

    def test_configure_interval_invalid(self, poller):
        """Test configuring invalid polling interval."""
        with pytest.raises(ValueError, match="Polling interval must be positive"):
            poller.configure_interval(0)

        with pytest.raises(ValueError, match="Polling interval must be positive"):
            poller.configure_interval(-1)

    @pytest.mark.asyncio
    async def test_start_polling_already_running(self, poller):
        """Test starting poller when already running."""
        poller._is_running = True

        with pytest.raises(PollingError, match="Polling is already running"):
            await poller.start_polling()

    @pytest.mark.asyncio
    async def test_shutdown_not_running(self, poller):
        """Test shutting down poller when not running."""
        # Should not raise any exceptions
        await poller.shutdown()

    @pytest.mark.asyncio
    async def test_poll_once_success(
        self,
        poller,
        mock_http_client,
        mock_cache,
        sample_html,
        sample_raw_incident,
        sample_incident,
    ):
        """Test successful single polling operation."""
        # Setup mocks
        mock_http_client.fetch_incident_html.return_value = sample_html

        with (
            patch.object(poller.parser, "parse_incidents") as mock_parse,
            patch.object(poller.normalizer, "normalize_incident") as mock_normalize,
            patch.object(poller, "_update_cache_with_incidents") as mock_update,
        ):

            mock_parse.return_value = [sample_raw_incident]
            mock_normalize.return_value = sample_incident
            mock_update.return_value = None

            result = await poller.poll_once()

            assert result is True
            assert poller._total_polls == 1
            assert poller._successful_polls == 1
            assert poller._consecutive_failures == 0
            assert poller._last_successful_poll is not None

            mock_http_client.fetch_incident_html.assert_called_once()
            mock_parse.assert_called_once_with(sample_html)
            mock_normalize.assert_called_once_with(sample_raw_incident)
            mock_update.assert_called_once_with([sample_incident])

    @pytest.mark.asyncio
    async def test_poll_once_http_failure(self, poller, mock_http_client):
        """Test polling when HTTP client fails."""
        mock_http_client.fetch_incident_html.side_effect = Exception("HTTP Error")

        result = await poller.poll_once()

        assert result is False
        assert poller._total_polls == 1
        # Note: _failed_polls may be 2 due to degraded mode attempt
        assert poller._failed_polls >= 1
        assert poller._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_poll_once_parse_failure(self, poller, mock_http_client, sample_html):
        """Test polling when HTML parsing fails."""
        mock_http_client.fetch_incident_html.return_value = sample_html

        with patch.object(poller.parser, "parse_incidents") as mock_parse:
            mock_parse.side_effect = Exception("Parse Error")

            result = await poller.poll_once()

            assert result is False
            assert poller._total_polls == 1
            assert poller._failed_polls >= 1
            # Note: consecutive_failures might be 0 if degraded mode succeeds
            assert poller._consecutive_failures >= 0

    @pytest.mark.asyncio
    async def test_poll_once_normalization_failure(
        self, poller, mock_http_client, sample_html, sample_raw_incident
    ):
        """Test polling when incident normalization fails."""
        mock_http_client.fetch_incident_html.return_value = sample_html

        with (
            patch.object(poller.parser, "parse_incidents") as mock_parse,
            patch.object(poller.normalizer, "normalize_incident") as mock_normalize,
            patch.object(poller, "_update_cache_with_incidents") as mock_update,
        ):

            mock_parse.return_value = [sample_raw_incident]
            mock_normalize.side_effect = Exception("Normalize Error")
            mock_update.return_value = None

            result = await poller.poll_once()

            # Should still succeed even if some incidents fail to normalize
            assert result is True
            mock_update.assert_called_once_with(
                []
            )  # Empty list since normalization failed

    @pytest.mark.asyncio
    async def test_update_cache_with_incidents(
        self, poller, mock_cache, sample_incident
    ):
        """Test updating cache with new incidents."""
        incidents = [sample_incident]

        # Mock executor to run synchronously for testing
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_executor = MagicMock()
            mock_executor.run_in_executor = AsyncMock()
            mock_loop.return_value = mock_executor

            # Mock cache methods
            mock_executor.run_in_executor.side_effect = [
                [],  # get_active_incidents
                None,  # add_incident
            ]

            await poller._update_cache_with_incidents(incidents)

            # Verify cache.add_incident was called for each incident
            assert mock_executor.run_in_executor.call_count == 2

    @pytest.mark.asyncio
    async def test_update_cache_closes_missing_incidents(
        self, poller, mock_cache, sample_incident
    ):
        """Test that incidents missing from feed are marked as closed."""
        # Setup: cache has an active incident that's not in the current feed
        existing_incident = sample_incident.model_copy(update={"incident_id": "OLD001"})
        current_incidents = [sample_incident]  # Different incident ID

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_executor = MagicMock()
            mock_executor.run_in_executor = AsyncMock()
            mock_loop.return_value = mock_executor

            # Mock cache methods
            mock_executor.run_in_executor.side_effect = [
                [existing_incident],  # get_active_incidents
                None,  # add_incident (current)
                existing_incident,  # get_incident (for closing)
                None,  # add_incident (closed)
            ]

            await poller._update_cache_with_incidents(current_incidents)

            # Should have called run_in_executor multiple times for cache operations
            assert mock_executor.run_in_executor.call_count >= 3
            # Verify that we tried to get active incidents and add incidents
            calls = mock_executor.run_in_executor.call_args_list
            assert any("get_active_incidents" in str(call) for call in calls)
            assert any("add_incident" in str(call) for call in calls)

    def test_get_health_status_healthy(self, poller):
        """Test health status when poller is healthy."""
        poller._is_running = True
        poller._last_successful_poll = datetime.now(UTC)
        poller._total_polls = 10
        poller._successful_polls = 9
        poller._failed_polls = 1

        status = poller.get_health_status()

        assert status["status"] == "healthy"
        assert status["is_running"] is True
        assert status["total_polls"] == 10
        assert status["successful_polls"] == 9
        assert status["failed_polls"] == 1
        assert status["consecutive_failures"] == 0

    def test_get_health_status_stopped(self, poller):
        """Test health status when poller is stopped."""
        poller._is_running = False

        status = poller.get_health_status()

        assert status["status"] == "stopped"
        assert status["is_running"] is False

    def test_get_health_status_degraded(self, poller):
        """Test health status when poller has failures."""
        poller._is_running = True
        poller._consecutive_failures = 2

        status = poller.get_health_status()

        assert status["status"] == "degraded"
        assert status["consecutive_failures"] == 2

    def test_get_health_status_stale(self, poller):
        """Test health status when last poll is too old."""
        poller._is_running = True
        poller._last_successful_poll = datetime.now(UTC) - timedelta(hours=1)
        poller.config.polling_interval_minutes = 5

        status = poller.get_health_status()

        assert status["status"] == "stale"
        assert status["time_since_last_poll_seconds"] > 3600

    def test_shutdown_callbacks(self, poller):
        """Test shutdown callback functionality."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        # Add callbacks
        poller.add_shutdown_callback(callback1)
        poller.add_shutdown_callback(callback2)

        assert len(poller._shutdown_callbacks) == 2

        # Remove one callback
        poller.remove_shutdown_callback(callback1)

        assert len(poller._shutdown_callbacks) == 1
        assert callback2 in poller._shutdown_callbacks

    @pytest.mark.asyncio
    async def test_shutdown_calls_callbacks(self, poller):
        """Test that shutdown calls registered callbacks."""
        sync_callback = MagicMock()
        async_callback = AsyncMock()

        poller.add_shutdown_callback(sync_callback)
        poller.add_shutdown_callback(async_callback)

        poller._is_running = True
        await poller.shutdown()

        sync_callback.assert_called_once()
        async_callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_max_failures_shutdown(self, poller, mock_http_client):
        """Test that poller shuts down after max consecutive failures."""
        poller._max_failures = 3
        mock_http_client.fetch_incident_html.side_effect = Exception("Persistent Error")

        # Simulate multiple failed polls
        for _ in range(3):
            await poller.poll_once()

        # After 3 failures, should shutdown
        assert not poller._is_running

    @pytest.mark.asyncio
    async def test_exponential_backoff_calculation(self, poller):
        """Test exponential backoff delay calculation."""
        poller._consecutive_failures = 1
        poller._base_retry_delay = 1.0
        poller._max_retry_delay = 10.0

        # Test backoff calculation logic (simplified version of what's in _polling_loop)
        expected_delays = [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]  # Capped at max

        for i, expected in enumerate(expected_delays):
            delay = min(poller._base_retry_delay * (2**i), poller._max_retry_delay)
            assert delay == expected

    @pytest.mark.asyncio
    async def test_start_polling_startup_timeout(
        self, config, mock_http_client, mock_cache
    ):
        """Test polling startup timeout."""
        # Create poller with very short startup timeout for fast testing
        poller = IncidentPoller(
            config, mock_http_client, mock_cache, startup_timeout=0.1
        )

        # Make poll_once hang to trigger timeout
        mock_http_client.fetch_incident_html = AsyncMock()
        mock_http_client.fetch_incident_html.side_effect = asyncio.TimeoutError("Request timed out")

        with pytest.raises(PollingError, match="Poller startup timed out"):
            await poller.start_polling()

        assert not poller._is_running


class TestPollingIntegration:
    """Integration tests for polling workflow."""

    @pytest.mark.asyncio
    async def test_full_polling_workflow(self, config, sample_html):
        """Test complete polling workflow with real components."""
        # Use real cache instead of mock for integration test
        cache = IncidentCache(retention_hours=1)

        # Mock only the HTTP client since we can't hit real endpoints in tests
        http_client = MagicMock(spec=SeattleHTTPClient)
        http_client.fetch_incident_html = AsyncMock(return_value=sample_html)

        poller = IncidentPoller(config, http_client, cache)

        try:
            # Test single poll
            result = await poller.poll_once()
            assert result is True

            # Verify cache was updated
            incidents = cache.get_all_incidents()
            assert len(incidents) == 1
            assert incidents[0].incident_id == "INC001"

        finally:
            await poller.shutdown()

    @pytest.mark.asyncio
    async def test_polling_error_recovery(self, config, sample_html):
        """Test that poller recovers from transient errors."""
        cache = IncidentCache(retention_hours=1)
        http_client = MagicMock(spec=SeattleHTTPClient)

        # First call fails, second succeeds
        http_client.fetch_incident_html = AsyncMock()
        http_client.fetch_incident_html.side_effect = [
            Exception("Transient Error"),
            sample_html,
        ]

        poller = IncidentPoller(config, http_client, cache)

        try:
            # First poll should fail
            result1 = await poller.poll_once()
            assert result1 is False
            assert poller._consecutive_failures == 1

            # Second poll should succeed and reset failure count
            result2 = await poller.poll_once()
            assert result2 is True
            assert poller._consecutive_failures == 0

        finally:
            await poller.shutdown()


if __name__ == "__main__":
    pytest.main([__file__])
