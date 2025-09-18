"""
Implementation of sfd.latest_incident tool.

This tool returns the single latest incident by datetime from the Socrata API.
"""

import logging
from typing import Any

from ..schemas import Incident, LatestIncidentInput, LatestIncidentResponse
from .fetch_raw import fetch_raw

logger = logging.getLogger(__name__)


async def latest_incident(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Returns the single latest incident by datetime.

    This tool fetches the most recent incident from the Seattle Fire Department
    via Socrata API by calling the fetch_raw tool with parameters optimized
    for getting the single latest incident.

    Args:
        arguments: Tool arguments (empty dict, no parameters required)

    Returns:
        Latest incident data

    Raises:
        MCPToolError: If no incidents found or upstream errors occur
    """
    # Validate input (should be empty)
    try:
        LatestIncidentInput(**arguments)
    except Exception as e:
        logger.error(f"Invalid input arguments: {e}")
        raise ValueError(f"Invalid arguments: {e}") from e

    logger.info("Fetching latest incident from Socrata")

    # Call fetch_raw with parameters to get the latest single incident
    fetch_args = {
        "order": "new",  # Get newest first
        "start": 0,  # From the beginning
        "length": 1,  # Get only 1 incident (the latest)
        "page": 1,  # First page
        "date": "Today",  # Today's incidents
        "dateEnd": "Today",  # Today's incidents
        "search": "Any",  # No filtering
        "location": "Any",  # No location filter
        "unit": "Any",  # No unit filter (ignored in Socrata)
        "type": "Any",  # No type filter
        "area": "Any",  # No area filter (ignored in Socrata)
        "cacheTtlSeconds": 15,  # Short cache for latest data
    }

    # Get the raw response
    raw_response = await fetch_raw(fetch_args)

    # Extract incidents
    incidents = raw_response.get("incidents", [])
    if not incidents:
        from ..http_client import MCPToolError

        logger.warning("No incidents found in latest incident query")
        raise MCPToolError("UPSTREAM_HTTP_ERROR", "No incidents found for today")

    # Get the latest incident (should be the first and only one)
    latest_incident_data = incidents[0]

    # Validate the incident
    try:
        latest = Incident(**latest_incident_data)
    except Exception as e:
        logger.error(f"Failed to validate latest incident: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Invalid incident data: {e}"
        ) from e

    # Log info about the latest incident
    logger.info(
        f"Latest incident: {latest.type}",
        extra={
            "incident_number": latest.incident_number,
            "incident_type": latest.type,
            "address": latest.address,
            "estimated_active": latest.estimated_active,
            "datetime_local": latest.datetime_local.isoformat(),
            "latitude": latest.latitude,
            "longitude": latest.longitude,
        },
    )

    # Create response
    response_data = {
        "incident": latest.model_dump(),
        "source": raw_response["source"],
    }

    # Validate response against schema
    try:
        validated_response = LatestIncidentResponse(**response_data)
        result = validated_response.model_dump()
    except Exception as e:
        logger.error(f"Response validation failed: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Response validation failed: {e}"
        ) from e

    logger.info(
        "Successfully fetched latest incident",
        extra={
            "incident_type": latest.type,
            "datetime": latest.datetime_local.isoformat(),
        },
    )

    return result
