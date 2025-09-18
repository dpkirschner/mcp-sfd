"""
Data normalization utilities for Seattle Socrata API responses.

This module handles converting the Socrata API format into clean,
standardized data structures that match our Pydantic schemas.
"""

import logging
from datetime import datetime
from typing import Any

import pytz

from .schemas import Incident, ReportLocation, ResponseMeta

logger = logging.getLogger(__name__)

# Seattle timezone
SEATTLE_TZ = pytz.timezone("America/Los_Angeles")
UTC_TZ = pytz.UTC


def parse_datetime(dt_str: str) -> datetime:
    """
    Parse datetime string from Socrata API.

    Expected format: "2025-09-15T22:58:00.000" (ISO format)
    Assumes input is in UTC and converts to both UTC and local time.
    """
    # Handle empty/None strings early to avoid warnings
    if not dt_str or dt_str.strip() in ("", "None", "null"):
        logger.debug("Empty datetime string, using current time")
        return datetime.now(UTC_TZ)

    try:
        # Parse ISO format datetime (Socrata standard)
        # Remove trailing 'Z' if present and handle timezone
        clean_dt_str = dt_str.replace("Z", "+00:00")

        # Parse as ISO format
        parsed_dt = datetime.fromisoformat(clean_dt_str)

        # Ensure it's in UTC
        if parsed_dt.tzinfo is None:
            # Assume UTC if no timezone info
            utc_dt = UTC_TZ.localize(parsed_dt)
        else:
            utc_dt = parsed_dt.astimezone(UTC_TZ)

        return utc_dt
    except ValueError as e:
        logger.warning(f"Failed to parse datetime '{dt_str}': {e}")
        # Fallback: try to parse as old SFD format
        try:
            naive_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            local_dt = SEATTLE_TZ.localize(naive_dt)
            utc_dt = local_dt.astimezone(UTC_TZ)
            return utc_dt
        except ValueError:
            # Last resort: current time in UTC
            logger.error(f"Could not parse datetime '{dt_str}', using current time")
            return datetime.now(UTC_TZ)


def parse_coordinate(coord: str | int | float | None) -> float | None:
    """
    Parse latitude or longitude from Socrata format.

    Socrata returns coordinates as string representations of floats.
    """
    if coord is None:
        return None

    try:
        return float(coord)
    except (ValueError, TypeError):
        logger.warning(f"Could not parse coordinate: {coord}")
        return None


def parse_report_location(
    location_data: dict[str, Any] | None,
) -> ReportLocation | None:
    """
    Parse the report_location field from Socrata.

    Expected format:
    {
        "type": "Point",
        "coordinates": [longitude, latitude]
    }
    """
    if not location_data or not isinstance(location_data, dict):
        return None

    try:
        return ReportLocation(
            type=location_data.get("type", "Point"),
            coordinates=location_data.get("coordinates", []),
        )
    except Exception as e:
        logger.warning(f"Failed to parse report_location: {e}")
        return None


def estimate_incident_active(datetime_utc: datetime) -> bool:
    """
    Estimate if an incident is still active based on its timestamp.

    Since Socrata data doesn't include active status, we use a heuristic:
    - Incidents within the last 30 minutes are considered "likely active"
    - This is a rough approximation for compatibility with existing tools
    """
    now = datetime.now(UTC_TZ)
    time_diff = now - datetime_utc

    # Consider incidents active if they're less than 30 minutes old
    return time_diff.total_seconds() < (30 * 60)


def normalize_incident(raw_incident: dict[str, Any]) -> Incident:
    """
    Normalize a single incident from Socrata format to our schema.

    Socrata incident format:
    {
        "address": "1601 5th Ave",
        "type": "Auto Fire Alarm",
        "datetime": "2025-09-15T22:58:00.000",
        "latitude": "47.611672",
        "longitude": "-122.336484",
        "report_location": {
            "type": "Point",
            "coordinates": [-122.336484, 47.611672]
        },
        "incident_number": "F250128483",
        ":@computed_region_ru88_fbhk": "14",
        ":@computed_region_kuhn_3gp2": "31",
        ":@computed_region_q256_3sug": "18081"
    }
    """
    try:
        # Parse datetime fields
        datetime_str = raw_incident.get("datetime", "")
        datetime_utc = parse_datetime(datetime_str)
        datetime_local = datetime_utc.astimezone(SEATTLE_TZ)

        # Parse coordinates
        latitude = parse_coordinate(raw_incident.get("latitude"))
        longitude = parse_coordinate(raw_incident.get("longitude"))

        # Parse report location
        report_location = parse_report_location(raw_incident.get("report_location"))

        # Estimate if incident is active (time-based heuristic)
        estimated_active = estimate_incident_active(datetime_utc)

        # Create normalized incident
        incident = Incident(
            incident_number=str(raw_incident.get("incident_number", "")),
            type=str(raw_incident.get("type", "")),
            address=str(raw_incident.get("address", "")),
            datetime_local=datetime_local,
            datetime_utc=datetime_utc,
            latitude=latitude,
            longitude=longitude,
            report_location=report_location,
            # Computed region fields from Socrata
            computed_region_ru88_fbhk=raw_incident.get(":@computed_region_ru88_fbhk"),
            computed_region_kuhn_3gp2=raw_incident.get(":@computed_region_kuhn_3gp2"),
            computed_region_q256_3sug=raw_incident.get(":@computed_region_q256_3sug"),
            # Derived fields
            estimated_active=estimated_active,
            raw=raw_incident,  # Preserve original for debugging
        )

        return incident

    except Exception as e:
        logger.error(
            f"Failed to normalize incident: {e}", extra={"raw_incident": raw_incident}
        )
        raise


def normalize_response_meta(
    incidents_count: int, query_params: dict[str, Any]
) -> ResponseMeta:
    """Normalize response metadata for Socrata API response."""
    order = query_params.get("$order", "datetime DESC")
    # Convert Socrata order to our format
    if "DESC" in order:
        order_normalized = "new"
    else:
        order_normalized = "old"

    return ResponseMeta(
        results_returned=incidents_count,
        order=order_normalized,
        limit=int(query_params.get("$limit", 100)),
        offset=int(query_params.get("$offset", 0)),
        query_params=query_params,
    )


def normalize_full_response(
    raw_incidents: list[dict[str, Any]],
    request_url: str,
    cache_hit: bool,
    query_params: dict[str, Any],
) -> dict[str, Any]:
    """
    Normalize the complete Socrata API response.

    This is the main entry point for data normalization.
    Socrata returns incidents as a simple array, much simpler than sfdlive.
    """
    try:
        # Normalize each incident
        incidents = []
        for raw_incident in raw_incidents:
            try:
                incident = normalize_incident(raw_incident)
                incidents.append(incident)
            except Exception as e:
                logger.error(f"Skipping malformed incident: {e}")
                continue

        # Normalize metadata
        meta = normalize_response_meta(len(incidents), query_params)

        # Create normalized response
        normalized = {
            "meta": meta.model_dump(),
            "incidents": [incident.model_dump() for incident in incidents],
            "source": {
                "url": request_url,
                "fetched_at": datetime.now(UTC_TZ).isoformat(),
                "cache_hit": cache_hit,
            },
        }

        logger.info(
            f"Normalized Socrata response with {len(incidents)} incidents",
            extra={
                "incident_count": len(incidents),
                "cache_hit": cache_hit,
                "query_params": query_params,
            },
        )

        return normalized

    except Exception as e:
        logger.error(f"Failed to normalize Socrata response: {e}")
        raise
