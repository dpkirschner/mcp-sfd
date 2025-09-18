"""
Tests for all MCP tools.

This module tests each tool's logic using mocked HTTP responses
to ensure correct behavior without requiring real API calls.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytz

from mcp_sfd.http_client import MCPToolError
from mcp_sfd.tools.fetch_raw import fetch_raw
from mcp_sfd.tools.has_evac_orders import has_evacuation_orders
from mcp_sfd.tools.is_fire_active import is_fire_active
from mcp_sfd.tools.latest_incident import latest_incident


@pytest.fixture
def example_socrata_response():
    """Create example Socrata response data."""
    return [
        {
            "incident_number": "F250128483",
            "type": "Auto Fire Alarm",
            "address": "1601 5th Ave",
            "datetime": "2025-09-15T22:58:00.000",
            "latitude": "47.611672",
            "longitude": "-122.336484",
            "report_location": {
                "type": "Point",
                "coordinates": [-122.336484, 47.611672],
            },
        },
        {
            "incident_number": "M250128484",
            "type": "Medical Aid",
            "address": "456 Pine St",
            "datetime": "2025-09-15T22:30:00.000",
            "latitude": "47.612345",
            "longitude": "-122.345678",
        },
    ]


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch("mcp_sfd.tools.fetch_raw.get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_client.base_url = "https://data.seattle.gov/resource/kzjm-xkqj.json"
        yield mock_client


class TestFetchRaw:
    """Test the fetch_raw tool."""

    @pytest.mark.asyncio
    async def test_fetch_raw_default_params(
        self, mock_http_client, example_socrata_response
    ):
        """Test fetch_raw with default parameters."""
        # Setup mock response
        mock_http_client.fetch_incidents.return_value = (
            example_socrata_response,
            False,
        )

        # Call tool with minimal arguments
        result = await fetch_raw({})

        # Check that client was called with correct defaults
        mock_http_client.fetch_incidents.assert_called_once()
        call_args = mock_http_client.fetch_incidents.call_args
        params, cache_ttl = call_args[0]

        assert params["$order"] == "datetime DESC"
        assert params["$limit"] == "100"
        assert cache_ttl == 15

        # Check result structure
        assert "meta" in result
        assert "incidents" in result
        assert "source" in result
        assert len(result["incidents"]) == 2

    @pytest.mark.asyncio
    async def test_fetch_raw_custom_params(
        self, mock_http_client, example_socrata_response
    ):
        """Test fetch_raw with custom parameters."""
        mock_http_client.fetch_incidents.return_value = (example_socrata_response, True)

        arguments = {
            "order": "old",
            "length": 50,
            "search": "fire",
            "cacheTtlSeconds": 60,
        }

        result = await fetch_raw(arguments)

        # Check parameters passed to client
        call_args = mock_http_client.fetch_incidents.call_args
        params, cache_ttl = call_args[0]

        assert params["$order"] == "datetime ASC"
        assert params["$limit"] == "50"
        assert cache_ttl == 60

        # Check cache hit reflected in response
        assert result["source"]["cache_hit"] is True

    @pytest.mark.asyncio
    async def test_fetch_raw_validation_error(self, mock_http_client):
        """Test fetch_raw with invalid arguments."""
        with pytest.raises(ValueError, match="Invalid arguments"):
            await fetch_raw({"length": -1})  # Invalid length

    @pytest.mark.asyncio
    async def test_fetch_raw_http_error(self, mock_http_client):
        """Test fetch_raw with HTTP error."""
        mock_http_client.fetch_incidents.side_effect = MCPToolError(
            "UPSTREAM_HTTP_ERROR", "API returned 500"
        )

        with pytest.raises(MCPToolError) as exc_info:
            await fetch_raw({})

        assert exc_info.value.code == "UPSTREAM_HTTP_ERROR"


class TestLatestIncident:
    """Test the latest_incident tool."""

    @pytest.mark.asyncio
    async def test_latest_incident_success(self):
        """Test successful latest incident retrieval."""
        with patch("mcp_sfd.tools.latest_incident.fetch_raw") as mock_fetch:
            # Setup mock to return our example data
            mock_response = {
                "incidents": [
                    {
                        "incident_number": "F250915-001",
                        "type": "Fire in Building",
                        "address": "123 Main St",
                        "datetime_local": "2025-09-15T16:05:27-07:00",
                        "datetime_utc": "2025-09-15T23:05:27+00:00",
                        "latitude": 47.6062,
                        "longitude": -122.3321,
                        "report_location": None,
                        "computed_region_ru88_fbhk": None,
                        "computed_region_kuhn_3gp2": None,
                        "computed_region_q256_3sug": None,
                        "estimated_active": True,
                        "raw": None,
                    }
                ],
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": "2025-09-15T23:10:00+00:00",
                    "cache_hit": False,
                },
            }
            mock_fetch.return_value = mock_response

            result = await latest_incident({})

            # Check that fetch_raw was called with correct parameters
            mock_fetch.assert_called_once()
            call_args = mock_fetch.call_args[0][0]
            assert call_args["order"] == "new"
            assert call_args["length"] == 1

            # Check result structure
            assert "incident" in result
            assert "source" in result
            assert result["incident"]["incident_number"] == "F250915-001"

    @pytest.mark.asyncio
    async def test_latest_incident_no_incidents(self):
        """Test latest incident when no incidents found."""
        with patch("mcp_sfd.tools.latest_incident.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": [],
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": "2025-09-15T23:10:00+00:00",
                    "cache_hit": False,
                },
            }

            with pytest.raises(MCPToolError, match="No incidents found"):
                await latest_incident({})


class TestIsFireActive:
    """Test the is_fire_active tool."""

    @pytest.mark.asyncio
    async def test_is_fire_active_with_active_fire(self):
        """Test fire detection with active fire incident."""
        # Create recent fire incident (within lookback)
        recent_time = datetime.now(pytz.UTC) - timedelta(minutes=10)

        mock_incidents = [
            {
                "incident_number": "F250915-001",
                "type": "Structure Fire",
                "address": "123 Main St",
                "datetime_local": recent_time.isoformat(),
                "datetime_utc": recent_time.isoformat(),
                "latitude": 47.6062,
                "longitude": -122.3321,
                "report_location": None,
                "computed_region_ru88_fbhk": None,
                "computed_region_kuhn_3gp2": None,
                "computed_region_q256_3sug": None,
                "estimated_active": True,  # Recent incident
                "raw": None,
            }
        ]

        with patch("mcp_sfd.tools.is_fire_active.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": mock_incidents,
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": datetime.now(pytz.UTC).isoformat(),
                    "cache_hit": False,
                },
            }

            result = await is_fire_active({"lookbackMinutes": 120})

            assert result["is_fire_active"] is True
            assert len(result["matching_incidents"]) == 1
            assert "active fire incident" in result["reasoning"].lower()

    @pytest.mark.asyncio
    async def test_is_fire_active_with_inactive_fire(self):
        """Test fire detection with inactive fire incident."""
        # Create old fire incident (outside active window)
        old_time = datetime.now(pytz.UTC) - timedelta(hours=2)

        mock_incidents = [
            {
                "incident_number": "F250915-001",
                "type": "Structure Fire",
                "address": "123 Main St",
                "datetime_local": old_time.isoformat(),
                "datetime_utc": old_time.isoformat(),
                "latitude": 47.6062,
                "longitude": -122.3321,
                "report_location": None,
                "computed_region_ru88_fbhk": None,
                "computed_region_kuhn_3gp2": None,
                "computed_region_q256_3sug": None,
                "estimated_active": False,  # Old incident
                "raw": None,
            }
        ]

        with patch("mcp_sfd.tools.is_fire_active.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": mock_incidents,
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": datetime.now(pytz.UTC).isoformat(),
                    "cache_hit": False,
                },
            }

            result = await is_fire_active({"lookbackMinutes": 120})

            assert result["is_fire_active"] is False
            assert len(result["matching_incidents"]) == 0

    @pytest.mark.asyncio
    async def test_is_fire_active_no_fire_incidents(self):
        """Test fire detection with no fire incidents."""
        mock_incidents = [
            {
                "incident_number": "M250915-001",
                "type": "Medical Aid",
                "address": "123 Main St",
                "datetime_local": datetime.now(pytz.UTC).isoformat(),
                "datetime_utc": datetime.now(pytz.UTC).isoformat(),
                "latitude": 47.6062,
                "longitude": -122.3321,
                "report_location": None,
                "computed_region_ru88_fbhk": None,
                "computed_region_kuhn_3gp2": None,
                "computed_region_q256_3sug": None,
                "estimated_active": True,
                "raw": None,
            }
        ]

        with patch("mcp_sfd.tools.is_fire_active.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": mock_incidents,
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": datetime.now(pytz.UTC).isoformat(),
                    "cache_hit": False,
                },
            }

            result = await is_fire_active({})

            assert result["is_fire_active"] is False
            assert len(result["matching_incidents"]) == 0
            assert "no fire-related incidents" in result["reasoning"].lower()

    @pytest.mark.asyncio
    async def test_is_fire_active_water_rescue_exclusion(self):
        """Test that water rescue without fire mention is excluded."""
        mock_incidents = [
            {
                "incident_number": "R250915-001",
                "type": "Water Rescue",
                "address": "Lake Washington",
                "datetime_local": datetime.now(pytz.UTC).isoformat(),
                "datetime_utc": datetime.now(pytz.UTC).isoformat(),
                "latitude": 47.6062,
                "longitude": -122.3321,
                "report_location": None,
                "computed_region_ru88_fbhk": None,
                "computed_region_kuhn_3gp2": None,
                "computed_region_q256_3sug": None,
                "estimated_active": True,
                "raw": None,
            }
        ]

        with patch("mcp_sfd.tools.is_fire_active.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": mock_incidents,
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": datetime.now(pytz.UTC).isoformat(),
                    "cache_hit": False,
                },
            }

            result = await is_fire_active({})

            assert result["is_fire_active"] is False


class TestHasEvacuationOrders:
    """Test the has_evacuation_orders tool."""

    @pytest.mark.asyncio
    async def test_has_evacuation_orders_found(self):
        """Test evacuation detection when keywords are found."""
        mock_incidents = [
            {
                "incident_number": "F250915-001",
                "type": "Evacuation Order",  # Keyword in type
                "address": "123 Main St",
                "datetime_local": datetime.now(pytz.UTC).isoformat(),
                "datetime_utc": datetime.now(pytz.UTC).isoformat(),
                "latitude": 47.6062,
                "longitude": -122.3321,
                "report_location": None,
                "computed_region_ru88_fbhk": None,
                "computed_region_kuhn_3gp2": None,
                "computed_region_q256_3sug": None,
                "estimated_active": True,
                "raw": None,
            }
        ]

        with patch("mcp_sfd.tools.has_evac_orders.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": mock_incidents,
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": datetime.now(pytz.UTC).isoformat(),
                    "cache_hit": False,
                },
            }

            result = await has_evacuation_orders({})

            assert result["has_evacuation_orders"] is True
            assert len(result["supporting_incidents"]) == 1
            assert "evacuation-related keywords" in result["notes"]
            assert "AlertSeattle" in result["notes"]

    @pytest.mark.asyncio
    async def test_has_evacuation_orders_not_found(self):
        """Test evacuation detection when no keywords found."""
        mock_incidents = [
            {
                "incident_number": "M250915-001",
                "type": "Medical Aid",
                "address": "123 Main St",
                "datetime_local": datetime.now(pytz.UTC).isoformat(),
                "datetime_utc": datetime.now(pytz.UTC).isoformat(),
                "latitude": 47.6062,
                "longitude": -122.3321,
                "report_location": None,
                "computed_region_ru88_fbhk": None,
                "computed_region_kuhn_3gp2": None,
                "computed_region_q256_3sug": None,
                "estimated_active": True,
                "raw": None,
            }
        ]

        with patch("mcp_sfd.tools.has_evac_orders.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": mock_incidents,
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": datetime.now(pytz.UTC).isoformat(),
                    "cache_hit": False,
                },
            }

            result = await has_evacuation_orders({"lookbackMinutes": 180})

            assert result["has_evacuation_orders"] is False
            assert len(result["supporting_incidents"]) == 0
            assert "No evacuation-related keywords" in result["notes"]

    @pytest.mark.asyncio
    async def test_has_evacuation_orders_custom_lookback(self):
        """Test evacuation detection with custom lookback time."""
        with patch("mcp_sfd.tools.has_evac_orders.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": [],
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": datetime.now(pytz.UTC).isoformat(),
                    "cache_hit": False,
                },
            }

            result = await has_evacuation_orders({"lookbackMinutes": 360})

            # Check that the lookback time is reflected in the response
            assert "360 minutes" in result["notes"]


class TestToolValidation:
    """Test input validation for all tools."""

    @pytest.mark.asyncio
    async def test_fetch_raw_invalid_order(self):
        """Test fetch_raw with invalid order parameter."""
        with pytest.raises(ValueError):
            await fetch_raw({"order": "invalid"})

    @pytest.mark.asyncio
    async def test_is_fire_active_invalid_lookback(self):
        """Test is_fire_active with invalid lookback parameter."""
        with pytest.raises(ValueError):
            await is_fire_active({"lookbackMinutes": 5})  # Below minimum

    @pytest.mark.asyncio
    async def test_has_evacuation_orders_invalid_lookback(self):
        """Test has_evacuation_orders with invalid lookback parameter."""
        with pytest.raises(ValueError):
            await has_evacuation_orders({"lookbackMinutes": 20})  # Below minimum

    @pytest.mark.asyncio
    async def test_latest_incident_extra_params(self):
        """Test that latest_incident ignores extra parameters."""
        # Should not raise an error even with extra params
        with patch("mcp_sfd.tools.latest_incident.fetch_raw") as mock_fetch:
            mock_fetch.return_value = {
                "incidents": [
                    {
                        "incident_number": "TEST-001",
                        "type": "Test",
                        "address": "Test",
                        "datetime_local": datetime.now(pytz.UTC).isoformat(),
                        "datetime_utc": datetime.now(pytz.UTC).isoformat(),
                        "latitude": None,
                        "longitude": None,
                        "report_location": None,
                        "computed_region_ru88_fbhk": None,
                        "computed_region_kuhn_3gp2": None,
                        "computed_region_q256_3sug": None,
                        "estimated_active": False,
                        "raw": None,
                    }
                ],
                "source": {
                    "url": "https://data.seattle.gov/resource/kzjm-xkqj.json",
                    "fetched_at": datetime.now(pytz.UTC).isoformat(),
                    "cache_hit": False,
                },
            }

            # This should work despite extra parameters
            result = await latest_incident({"extra_param": "value"})
            assert "incident" in result
