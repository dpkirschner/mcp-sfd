"""
Implementation of sfd.active_incidents tool.

This tool fetches and returns only currently active incidents from the Seattle
Fire Department API, providing a focused view of ongoing emergency situations.
"""

import logging
from typing import Any

from ..http_client import get_client
from ..normalize import normalize_full_response
from ..schemas import FetchRawInput, Incident, ActiveIncidentSummary, ActiveIncidentsLightResponse

logger = logging.getLogger(__name__)


async def active_incidents(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Fetch only active incidents from the SFD API.

    This tool is optimized for getting a current snapshot of ongoing
    emergency situations by filtering for incidents marked as active.

    Args:
        arguments: Tool arguments (optional: cacheTtlSeconds)

    Returns:
        Response containing only active incidents with metadata

    Raises:
        MCPToolError: On upstream API errors, timeouts, or validation failures
    """
    # Parse optional cache TTL argument
    cache_ttl = arguments.get("cacheTtlSeconds", 15)
    if not isinstance(cache_ttl, int) or cache_ttl < 0:
        cache_ttl = 15

    # Use fetch_raw parameters optimized for active incidents
    # We'll fetch a reasonable number and filter client-side since the API
    # doesn't have a direct "active only" filter
    query_params = {
        "draw": 1,
        "order": "new",  # Get newest first
        "start": 0,
        "length": 100,  # Get enough to ensure we capture all active incidents
        "search": "Any",
        "page": 1,
        "location": "Any",
        "unit": "Any",
        "type": "Any",
        "area": "Any",
        "date": "Today",  # Only today's incidents are likely to be active
        "dateEnd": "Today",
    }

    logger.info(
        "Fetching active SFD incidents",
        extra={
            "cache_ttl": cache_ttl,
            "filter": "active_only",
        },
    )

    # Get HTTP client and make request
    client = await get_client()
    raw_response, cache_hit = await client.fetch_incidents(query_params, cache_ttl)

    # Construct the request URL for source information
    base_url = client.base_url
    query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
    request_url = f"{base_url}?{query_string}"

    # Normalize the response
    try:
        normalized_response = normalize_full_response(
            raw_response, request_url, cache_hit
        )
    except Exception as e:
        logger.error(f"Failed to normalize response: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Failed to parse upstream response: {e}"
        )

    # Filter for active incidents only
    all_incidents = []
    for incident_data in normalized_response["incidents"]:
        incident = Incident(**incident_data)
        all_incidents.append(incident)

    # Filter to active incidents only
    active_incidents_list = [
        incident for incident in all_incidents if incident.active
    ]

    # Create lightweight summaries to reduce token usage
    incident_summaries = []
    for incident in active_incidents_list:
        # Format time as simple "6:55 PM" format
        time_str = incident.datetime_local.strftime("%-I:%M %p")

        summary = ActiveIncidentSummary(
            id=incident.id,
            incident_number=incident.incident_number,
            type=incident.type,
            description=incident.description_clean or incident.description,
            time=time_str,
            address=incident.address,
            area=incident.area,
            units=incident.units,
            active=incident.active,
        )
        incident_summaries.append(summary)

    # Create lightweight response
    light_response = ActiveIncidentsLightResponse(
        count=len(incident_summaries),
        incidents=incident_summaries,
        fetched_at=normalized_response["source"]["fetched_at"],
        cache_hit=normalized_response["source"]["cache_hit"],
    )

    filtered_response = light_response.model_dump()

    logger.info(
        "Successfully filtered for active incidents (lightweight response)",
        extra={
            "total_incidents": len(all_incidents),
            "active_incidents": len(incident_summaries),
            "cache_hit": cache_hit,
            "token_reduction": "lightweight_summaries",
        },
    )

    return filtered_response