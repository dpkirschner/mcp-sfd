"""Tests for Seattle HTTP client."""

from unittest.mock import patch

import httpx
import pytest
from httpx import Request, Response

from seattle_api.config import FastAPIConfig
from seattle_api.http_client import HTTPClientError, SeattleHTTPClient


@pytest.fixture
def config():
    """Test configuration."""
    return FastAPIConfig(
        seattle_endpoint="https://test.example.com/incidents",
        polling_interval_minutes=5,
        cache_retention_hours=24,
        server_port=8000,
    )


@pytest.fixture
def http_client(config):
    """HTTP client instance for testing."""
    return SeattleHTTPClient(config)


@pytest.fixture
def mock_response():
    """Mock HTTP response."""

    def _create_response(status_code=200, content="<html><table>test</table></html>"):
        request = Request("GET", "https://test.example.com/incidents")
        response = Response(status_code, request=request)
        response._content = content.encode()
        return response

    return _create_response


class TestSeattleHTTPClient:
    """Test cases for SeattleHTTPClient."""

    def test_init(self, config):
        """Test client initialization."""
        client = SeattleHTTPClient(config)

        assert client.config == config
        assert client.endpoint_url == config.seattle_endpoint
        assert client._client is None
        assert client.max_retries == 3
        assert client.timeout == 30.0
        assert "User-Agent" in client.headers
        assert "Seattle-Incident-API/1.0.0" in client.headers["User-Agent"]

    @pytest.mark.asyncio
    async def test_context_manager(self, http_client):
        """Test async context manager functionality."""
        async with http_client as client:
            assert client._client is not None

        assert http_client._client is None

    @pytest.mark.asyncio
    async def test_start_and_close(self, http_client):
        """Test manual start and close operations."""
        # Initially no client
        assert http_client._client is None

        # Start client
        await http_client.start()
        assert http_client._client is not None
        assert isinstance(http_client._client, httpx.AsyncClient)

        # Close client
        await http_client.close()
        assert http_client._client is None

    @pytest.mark.asyncio
    async def test_fetch_incident_html_success(self, http_client, mock_response):
        """Test successful HTML fetch."""
        test_html = (
            "<html><body><table><tr><td>incident data</td></tr></table></body></html>"
        )

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.return_value = mock_response(200, test_html)

            result = await http_client.fetch_incident_html()

            assert result == test_html
            mock_get.assert_called_once_with(http_client.endpoint_url)

    @pytest.mark.asyncio
    async def test_fetch_incident_html_empty_response(self, http_client, mock_response):
        """Test handling of empty response."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.return_value = mock_response(200, "")

            with pytest.raises(HTTPClientError, match="Empty response received"):
                await http_client.fetch_incident_html()

    @pytest.mark.asyncio
    async def test_fetch_incident_html_invalid_html(self, http_client, mock_response):
        """Test handling of invalid HTML response."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.return_value = mock_response(200, "not html content")

            with pytest.raises(
                HTTPClientError, match="does not appear to be valid HTML"
            ):
                await http_client.fetch_incident_html()

    @pytest.mark.asyncio
    async def test_fetch_incident_html_http_error_4xx(self, http_client):
        """Test handling of 4xx HTTP errors (no retry)."""
        error_response = Response(
            404, request=Request("GET", "https://test.example.com")
        )
        http_error = httpx.HTTPStatusError(
            "Not Found", request=error_response.request, response=error_response
        )

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = http_error

            with pytest.raises(HTTPClientError, match="Failed to fetch incident data"):
                await http_client.fetch_incident_html()

            # Should only try once for 4xx errors
            assert mock_get.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_incident_html_http_error_5xx_with_retry(
        self, http_client, mock_response
    ):
        """Test handling of 5xx HTTP errors with retry."""
        error_response = Response(
            500, request=Request("GET", "https://test.example.com")
        )
        http_error = httpx.HTTPStatusError(
            "Server Error", request=error_response.request, response=error_response
        )

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            # First two calls fail, third succeeds
            mock_get.side_effect = [
                http_error,
                http_error,
                mock_response(200, "<html><table>success</table></html>"),
            ]

            with patch("asyncio.sleep") as mock_sleep:
                result = await http_client.fetch_incident_html()

                assert result == "<html><table>success</table></html>"
                assert mock_get.call_count == 3
                assert mock_sleep.call_count == 2  # Two retries

    @pytest.mark.asyncio
    async def test_fetch_incident_html_timeout_with_retry(self, http_client):
        """Test handling of timeout errors with retry."""
        timeout_error = httpx.TimeoutException("Request timeout")

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = timeout_error

            with patch("asyncio.sleep") as mock_sleep:
                with pytest.raises(
                    HTTPClientError, match="Failed to fetch incident data"
                ):
                    await http_client.fetch_incident_html()

                # Should retry max_retries times
                assert mock_get.call_count == http_client.max_retries + 1
                assert mock_sleep.call_count == http_client.max_retries

    @pytest.mark.asyncio
    async def test_fetch_incident_html_connection_error(self, http_client):
        """Test handling of connection errors."""
        connection_error = httpx.ConnectError("Connection failed")

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = connection_error

            with patch("asyncio.sleep"):
                with pytest.raises(
                    HTTPClientError, match="Failed to fetch incident data"
                ):
                    await http_client.fetch_incident_html()

                assert mock_get.call_count == http_client.max_retries + 1

    @pytest.mark.asyncio
    async def test_fetch_incident_html_exponential_backoff(self, http_client):
        """Test exponential backoff delay calculation."""
        timeout_error = httpx.TimeoutException("Request timeout")

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = timeout_error

            with patch("asyncio.sleep") as mock_sleep:
                with pytest.raises(HTTPClientError):
                    await http_client.fetch_incident_html()

                # Check that delays increase exponentially
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert len(sleep_calls) == 3  # max_retries
                assert sleep_calls[0] == 1.0  # base_delay * 2^0
                assert sleep_calls[1] == 2.0  # base_delay * 2^1
                assert sleep_calls[2] == 4.0  # base_delay * 2^2

    @pytest.mark.asyncio
    async def test_fetch_incident_html_max_delay_cap(self, http_client):
        """Test that delay is capped at max_delay."""
        http_client.max_delay = 3.0  # Set low max delay for testing
        timeout_error = httpx.TimeoutException("Request timeout")

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = timeout_error

            with patch("asyncio.sleep") as mock_sleep:
                with pytest.raises(HTTPClientError):
                    await http_client.fetch_incident_html()

                # Check that delay is capped
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert all(delay <= http_client.max_delay for delay in sleep_calls)

    def test_is_valid_html_response(self, http_client):
        """Test HTML response validation."""
        # Valid HTML responses
        assert http_client._is_valid_html_response("<html><body>test</body></html>")
        assert http_client._is_valid_html_response("<!DOCTYPE html><html>test</html>")
        assert http_client._is_valid_html_response(
            "<table><tr><td>data</td></tr></table>"
        )
        assert http_client._is_valid_html_response("  <HTML>  ")  # Case insensitive

        # Invalid responses
        assert not http_client._is_valid_html_response("plain text")
        assert not http_client._is_valid_html_response('{"json": "data"}')
        assert not http_client._is_valid_html_response("")
        assert not http_client._is_valid_html_response("   ")

    @pytest.mark.asyncio
    async def test_health_check_success(self, http_client, mock_response):
        """Test successful health check."""
        with patch.object(httpx.AsyncClient, "head") as mock_head:
            mock_head.return_value = mock_response(200)

            result = await http_client.health_check()

            assert result["status"] == "healthy"
            assert result["status_code"] == 200
            assert "response_time_seconds" in result
            assert result["endpoint"] == http_client.endpoint_url
            assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_health_check_degraded(self, http_client, mock_response):
        """Test degraded health check (non-200 status)."""
        with patch.object(httpx.AsyncClient, "head") as mock_head:
            mock_head.return_value = mock_response(503)

            result = await http_client.health_check()

            assert result["status"] == "degraded"
            assert result["status_code"] == 503

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, http_client):
        """Test unhealthy health check (exception)."""
        with patch.object(httpx.AsyncClient, "head") as mock_head:
            mock_head.side_effect = httpx.ConnectError("Connection failed")

            result = await http_client.health_check()

            assert result["status"] == "unhealthy"
            assert "error" in result
            assert "Connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_auto_start_client(self, http_client, mock_response):
        """Test that client auto-starts when needed."""
        # Client should be None initially
        assert http_client._client is None

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.return_value = mock_response(
                200, "<html><table>test</table></html>"
            )

            # This should auto-start the client
            await http_client.fetch_incident_html()

            # Client should now be initialized
            assert http_client._client is not None

        # Clean up
        await http_client.close()


class TestHTTPClientError:
    """Test cases for HTTPClientError exception."""

    def test_http_client_error_creation(self):
        """Test HTTPClientError creation."""
        error = HTTPClientError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)

    def test_http_client_error_with_cause(self):
        """Test HTTPClientError with cause."""
        original_error = ValueError("Original error")
        error = None
        try:
            raise HTTPClientError("Wrapper error") from original_error
        except HTTPClientError as e:
            error = e

        assert str(error) == "Wrapper error"
        assert error.__cause__ == original_error
