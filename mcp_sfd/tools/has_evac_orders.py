"""
Implementation of sfd.has_evacuation_orders tool.

This tool scans incident data for evacuation-related keywords to detect
potential evacuation orders or advisories.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, cast

import pytz

from ..schemas import (
    EVACUATION_KEYWORDS,
    HasEvacuationOrdersInput,
    HasEvacuationOrdersResponse,
    Incident,
)
from .fetch_raw import fetch_raw

logger = logging.getLogger(__name__)


def check_incident_for_evacuation(incident: Incident) -> bool:
    """
    Check if an incident contains evacuation-related keywords.

    Searches in description, description_clean, and other text fields
    for evacuation keywords (case insensitive).

    Args:
        incident: The incident to check

    Returns:
        True if evacuation keywords are found
    """
    # Collect all text fields to search
    text_fields = []

    if incident.description:
        text_fields.append(incident.description.lower())

    if incident.description_clean:
        text_fields.append(incident.description_clean.lower())

    if incident.type:
        text_fields.append(incident.type.lower())

    if incident.response_type:
        text_fields.append(incident.response_type.lower())

    if incident.response_mode:
        text_fields.append(incident.response_mode.lower())

    # Check for evacuation keywords in all text fields
    for text in text_fields:
        for keyword in EVACUATION_KEYWORDS:
            if keyword.lower() in text:
                logger.debug(
                    f"Found evacuation keyword '{keyword}' in incident {incident.id}",
                    extra={
                        "incident_id": incident.id,
                        "keyword": keyword,
                        "text_field": text[:100],  # First 100 chars for context
                    },
                )
                return True

    return False


def filter_incidents_by_timeframe(
    incidents: list[Incident], lookback_minutes: int
) -> list[Incident]:
    """
    Filter incidents to only include those within the lookback timeframe.

    Args:
        incidents: List of incidents to filter
        lookback_minutes: How many minutes back to include

    Returns:
        Filtered list of incidents within the timeframe
    """
    if lookback_minutes <= 0:
        return incidents

    cutoff_time = datetime.now(pytz.UTC) - timedelta(minutes=lookback_minutes)
    filtered = []

    for incident in incidents:
        if incident.datetime_utc >= cutoff_time:
            filtered.append(incident)

    logger.debug(
        f"Filtered {len(incidents)} incidents to {len(filtered)} within {lookback_minutes} minutes"
    )

    return filtered


async def has_evacuation_orders(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Check for evacuation orders in recent incidents.

    Scans incident descriptions for evacuation-related keywords and provides
    guidance about official evacuation information sources.

    Args:
        arguments: Tool arguments with optional lookback time

    Returns:
        Boolean result with supporting incidents and guidance notes

    Raises:
        MCPToolError: On upstream API errors or validation failures
    """
    # Validate input arguments
    try:
        input_data = HasEvacuationOrdersInput(**arguments)
    except Exception as e:
        logger.error(f"Invalid input arguments: {e}")
        raise ValueError(f"Invalid arguments: {e}") from e

    logger.info(
        "Checking for evacuation orders",
        extra={"lookback_minutes": input_data.lookbackMinutes},
    )

    # Fetch recent incidents with broader parameters to capture more data
    fetch_args = {
        "order": "new",  # Get newest first
        "start": 0,  # From the beginning
        "length": 200,  # Get more incidents for better coverage
        "page": 1,  # First page
        "date": "Today",  # Today's incidents
        "dateEnd": "Today",  # Today's incidents
        "search": "Any",  # No search filtering
        "location": "Any",  # No location filter
        "unit": "Any",  # No unit filter
        "type": "Any",  # No type filter
        "area": "Any",  # No area filter
        "cacheTtlSeconds": 30,  # Slightly longer cache for this analysis
    }

    # Get incidents data
    raw_response = await fetch_raw(fetch_args)
    all_incidents = [Incident(**inc) for inc in raw_response.get("incidents", [])]

    # Filter by timeframe
    recent_incidents = filter_incidents_by_timeframe(
        all_incidents, input_data.lookbackMinutes
    )

    # Check each incident for evacuation keywords
    evacuation_incidents = []
    for incident in recent_incidents:
        if check_incident_for_evacuation(incident):
            evacuation_incidents.append(incident)

    # Determine result
    has_evacuation = len(evacuation_incidents) > 0

    # Create guidance notes
    if has_evacuation:
        notes = (
            f"Found {len(evacuation_incidents)} incident(s) with evacuation-related keywords "
            f"in the last {input_data.lookbackMinutes} minutes. However, this data comes from "
            "the live incident feed and may not represent official evacuation orders. "
            "For authoritative evacuation information, check AlertSeattle, Seattle Emergency "
            "Management, or official Seattle Fire Department communications."
        )
    else:
        notes = (
            f"No evacuation-related keywords found in incident descriptions from the last "
            f"{input_data.lookbackMinutes} minutes. Note that official evacuation orders "
            "typically come from AlertSeattle, Seattle Emergency Management, or Seattle Fire "
            "Department official channels, not the live incident feed."
        )

    # Create response
    response_data = {
        "has_evacuation_orders": has_evacuation,
        "supporting_incidents": evacuation_incidents,
        "notes": notes,
    }

    # Validate output
    try:
        validated_response = HasEvacuationOrdersResponse(
            has_evacuation_orders=cast(bool, response_data["has_evacuation_orders"]),
            supporting_incidents=cast(
                list[Incident], response_data["supporting_incidents"]
            ),
            notes=cast(str, response_data["notes"]),
        )
        result = validated_response.model_dump()
    except Exception as e:
        logger.error(f"Response validation failed: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Response validation failed: {e}"
        ) from e

    logger.info(
        "Completed evacuation order check",
        extra={
            "has_evacuation": has_evacuation,
            "supporting_incidents": len(evacuation_incidents),
            "total_recent_incidents": len(recent_incidents),
            "lookback_minutes": input_data.lookbackMinutes,
        },
    )

    return result
