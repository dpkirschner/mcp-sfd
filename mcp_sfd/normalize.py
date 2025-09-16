"""
Data normalization utilities for SFD API responses.

This module handles the complex task of converting the upstream API format
into clean, standardized data structures that match our Pydantic schemas.
"""

import logging
import re
from datetime import datetime
from typing import Any

import pytz

from .schemas import Incident, ResponseMeta, UnitStatus

logger = logging.getLogger(__name__)

# Seattle timezone
SEATTLE_TZ = pytz.timezone("America/Los_Angeles")
UTC_TZ = pytz.UTC


def parse_datetime(dt_str: str) -> datetime:
    """
    Parse datetime string from SFD API.

    Assumes input is in Seattle local time and converts to UTC.
    Expected format: "2025-09-15 16:05:27"
    """
    # Handle empty/None strings early to avoid warnings
    if not dt_str or dt_str.strip() in ("", "None", "null"):
        logger.debug("Empty datetime string, using current time")
        return datetime.now(UTC_TZ)

    try:
        # Parse as naive datetime
        naive_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")

        # Localize to Seattle timezone
        local_dt = SEATTLE_TZ.localize(naive_dt)

        # Convert to UTC
        utc_dt = local_dt.astimezone(UTC_TZ)

        return utc_dt
    except ValueError as e:
        logger.warning(f"Failed to parse datetime '{dt_str}': {e}")
        # Fallback: try to parse as ISO format
        try:
            iso_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            # Convert to pytz.UTC for consistency
            return iso_dt.astimezone(UTC_TZ)
        except ValueError:
            # Last resort: current time in UTC
            logger.error(f"Could not parse datetime '{dt_str}', using current time")
            return datetime.now(UTC_TZ)


def parse_coordinate(
    coord: str | int | float | dict[str, Any] | None,
) -> float | None:
    """
    Parse latitude or longitude from various formats.

    Handles:
    - Float/int values directly
    - String representations of numbers
    - Objects with 'parsedValue' field
    - None/missing values
    """
    if coord is None:
        return None

    # Handle dict format with parsedValue
    if isinstance(coord, dict):
        if "parsedValue" in coord:
            try:
                return float(coord["parsedValue"])
            except (ValueError, TypeError):
                logger.warning(f"Could not parse coordinate from parsedValue: {coord}")
                return None
        # Try to find any numeric field
        for key in ["value", "lat", "lng", "latitude", "longitude"]:
            if key in coord:
                try:
                    return float(coord[key])
                except (ValueError, TypeError):
                    continue
        return None

    # Handle string/numeric values
    try:
        return float(coord)
    except (ValueError, TypeError):
        logger.warning(f"Could not parse coordinate: {coord}")
        return None


def parse_units(units_str: str) -> list[str]:
    """
    Parse units string into list of unit identifiers.

    Examples:
    - "E16*" -> ["E16"]
    - "E16*, E32" -> ["E16", "E32"]
    - "L15,E27*,M12" -> ["L15", "E27", "M12"]
    """
    if not units_str or units_str.strip() in ("", "None", "null"):
        return []

    # Split by comma and clean each unit
    units = []
    for unit in re.split(r"[,\s]+", units_str):
        # Remove trailing markers like *, +, etc.
        clean_unit = re.sub(r"[*+\-#]+$", "", unit.strip())
        if clean_unit:
            units.append(clean_unit)

    return units


