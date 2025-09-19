"""
Unit tests for the Seattle API FastAPI client.

Tests cover HTTP client functionality, retry logic, error handling,
response validation, and connection management.
"""

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_sfd.api_client import MCPToolError, SeattleAPIClient, close_client, get_client


class TestSeattleAPIClient:
    """Test cases for SeattleAPIClient."""

    @pytest.fixture
    def client(self):
        """Create a test client instance."""
        return SeattleAPIClient(
            base_url="http://test-api:8000", timeout=5, max_retries=2
        )

    @pytest.fixture
    def mock_httpx_client(self):
        """Create a mock httpx client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return mock_client

    @pytest.fixture
    def sample_incident_data(self):
        """Sample incident data for testing."""
        return [
            {
                "incident_id": "F240001234",
                "incident_datetime": "2024-01-01T10:30:00Z",
                "priority": 3,
                "units": ["E17", "L9"],
                "address": "123 Test St",
                "incident_type": "Aid Response",
                "status": "active",
                "first_seen": "2024-01-01T10:30:00Z",
                "last_seen": "2024-01-01T10:35:00Z",
                "closed_at": None,
            },
            {
                "incident_id": "F240001235",
                "incident_datetime": "2024-01-01T11:00:00Z",
                "priority": 1,
                "units": ["E12", "E15", "L3"],
                "address": "456 Emergency Ave",
                "incident_type": "Structure Fire",
                "status": "active",
                "first_seen": "2024-01-01T11:00:00Z",
                "last_seen": "2024-01-01T11:05:00Z",
                "closed_at": None,
            },
        ]

    @pytest.fixture
    def sample_health_data(self):
        """Sample health status data for testing."""
        return {
            "status": "healthy",
            "service": "seattle-fire-api",
            "version": "1.0.0",
            "config": {"polling_interval": 300, "cache_enabled": True},
        }

    async def test_client_initialization(self, client):
        """Test client initialization with custom parameters."""
        assert client.base_url == "http://test-api:8000"
        assert client.timeout == 5
        assert client.max_retries == 2
        assert client._client is None

    async def test_client_creation_from_environment(self):
        """Test client creation with environment variables."""
        with patch.dict(
            "os.environ",
            {
                "FASTAPI_BASE_URL": "http://env-api:9000",
                "REQUEST_TIMEOUT": "60",
                "MAX_RETRIES": "5",
            },
        ):
            client = SeattleAPIClient(
                base_url=os.getenv("FASTAPI_BASE_URL"),
                timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
                max_retries=int(os.getenv("MAX_RETRIES", "3")),
            )
            assert client.base_url == "http://env-api:9000"
            assert client.timeout == 60
            assert client.max_retries == 5

    @patch("mcp_sfd.api_client.httpx.AsyncClient")
    async def test_get_client_creates_client(self, mock_async_client_class, client):
        """Test that _get_client creates and configures httpx client properly."""
        mock_client_instance = AsyncMock()
        mock_async_client_class.return_value = mock_client_instance

        result = await client._get_client()

        assert result == mock_client_instance
        assert client._client == mock_client_instance

        # Verify client was created with correct configuration
        mock_async_client_class.assert_called_once()
        call_kwargs = mock_async_client_class.call_args.kwargs

        assert call_kwargs["base_url"] == "http://test-api:8000"
        assert call_kwargs["follow_redirects"] is True
        assert "timeout" in call_kwargs
        assert "headers" in call_kwargs
        assert "limits" in call_kwargs

        # Check headers
        headers = call_kwargs["headers"]
        assert headers["User-Agent"] == "mcp-sfd-client/1.0.0"
        assert headers["Accept"] == "application/json"

    async def test_successful_get_active_incidents(self, client, sample_incident_data):
        """Test successful retrieval of active incidents."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_incident_data

        with patch.object(
            client, "_make_request_with_retry", return_value=mock_response
        ):
            result = await client.get_active_incidents()

            assert result == sample_incident_data
            client._make_request_with_retry.assert_called_once_with(
                "GET", "/incidents/active"
            )

    async def test_successful_get_all_incidents(self, client, sample_incident_data):
        """Test successful retrieval of all incidents."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_incident_data

        with patch.object(
            client, "_make_request_with_retry", return_value=mock_response
        ):
            result = await client.get_all_incidents()

            assert result == sample_incident_data
            client._make_request_with_retry.assert_called_once_with(
                "GET", "/incidents/all"
            )

    async def test_successful_search_incidents(self, client, sample_incident_data):
        """Test successful incident search with filters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_incident_data

        search_params = {
            "incident_type": "Structure Fire",
            "address_contains": "Test",
            "since": datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            "priority": 1,
        }

        expected_params = {
            "type": "Structure Fire",
            "address": "Test",
            "since": "2024-01-01T10:00:00+00:00",
            "priority": "1",
        }

        with patch.object(
            client, "_make_request_with_retry", return_value=mock_response
        ):
            result = await client.search_incidents(**search_params)

            assert result == sample_incident_data
            client._make_request_with_retry.assert_called_once_with(
                "GET", "/incidents/search", params=expected_params
            )

    async def test_successful_get_incident(self, client):
        """Test successful retrieval of specific incident."""
        incident_data = {
            "incident_id": "F240001234",
            "incident_type": "Aid Response",
            "status": "active",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = incident_data

        with patch.object(
            client, "_make_request_with_retry", return_value=mock_response
        ):
            result = await client.get_incident("F240001234")

            assert result == incident_data
            client._make_request_with_retry.assert_called_once_with(
                "GET", "/incidents/F240001234"
            )

    async def test_successful_get_health(self, client, sample_health_data):
        """Test successful health status retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_health_data

        with patch.object(
            client, "_make_request_with_retry", return_value=mock_response
        ):
            result = await client.get_health()

            assert result == sample_health_data
            client._make_request_with_retry.assert_called_once_with("GET", "/health")

    async def test_retry_logic_with_server_errors(self, client):
        """Test retry logic for server errors (5xx)."""
        # Mock responses: 503, 503, 200 (success on third attempt)
        responses = [
            MagicMock(status_code=503, text="Service Unavailable"),
            MagicMock(status_code=503, text="Service Unavailable"),
            MagicMock(status_code=200, json=lambda: []),
        ]

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.side_effect = responses
            mock_get_client.return_value = mock_client

            with patch("asyncio.sleep"):  # Mock sleep to speed up test
                result = await client._make_request_with_retry("GET", "/test")

            assert result.status_code == 200
            assert mock_client.request.call_count == 3

    async def test_retry_exhaustion_with_server_errors(self, client):
        """Test retry exhaustion with persistent server errors."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.return_value = MagicMock(
                status_code=503, text="Service Unavailable"
            )
            mock_get_client.return_value = mock_client

            with patch("asyncio.sleep"):  # Mock sleep to speed up test
                with pytest.raises(MCPToolError) as exc_info:
                    await client._make_request_with_retry("GET", "/test")

            assert exc_info.value.code == "UPSTREAM_HTTP_ERROR"
            assert "503" in str(exc_info.value.message)
            assert mock_client.request.call_count == 3  # Initial + 2 retries

    async def test_timeout_handling(self, client):
        """Test timeout error handling and retries."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.side_effect = httpx.TimeoutException(
                "Request timed out"
            )
            mock_get_client.return_value = mock_client

            with patch("asyncio.sleep"):  # Mock sleep to speed up test
                with pytest.raises(MCPToolError) as exc_info:
                    await client._make_request_with_retry("GET", "/test")

            assert exc_info.value.code == "UPSTREAM_TIMEOUT"
            assert "timed out" in str(exc_info.value.message)
            assert mock_client.request.call_count == 3  # Initial + 2 retries

    async def test_connection_error_handling(self, client):
        """Test connection error handling."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.side_effect = httpx.ConnectError("Connection failed")
            mock_get_client.return_value = mock_client

            with pytest.raises(MCPToolError) as exc_info:
                await client._make_request_with_retry("GET", "/test")

            assert exc_info.value.code == "SERVICE_UNAVAILABLE"
            assert "Cannot connect" in str(exc_info.value.message)
            assert (
                mock_client.request.call_count == 1
            )  # No retries for connection errors

    async def test_404_error_handling(self, client):
        """Test 404 error handling."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.return_value = MagicMock(
                status_code=404, text="Not Found"
            )
            mock_get_client.return_value = mock_client

            with pytest.raises(MCPToolError) as exc_info:
                await client._make_request_with_retry("GET", "/incidents/nonexistent")

            assert exc_info.value.code == "RESOURCE_NOT_FOUND"
            assert mock_client.request.call_count == 1  # No retries for 404

    async def test_client_error_no_retry(self, client):
        """Test that 4xx errors (except 404) don't trigger retries."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.return_value = MagicMock(
                status_code=400, text="Bad Request"
            )
            mock_get_client.return_value = mock_client

            with pytest.raises(MCPToolError) as exc_info:
                await client._make_request_with_retry("GET", "/test")

            assert exc_info.value.code == "UPSTREAM_HTTP_ERROR"
            assert "400" in str(exc_info.value.message)
            assert mock_client.request.call_count == 1  # No retries for 400

    async def test_invalid_response_data_validation(self, client):
        """Test validation of invalid response data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = "invalid_data"  # Should be list

        with patch.object(
            client, "_make_request_with_retry", return_value=mock_response
        ):
            with pytest.raises(MCPToolError) as exc_info:
                await client.get_active_incidents()

            assert exc_info.value.code == "SCHEMA_VALIDATION_ERROR"
            assert "Expected list" in str(exc_info.value.message)

    async def test_incident_not_found(self, client):
        """Test incident not found error handling."""
        with patch.object(client, "_make_request_with_retry") as mock_request:
            mock_request.side_effect = httpx.HTTPStatusError(
                "Not Found", request=MagicMock(), response=MagicMock(status_code=404)
            )

            with pytest.raises(MCPToolError) as exc_info:
                await client.get_incident("nonexistent")

            assert exc_info.value.code == "RESOURCE_NOT_FOUND"
            assert "not found" in str(exc_info.value.message)

    async def test_close_client(self, client):
        """Test client cleanup."""
        # Set up a mock client
        mock_client = AsyncMock()
        client._client = mock_client

        await client.close()

        mock_client.aclose.assert_called_once()
        assert client._client is None

    async def test_exponential_backoff_timing(self, client):
        """Test that exponential backoff timing is correct."""
        sleep_times = []

        async def mock_sleep(duration):
            sleep_times.append(duration)

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.side_effect = [
                httpx.TimeoutException("timeout"),
                httpx.TimeoutException("timeout"),
                httpx.TimeoutException("timeout"),
            ]
            mock_get_client.return_value = mock_client

            with patch("asyncio.sleep", side_effect=mock_sleep):
                with pytest.raises(MCPToolError):
                    await client._make_request_with_retry("GET", "/test")

            # Should have exponential backoff: 1s, 2s
            assert sleep_times == [1, 2]


class TestGlobalClientFunctions:
    """Test cases for global client management functions."""

    async def test_get_client_singleton(self):
        """Test that get_client returns singleton instance."""
        # Clean up any existing client
        await close_client()

        with patch.dict(
            "os.environ",
            {
                "FASTAPI_BASE_URL": "http://test:8000",
                "REQUEST_TIMEOUT": "30",
                "MAX_RETRIES": "3",
            },
        ):
            client1 = await get_client()
            client2 = await get_client()

            assert client1 is client2
            assert client1.base_url == "http://test:8000"

        # Clean up
        await close_client()

    async def test_close_client_cleanup(self):
        """Test that close_client properly cleans up global instance."""
        # Create a client
        client = await get_client()
        assert client is not None

        # Mock the close method
        with patch.object(client, "close") as mock_close:
            await close_client()
            mock_close.assert_called_once()

        # Verify new client is created on next call
        new_client = await get_client()
        assert new_client is not client

        # Clean up
        await close_client()


@pytest.mark.asyncio
class TestIntegrationScenarios:
    """Integration test scenarios combining multiple client operations."""

    @pytest.fixture
    def client(self):
        """Create a test client for integration tests."""
        return SeattleAPIClient(base_url="http://test-api:8000", max_retries=1)

    @pytest.fixture
    def sample_incident_data(self):
        """Sample incident data for testing."""
        return [
            {
                "incident_id": "F240001234",
                "incident_datetime": "2024-01-01T10:30:00Z",
                "priority": 3,
                "units": ["E17", "L9"],
                "address": "123 Test St",
                "incident_type": "Aid Response",
                "status": "active",
                "first_seen": "2024-01-01T10:30:00Z",
                "last_seen": "2024-01-01T10:35:00Z",
                "closed_at": None,
            }
        ]

    @pytest.fixture
    def sample_health_data(self):
        """Sample health status data for testing."""
        return {
            "status": "healthy",
            "service": "seattle-fire-api",
            "version": "1.0.0",
            "config": {"polling_interval": 300, "cache_enabled": True},
        }

    async def test_service_recovery_scenario(self, client, sample_incident_data):
        """Test client behavior during service recovery."""
        # Simulate service down then up
        responses = [
            MagicMock(status_code=503, text="Service Unavailable"),
            MagicMock(status_code=200, json=lambda: sample_incident_data),
        ]

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.side_effect = responses
            mock_get_client.return_value = mock_client

            with patch("asyncio.sleep"):
                result = await client.get_active_incidents()

            assert result == sample_incident_data
            assert mock_client.request.call_count == 2

    async def test_mixed_operation_sequence(
        self, client, sample_incident_data, sample_health_data
    ):
        """Test a sequence of different operations."""

        def create_mock_response(data):
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = data
            return mock

        with patch.object(client, "_make_request_with_retry") as mock_request:
            mock_request.side_effect = [
                create_mock_response(sample_health_data),
                create_mock_response(sample_incident_data),
                create_mock_response(sample_incident_data[0]),
            ]

            # Sequence of operations
            health = await client.get_health()
            incidents = await client.get_active_incidents()
            specific = await client.get_incident("F240001234")

            assert health == sample_health_data
            assert incidents == sample_incident_data
            assert specific == sample_incident_data[0]

            assert mock_request.call_count == 3
