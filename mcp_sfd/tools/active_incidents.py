"""
Implementation of sfd.active_incidents tool.

This tool fetches and returns only currently active incidents from the Seattle
Fire Department via Socrata API, using time-based heuristics for activity.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from ..http_client import get_client
from ..normalize import normalize_full_response
from ..schemas import (
    ActiveIncidentsLightResponse,
    ActiveIncidentSummary,
    FetchRawInput,
    Incident,
)
from .fetch_raw import build_socrata_query_params

logger = logging.getLogger(__name__)


async def active_incidents(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Fetch only active incidents from the Socrata API.

    Since Socrata data doesn't include active status, this tool uses time-based
    heuristics to estimate which incidents are likely still active (within last 30 minutes).

    Args:
        arguments: Tool arguments (optional: cacheTtlSeconds)

    Returns:
        Response containing only estimated active incidents with metadata

    Raises:
        MCPToolError: On upstream API errors, timeouts, or validation failures
    """
    # Parse optional cache TTL argument
    cache_ttl = arguments.get("cacheTtlSeconds", 15)
    if not isinstance(cache_ttl, int) or cache_ttl < 0:
        cache_ttl = 15

    logger.info(
        "Fetching active incidents from Socrata (using time heuristics)",
        extra={
            "cache_ttl": cache_ttl,
            "filter": "time_based_active_estimation",
        },
    )

    # Build query to fetch recent incidents (last 2 hours to ensure we catch any active ones)
    now = datetime.now()
    start_time = now - timedelta(hours=2)

    # Create input parameters for query building
    input_data = FetchRawInput(
        order="new",  # Get newest first
        start=0,
        length=200,  # Get enough recent incidents
        search="Any",
        page=1,
        location="Any",
        unit="Any",
        type="Any",
        area="Any",
        date=start_time.strftime("%Y-%m-%d"),  # Go back 2 hours
        dateEnd=now.strftime("%Y-%m-%d"),
        cacheTtlSeconds=cache_ttl,
    )

    # Build Socrata query parameters
    query_params = build_socrata_query_params(input_data)

    # Override the date filter to get more recent incidents
    where_clauses = []
    # Get incidents from the last 2 hours
    cutoff_time = start_time.strftime("%Y-%m-%dT%H:%M:%S.000")
    where_clauses.append(f"datetime >= '{cutoff_time}'")

    query_params["$where"] = " AND ".join(where_clauses)
    query_params["cacheTtlSeconds"] = cache_ttl

    # Get HTTP client and make request
    client = await get_client()
    raw_incidents, cache_hit = await client.fetch_incidents(query_params, cache_ttl)

    # Construct the request URL for source information
    base_url = client.base_url
    query_items = []
    for k, v in query_params.items():
        if k != "cacheTtlSeconds":
            query_items.append(f"{k}={v}")
    query_string = "&".join(query_items)
    request_url = f"{base_url}?{query_string}"

    # Normalize the response
    try:
        normalized_response = normalize_full_response(
            raw_incidents, request_url, cache_hit, query_params
        )
    except Exception as e:
        logger.error(f"Failed to normalize response: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Failed to parse Socrata response: {e}"
        ) from e

    # Filter for estimated active incidents only
    all_incidents = []
    for incident_data in normalized_response["incidents"]:
        incident = Incident(**incident_data)
        all_incidents.append(incident)

    # Filter to estimated active incidents only (using time heuristic)
    active_incidents_list = [
        incident for incident in all_incidents if incident.estimated_active
    ]

    # Create lightweight summaries to reduce token usage
    incident_summaries = []
    for incident in active_incidents_list:
        # Format time as simple "6:55 PM" format
        time_str = incident.datetime_local.strftime("%-I:%M %p")

        summary = ActiveIncidentSummary(
            incident_number=incident.incident_number,
            type=incident.type,
            time=time_str,
            address=incident.address,
            estimated_active=incident.estimated_active,
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
        "Successfully estimated active incidents using time heuristics",
        extra={
            "total_incidents": len(all_incidents),
            "estimated_active_incidents": len(incident_summaries),
            "cache_hit": cache_hit,
            "method": "time_based_estimation",
            "cutoff_minutes": 30,
        },
    )

    return filtered_response