def parse_boolean(value: Any) -> bool:
    """Parse boolean from various formats (1/0, true/false, etc.)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return False


def parse_unit_status(status_data: dict[str, Any]) -> dict[str, UnitStatus]:
    """
    Parse unit status information from upstream format.

    Expected to be a dict where keys are unit names and values contain
    timestamp information for dispatched, arrived, transport, in_service.
    """
    unit_status = {}

    if not isinstance(status_data, dict):
        return unit_status

    for unit_name, timestamps in status_data.items():
        if not isinstance(timestamps, dict):
            continue

        unit_status[unit_name] = UnitStatus(
            dispatched=timestamps.get("dispatched"),
            arrived=timestamps.get("arrived"),
            transport=timestamps.get("transport"),
            in_service=timestamps.get("in_service"),
        )

    return unit_status


def normalize_incident(raw_incident: dict[str, Any]) -> Incident:
    """
    Normalize a single incident from upstream format to our schema.

    Handles all the complex parsing and field mapping.
    """
    try:
        # Parse datetime fields
        datetime_str = raw_incident.get("datetime", "")
        if not datetime_str:
            # Try alternative field names
            datetime_str = raw_incident.get("timestamp", raw_incident.get("time", ""))

        datetime_utc = parse_datetime(datetime_str)
        datetime_local = datetime_utc.astimezone(SEATTLE_TZ)

        # Parse coordinates
        latitude = parse_coordinate(raw_incident.get("latitude"))
        longitude = parse_coordinate(raw_incident.get("longitude"))

        # Parse units
        units_raw = raw_incident.get("units_dispatched", raw_incident.get("units", ""))
        if isinstance(units_raw, list):
            units = [str(unit) for unit in units_raw]
        else:
            units = parse_units(str(units_raw))

        # Parse unit status
        unit_status = parse_unit_status(raw_incident.get("unit_status", {}))

        # Create normalized incident
        incident = Incident(
            id=int(raw_incident.get("id", 0)),
            incident_number=str(raw_incident.get("incident_number", "")),
            type=str(raw_incident.get("type", "")),
            type_code=raw_incident.get("type_code"),
            description=str(raw_incident.get("description", "")),
            description_clean=raw_incident.get("description_clean"),
            response_type=raw_incident.get("response_type"),
            response_mode=raw_incident.get("response_mode"),
            datetime_local=datetime_local,
            datetime_utc=datetime_utc,
            latitude=latitude,
            longitude=longitude,
            address=str(raw_incident.get("address", "")),
            area=raw_incident.get("area"),
            battalion=raw_incident.get("battalion"),
            units=units,
            primary_unit=raw_incident.get("primary_unit"),
            unit_status=unit_status,
            active=parse_boolean(raw_incident.get("active", False)),
            alarm=raw_incident.get("alarm"),
            late=parse_boolean(raw_incident.get("late", False)),
            raw=raw_incident,  # Preserve original for debugging
        )

        return incident

    except Exception as e:
        logger.error(
            f"Failed to normalize incident: {e}", extra={"raw_incident": raw_incident}
        )
        raise


def flatten_data_array(data: list[Any]) -> list[dict[str, Any]]:
    """
    Flatten the upstream data array format.

    The current SFD API returns incidents directly as dictionary objects in an array.
    This function handles both the old nested format and the current direct format.

    Current format: [{...incident...}, {...incident...}]
    Old format: [{"0": {...incident...}}, {"1": {...incident...}}]
    """
    incidents = []

    for item in data:
        if not isinstance(item, dict):
            continue

        # Check if this looks like an incident object directly
        # Incidents should have keys like 'id', 'address', 'type', 'incident_number'
        incident_keys = {"id", "address", "type", "incident_number", "datetime"}
        if any(key in item for key in incident_keys):
            # This is already an incident object, use it directly
            incidents.append(item)
            continue

        # Legacy format: Look for incident data nested under numeric keys
        incident_data = None
        if "0" in item:
            incident_data = item["0"]
        else:
            # Find the first dict value that looks like an incident
            for value in item.values():
                if isinstance(value, dict) and any(
                    key in value for key in incident_keys
                ):
                    incident_data = value
                    break

        if incident_data:
            incidents.append(incident_data)

    return incidents


def normalize_response_meta(raw_response: dict[str, Any]) -> ResponseMeta:
    """Normalize response metadata from upstream format."""
    return ResponseMeta(
        page=int(raw_response.get("page", 1)),
        total_pages=raw_response.get("recordsTotal"),
        results_per_page=int(
            raw_response.get("length", raw_response.get("recordsFiltered", 0))
        ),
        total_incidents=raw_response.get("recordsTotal"),
        offset=raw_response.get("start"),
        order=raw_response.get("order", "new"),
        users_online=raw_response.get("users_online"),
    )


def normalize_full_response(
    raw_response: dict[str, Any], request_url: str, cache_hit: bool
) -> dict[str, Any]:
    """
    Normalize the complete API response.

    This is the main entry point for data normalization.
    """
    try:
        # Extract and flatten incidents data
        raw_data = raw_response.get("data", [])
        flattened_incidents = flatten_data_array(raw_data)

        # Normalize each incident
        incidents = []
        for raw_incident in flattened_incidents:
            try:
                incident = normalize_incident(raw_incident)
                incidents.append(incident)
            except Exception as e:
                logger.error(f"Skipping malformed incident: {e}")
                continue

        # Normalize metadata
        meta = normalize_response_meta(raw_response)

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
            f"Normalized response with {len(incidents)} incidents",
            extra={
                "incident_count": len(incidents),
                "cache_hit": cache_hit,
                "page": meta.page,
            },
        )

        return normalized

    except Exception as e:
        logger.error(f"Failed to normalize response: {e}")
        raise
