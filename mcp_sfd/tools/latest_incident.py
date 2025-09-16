"""
Implementation of sfd.latest_incident tool.

This tool returns the single latest incident by datetime from the SFD API.
"""

import logging
from typing import Any

from ..schemas import Incident, LatestIncidentInput, LatestIncidentResponse
from .fetch_raw import fetch_raw

logger = logging.getLogger(__name__)


async def latest_incident(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Returns the latest 10 incidents by datetime with pattern analysis logging.

    This tool fetches the 10 most recent incidents from the Seattle Fire Department
    by calling the fetch_raw tool with parameters optimized for getting recent
    incidents. It logs detailed information about each incident to help identify
    patterns in the data.

    Args:
        arguments: Tool arguments (empty dict, no parameters required)

    Returns:
        Latest incident for compatibility, plus all_incidents array and incident_count

    Raises:
        MCPToolError: If no incidents found or upstream errors occur
    """
    # Validate input (should be empty)
    try:
        LatestIncidentInput(**arguments)
    except Exception as e:
        logger.error(f"Invalid input arguments: {e}")
        raise ValueError(f"Invalid arguments: {e}") from e

    logger.info("Fetching latest 10 incidents for pattern analysis")

    # Call fetch_raw with parameters to get the latest 10 incidents
    fetch_args = {
        "order": "new",  # Get newest first
        "start": 0,  # From the beginning
        "length": 10,  # Get 10 incidents to analyze patterns
        "page": 1,  # First page
        "date": "Today",  # Today's incidents
        "dateEnd": "Today",  # Today's incidents
        "search": "Any",  # No filtering
        "location": "Any",  # No location filter
        "unit": "Any",  # No unit filter
        "type": "Any",  # No type filter
        "area": "Any",  # No area filter
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

    # Process and log info about each incident
    validated_incidents = []
    for i, incident_data in enumerate(incidents):
        try:
            incident = Incident(**incident_data)
            validated_incidents.append(incident)

            # Log descriptive info about each incident
            logger.info(
                f"Incident {i+1}/{len(incidents)} - {incident.type or 'UNKNOWN_TYPE'}",
                extra={
                    "incident_number": incident.incident_number or "NO_NUMBER",
                    "incident_type": incident.type or "UNKNOWN_TYPE",
                    "description": incident.description or "NO_DESCRIPTION",
                    "address": incident.address or "NO_ADDRESS",
                    "area": incident.area or "NO_AREA",
                    "units": incident.units or [],
                    "unit_count": len(incident.units) if incident.units else 0,
                    "active": incident.active,
                    "datetime_local": (
                        incident.datetime_local.isoformat()
                        if incident.datetime_local
                        else "NO_TIME"
                    ),
                    "latitude": incident.latitude,
                    "longitude": incident.longitude,
                    "raw_keys": list(incident.raw.keys()) if incident.raw else [],
                },
            )
        except Exception as e:
            logger.error(f"Failed to validate incident {i+1}: {e}")
            # Continue with other incidents instead of failing entirely
            continue

    if not validated_incidents:
        from ..http_client import MCPToolError

        raise MCPToolError("SCHEMA_VALIDATION_ERROR", "No valid incidents found")

    # Get the first (latest) incident for backward compatibility
    latest = validated_incidents[0]

    # Create response with all incidents
    response_data = {
        "incident": latest.model_dump(),  # Keep single incident for compatibility
        "all_incidents": [
            inc.model_dump() for inc in validated_incidents
        ],  # Add all incidents
        "incident_count": len(validated_incidents),
        "source": raw_response["source"],  # Pass the complete source object
    }

    # Note: We'll keep the existing LatestIncidentResponse schema for now
    # and add the extra fields which will be included in the raw output
    try:
        validated_response = LatestIncidentResponse(
            **{"incident": response_data["incident"], "source": response_data["source"]}
        )
        result = validated_response.model_dump()
        # Add our extra fields
        result["all_incidents"] = response_data["all_incidents"]
        result["incident_count"] = response_data["incident_count"]
    except Exception as e:
        logger.error(f"Response validation failed: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Response validation failed: {e}"
        ) from e

    logger.info(
        f"Successfully fetched {len(validated_incidents)} incidents",
        extra={
            "total_incidents": len(validated_incidents),
            "latest_incident_type": latest.type,
            "latest_datetime": (
                latest.datetime_local.isoformat()
                if latest.datetime_local
                else "NO_TIME"
            ),
        },
    )

    return result
