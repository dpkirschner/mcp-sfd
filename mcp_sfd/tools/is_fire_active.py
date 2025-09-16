"""
Implementation of sfd.is_fire_active tool.

This tool detects active fire incidents by analyzing incident types,
descriptions, and unit status information.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import pytz

from ..schemas import (
    FIRE_EXCLUSIONS,
    FIRE_KEYWORDS,
    Incident,
    IsFireActiveInput,
    IsFireActiveResponse,
)
from .fetch_raw import fetch_raw

logger = logging.getLogger(__name__)


def is_fire_related_incident(incident: Incident) -> tuple[bool, str]:
    """
    Determine if an incident is fire-related based on type and description.

    Args:
        incident: The incident to analyze

    Returns:
        Tuple of (is_fire_related, reason)
    """
    # Collect text fields to check
    text_fields = {
        "type": incident.type or "",
        "description": incident.description or "",
        "description_clean": incident.description_clean or "",
        "type_code": incident.type_code or "",
    }

    # Check for fire keywords
    fire_indicators = []
    for field_name, text in text_fields.items():
        text_lower = text.lower()
        for keyword in FIRE_KEYWORDS:
            if keyword.lower() in text_lower:
                fire_indicators.append(f"{keyword} in {field_name}")

    # Special handling for exclusions
    if fire_indicators:
        for exclusion in FIRE_EXCLUSIONS:
            # Check if this is a water rescue
            if exclusion.lower() in text_fields["type"].lower():
                # Only exclude if description doesn't mention fire
                description_text = (
                    text_fields["description"] + " " + text_fields["description_clean"]
                ).lower()
                if "fire" not in description_text:
                    return False, f"Excluded {exclusion} without fire in description"

    if fire_indicators:
        return True, f"Fire keywords found: {', '.join(fire_indicators)}"

    return False, "No fire-related keywords found"


def is_incident_still_active(
    incident: Incident, lookback_minutes: int
) -> tuple[bool, str]:
    """
    Determine if an incident is still active based on status and timing.

    An incident is considered active if:
    1. The 'active' field is True, OR
    2. The incident occurred within lookback_minutes AND no units have 'in_service' status

    Args:
        incident: The incident to analyze
        lookback_minutes: How far back to consider incidents active

    Returns:
        Tuple of (is_active, reason)
    """
    # Check the explicit active flag first
    if incident.active:
        return True, "Incident marked as active"

    # Check if incident is within the lookback window
    cutoff_time = datetime.now(pytz.UTC) - timedelta(minutes=lookback_minutes)
    if incident.datetime_utc < cutoff_time:
        return False, f"Incident older than {lookback_minutes} minutes"

    # Check unit status - if ANY unit is in service, incident is likely inactive
    units_in_service = []
    units_not_in_service = []

    for unit_name, status in incident.unit_status.items():
        if status.in_service:
            units_in_service.append(unit_name)
        else:
            units_not_in_service.append(unit_name)

    if units_in_service:
        return False, f"Units {', '.join(units_in_service)} marked as in service"

    # If no units have in_service status and incident is recent, consider active
    if units_not_in_service:
        return (
            True,
            f"Recent incident with units {', '.join(units_not_in_service)} still responding",
        )

    # If no unit status information, consider active if recent
    return (
        True,
        f"Recent incident within {lookback_minutes} minutes with no unit status data",
    )


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


async def is_fire_active(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Check if there are any active fire incidents in Seattle.

    Analyzes recent incidents to determine if any fire-related incidents
    are currently active based on type detection and unit status.

    Args:
        arguments: Tool arguments with optional lookback time

    Returns:
        Boolean result with matching incidents and reasoning

    Raises:
        MCPToolError: On upstream API errors or validation failures
    """
    # Validate input arguments
    try:
        input_data = IsFireActiveInput(**arguments)
    except Exception as e:
        logger.error(f"Invalid input arguments: {e}")
        raise ValueError(f"Invalid arguments: {e}")

    logger.info(
        "Checking for active fire incidents",
        extra={"lookback_minutes": input_data.lookbackMinutes},
    )

    # Fetch recent incidents with broader parameters for better coverage
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

    # Log sample of incidents to understand data patterns
    logger.info(f"Fetched {len(all_incidents)} total incidents for analysis")
    for i, incident in enumerate(all_incidents[:5]):  # Log first 5 incidents
        logger.info(
            f"Sample incident {i+1}/5",
            extra={
                "incident_id": incident.id,
                "incident_number": incident.incident_number or "EMPTY",
                "type": incident.type or "EMPTY",
                "description": incident.description or "EMPTY",
                "address": incident.address or "EMPTY",
                "active": incident.active,
                "units": incident.units or [],
                "unit_count": len(incident.units) if incident.units else 0,
                "datetime_local": incident.datetime_local.isoformat() if incident.datetime_local else "NO_TIME",
                "raw_data_keys": list(incident.raw.keys()) if incident.raw else [],
                "raw_name": incident.raw.get("name") if incident.raw else None,
                "raw_zoning": incident.raw.get("zoning") if incident.raw else None,
            }
        )

    # Filter by timeframe
    recent_incidents = filter_incidents_by_timeframe(
        all_incidents, input_data.lookbackMinutes
    )

    logger.info(f"Filtered to {len(recent_incidents)} incidents within {input_data.lookbackMinutes} minutes")

    # Analyze incidents for fire activity
    active_fire_incidents = []
    analysis_details = []

    logger.info(f"Analyzing {len(recent_incidents)} recent incidents for fire activity")

    for i, incident in enumerate(recent_incidents):
        # Log detailed info about each incident being analyzed
        logger.info(
            f"Analyzing incident {i+1}/{len(recent_incidents)}",
            extra={
                "incident_id": incident.id,
                "incident_number": incident.incident_number or "EMPTY",
                "type": incident.type or "EMPTY",
                "description": incident.description or "EMPTY",
                "address": incident.address or "EMPTY",
                "active_flag": incident.active,
                "units": incident.units or [],
                "unit_status": incident.unit_status or {},
                "datetime_local": incident.datetime_local.isoformat() if incident.datetime_local else "NO_TIME",
                "raw_name": incident.raw.get("name") if incident.raw else None,
                "raw_zoning": incident.raw.get("zoning") if incident.raw else None,
            }
        )

        # Check if fire-related
        is_fire, fire_reason = is_fire_related_incident(incident)

        logger.info(
            f"Fire analysis for incident {i+1}: is_fire={is_fire}, reason='{fire_reason}'"
        )

        if not is_fire:
            continue

        # Check if still active
        is_active, active_reason = is_incident_still_active(
            incident, input_data.lookbackMinutes
        )

        logger.info(
            f"Activity analysis for incident {i+1}: is_active={is_active}, reason='{active_reason}'"
        )

        analysis_details.append(
            {
                "incident_id": incident.id,
                "incident_number": incident.incident_number,
                "type": incident.type,
                "is_fire": is_fire,
                "fire_reason": fire_reason,
                "is_active": is_active,
                "active_reason": active_reason,
            }
        )

        if is_active:
            active_fire_incidents.append(incident)

    # Determine overall result
    is_fire_active_result = len(active_fire_incidents) > 0

    # Create reasoning
    if is_fire_active_result:
        active_count = len(active_fire_incidents)
        reasoning = (
            f"Found {active_count} active fire incident(s) within the last "
            f"{input_data.lookbackMinutes} minutes. "
        )

        # Add details about the active incidents
        incident_details = []
        for incident in active_fire_incidents[:3]:  # Limit to first 3 for brevity
            detail = f"Incident {incident.incident_number} ({incident.type})"
            incident_details.append(detail)

        if incident_details:
            reasoning += f"Active incidents: {', '.join(incident_details)}"
            if len(active_fire_incidents) > 3:
                reasoning += f" and {len(active_fire_incidents) - 3} more."
    else:
        fire_count = sum(1 for detail in analysis_details if detail["is_fire"])
        if fire_count > 0:
            reasoning = (
                f"Found {fire_count} fire-related incident(s) in the last "
                f"{input_data.lookbackMinutes} minutes, but none are currently active. "
                "Units have either completed service or incidents are marked inactive."
            )
        else:
            reasoning = (
                f"No fire-related incidents detected in the last "
                f"{input_data.lookbackMinutes} minutes."
            )

    # Create response
    response_data = {
        "is_fire_active": is_fire_active_result,
        "matching_incidents": [inc.model_dump() for inc in active_fire_incidents],
        "reasoning": reasoning,
    }

    # Validate output
    try:
        validated_response = IsFireActiveResponse(**response_data)
        result = validated_response.model_dump()
    except Exception as e:
        logger.error(f"Response validation failed: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Response validation failed: {e}"
        )

    logger.info(
        "Completed fire activity check",
        extra={
            "is_fire_active": is_fire_active_result,
            "active_fire_incidents": len(active_fire_incidents),
            "total_recent_incidents": len(recent_incidents),
            "fire_related_incidents": sum(1 for d in analysis_details if d["is_fire"]),
            "lookback_minutes": input_data.lookbackMinutes,
        },
    )

    return result
