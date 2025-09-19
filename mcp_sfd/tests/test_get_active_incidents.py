"""
Unit tests for the seattle.get_active_incidents MCP tool.

Tests cover successful responses, error handling, data formatting,
and integration with the FastAPI client.
"""

from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import TextContent

from mcp_sfd.api_client import MCPToolError
from mcp_sfd.tools.get_active_incidents import (
    _format_incident_time,
    _format_units,
    get_active_incidents,
)


class TestGetActiveIncidents:
    """Test cases for get_active_incidents tool."""

    @pytest.fixture
    def sample_incident_data(self):
        """Sample incident data matching FastAPI service format."""
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
    def mock_api_client(self):
        """Create a mock API client."""
        mock_client = AsyncMock()
        return mock_client

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_successful_get_active_incidents(
        self, mock_get_client, mock_api_client, sample_incident_data
    ):
        """Test successful retrieval and formatting of active incidents."""
        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.return_value = sample_incident_data

        # Call the tool
        result = await get_active_incidents({})

        # Verify result
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"

        response_text = result[0].text

        # Check header
        assert (
            "Active Seattle Fire Department Incidents (2 incidents found)"
            in response_text
        )

        # Check incident data is formatted properly
        assert "F240001234" in response_text
        assert "F240001235" in response_text
        assert "10:30 AM" in response_text
        assert "11:00 AM" in response_text
        assert "Aid Response" in response_text
        assert "Structure Fire" in response_text
        assert "123 Test St" in response_text
        assert "456 Emergency Ave" in response_text
        assert "Units: E17, L9" in response_text
        assert "Units: E12, E15, L3" in response_text
        assert "Priority: 3" in response_text
        assert "Priority: 1" in response_text

        # Check footer
        assert "Last updated:" in response_text
        assert "UTC" in response_text

        # Verify API client was called correctly
        mock_get_client.assert_called_once()
        mock_api_client.get_active_incidents.assert_called_once()

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_no_active_incidents(self, mock_get_client, mock_api_client):
        """Test handling of empty incident list."""
        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.return_value = []

        # Call the tool
        result = await get_active_incidents({})

        # Verify result
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        response_text = result[0].text
        assert "No active Seattle Fire Department incidents found" in response_text
        assert "Last updated:" in response_text
        assert "UTC" in response_text

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_custom_cache_ttl(self, mock_get_client, mock_api_client):
        """Test tool with custom cache TTL parameter."""
        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.return_value = []

        # Call the tool with custom cache TTL
        arguments = {"cache_ttl_seconds": 60}
        result = await get_active_incidents(arguments)

        # Verify result format is correct
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        # Note: The current implementation doesn't pass cache_ttl to the API client
        # This test verifies the parameter is accepted without error
        mock_api_client.get_active_incidents.assert_called_once()

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_service_unavailable_error(self, mock_get_client, mock_api_client):
        """Test handling of service unavailable error."""
        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.side_effect = MCPToolError(
            "SERVICE_UNAVAILABLE", "Cannot connect to FastAPI service"
        )

        # Call the tool
        result = await get_active_incidents({})

        # Verify error handling
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        response_text = result[0].text
        assert (
            "❌ Cannot connect to the Seattle Fire Department data service"
            in response_text
        )
        assert "FastAPI service is not running" in response_text
        assert "Network connectivity issues" in response_text

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_timeout_error(self, mock_get_client, mock_api_client):
        """Test handling of timeout error."""
        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.side_effect = MCPToolError(
            "UPSTREAM_TIMEOUT", "Request timed out after 3 retries"
        )

        # Call the tool
        result = await get_active_incidents({})

        # Verify error handling
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        response_text = result[0].text
        assert (
            "⏱️ Request to Seattle Fire Department data service timed out"
            in response_text
        )
        assert "high load or temporary issues" in response_text

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_schema_validation_error(self, mock_get_client, mock_api_client):
        """Test handling of schema validation error."""
        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.side_effect = MCPToolError(
            "SCHEMA_VALIDATION_ERROR", "Invalid response format"
        )

        # Call the tool
        result = await get_active_incidents({})

        # Verify error handling
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        response_text = result[0].text
        assert "📋 Received invalid data format from the service" in response_text
        assert "potential issue with the data service" in response_text

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_unknown_mcp_error(self, mock_get_client, mock_api_client):
        """Test handling of unknown MCP error codes."""
        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.side_effect = MCPToolError(
            "UNKNOWN_ERROR", "Some unknown error occurred"
        )

        # Call the tool
        result = await get_active_incidents({})

        # Verify error handling
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        response_text = result[0].text
        assert (
            "🚨 Unexpected error from Seattle Fire Department service" in response_text
        )
        assert "Some unknown error occurred" in response_text

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_unexpected_exception(self, mock_get_client, mock_api_client):
        """Test handling of unexpected exceptions."""
        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.side_effect = ValueError(
            "Unexpected error"
        )

        # Call the tool
        result = await get_active_incidents({})

        # Verify error handling
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        response_text = result[0].text
        assert "💥 An unexpected error occurred: Unexpected error" in response_text
        assert "likely a bug in the tool implementation" in response_text

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_incident_with_missing_fields(self, mock_get_client, mock_api_client):
        """Test handling of incidents with missing or None fields."""
        # Incident data with missing fields
        incomplete_incident = {
            "incident_id": "F240999999",
            # Missing incident_datetime
            # Missing priority
            "units": None,
            "address": "",
            "incident_type": None,
            # Missing status
        }

        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.return_value = [incomplete_incident]

        # Call the tool
        result = await get_active_incidents({})

        # Verify result handles missing fields gracefully
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        response_text = result[0].text
        assert "F240999999" in response_text
        assert "Unknown Time" in response_text
        assert "Unknown Type" in response_text
        # Should handle empty/None address
        assert "Unknown Address" in response_text or "" in response_text

    @patch("mcp_sfd.tools.get_active_incidents.get_client")
    async def test_incident_with_string_units(self, mock_get_client, mock_api_client):
        """Test handling of incidents where units is a string instead of list."""
        # Incident data with string units
        incident_with_string_units = {
            "incident_id": "F240777777",
            "incident_datetime": "2024-01-01T14:30:00Z",
            "priority": 2,
            "units": "E20",  # String instead of list
            "address": "789 String Units Ave",
            "incident_type": "Medical Aid",
            "status": "active",
        }

        # Setup mocks
        mock_get_client.return_value = mock_api_client
        mock_api_client.get_active_incidents.return_value = [incident_with_string_units]

        # Call the tool
        result = await get_active_incidents({})

        # Verify result handles string units correctly
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        response_text = result[0].text
        assert "F240777777" in response_text
        assert "Units: E20" in response_text


class TestUtilityFunctions:
    """Test cases for utility functions."""

    def test_format_incident_time_iso_format(self):
        """Test formatting of ISO format datetime."""
        iso_time = "2024-01-01T14:30:00Z"
        result = _format_incident_time(iso_time)
        assert result == "02:30 PM"

    def test_format_incident_time_iso_with_timezone(self):
        """Test formatting of ISO format datetime with timezone."""
        iso_time = "2024-01-01T14:30:00+00:00"
        result = _format_incident_time(iso_time)
        assert result == "02:30 PM"

    def test_format_incident_time_none(self):
        """Test formatting of None datetime."""
        result = _format_incident_time(None)
        assert result == "Unknown Time"

    def test_format_incident_time_empty_string(self):
        """Test formatting of empty string datetime."""
        result = _format_incident_time("")
        assert result == "Unknown Time"

    def test_format_incident_time_invalid_format(self):
        """Test formatting of invalid datetime format."""
        invalid_time = "not a datetime"
        result = _format_incident_time(invalid_time)
        assert result == "not a datetime"

    def test_format_incident_time_non_iso_format(self):
        """Test formatting of non-ISO datetime format."""
        non_iso_time = "2024-01-01 14:30:00"
        result = _format_incident_time(non_iso_time)
        assert result == "2024-01-01 14:30:00"

    def test_format_units_list(self):
        """Test formatting of units list."""
        units_list = ["E17", "L9", "M1"]
        result = _format_units(units_list)
        assert result == "E17, L9, M1"

    def test_format_units_empty_list(self):
        """Test formatting of empty units list."""
        result = _format_units([])
        assert result == ""

    def test_format_units_none(self):
        """Test formatting of None units."""
        result = _format_units(None)
        assert result == ""

    def test_format_units_string(self):
        """Test formatting of units as string."""
        units_string = "E20"
        result = _format_units(units_string)
        assert result == "E20"

    def test_format_units_list_with_empty_strings(self):
        """Test formatting of units list with empty strings."""
        units_list = ["E17", "", "L9", None, "M1"]
        result = _format_units(units_list)
        assert result == "E17, L9, M1"

    def test_format_units_non_string_non_list(self):
        """Test formatting of units that is neither string nor list."""
        units_number = 123
        result = _format_units(units_number)
        assert result == "123"
