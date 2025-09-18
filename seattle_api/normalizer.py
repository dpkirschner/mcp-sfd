"""Data normalization functions for Seattle Fire Department incidents."""

import logging
import re
from datetime import datetime
from typing import List

import pytz

from .models import RawIncident, Incident, IncidentStatus

logger = logging.getLogger(__name__)


class NormalizationError(Exception):
    """Exception raised when data normalization fails."""
    pass


class IncidentNormalizer:
    """Normalizes raw incident data into structured Incident objects."""

    def __init__(self):
        """Initialize the normalizer."""
        self.seattle_tz = pytz.timezone('America/Los_Angeles')

    def normalize_incident(self, raw_incident: RawIncident) -> Incident:
        """Normalize a raw incident into a structured Incident.

        Args:
            raw_incident: Raw incident data from HTML parsing

        Returns:
            Normalized Incident object

        Raises:
            NormalizationError: When normalization fails
        """
        try:
            # Parse datetime
            incident_datetime = self._parse_datetime(raw_incident.datetime_str)

            # Parse priority
            priority = self._parse_priority(raw_incident.priority_str)

            # Parse units
            units = self._parse_units(raw_incident.units_str)

            # Current time for tracking
            now = datetime.utcnow()

            return Incident(
                incident_id=raw_incident.incident_id,
                incident_datetime=incident_datetime,
                priority=priority,
                units=units,
                address=raw_incident.address,
                incident_type=raw_incident.incident_type,
                status=IncidentStatus.ACTIVE,  # New incidents are active
                first_seen=now,
                last_seen=now,
                closed_at=None
            )

        except Exception as e:
            raise NormalizationError(f"Failed to normalize incident {raw_incident.incident_id}: {e}") from e

    def _parse_datetime(self, datetime_str: str) -> datetime:
        """Parse datetime string to UTC datetime.

        Args:
            datetime_str: Datetime string in format "M/D/YYYY H:MM:SS AM/PM"

        Returns:
            UTC datetime object

        Raises:
            NormalizationError: When datetime parsing fails
        """
        if not datetime_str:
            raise NormalizationError("Empty datetime string")

        try:
            # Try common format: "9/17/2025 8:39:31 PM"
            dt = datetime.strptime(datetime_str, "%m/%d/%Y %I:%M:%S %p")

            # Localize to Seattle timezone
            seattle_dt = self.seattle_tz.localize(dt)

            # Convert to UTC
            utc_dt = seattle_dt.astimezone(pytz.UTC).replace(tzinfo=None)

            return utc_dt

        except ValueError as e:
            # Try alternative formats
            alternative_formats = [
                "%m/%d/%Y %H:%M:%S",  # 24-hour format
                "%m/%d/%y %I:%M:%S %p",  # 2-digit year
                "%m/%d/%y %H:%M:%S",  # 2-digit year, 24-hour
            ]

            for fmt in alternative_formats:
                try:
                    dt = datetime.strptime(datetime_str, fmt)
                    seattle_dt = self.seattle_tz.localize(dt)
                    utc_dt = seattle_dt.astimezone(pytz.UTC).replace(tzinfo=None)
                    return utc_dt
                except ValueError:
                    continue

            raise NormalizationError(f"Unable to parse datetime: {datetime_str}") from e

    def _parse_priority(self, priority_str: str) -> int:
        """Parse priority string to integer.

        Args:
            priority_str: Priority string

        Returns:
            Priority as integer

        Raises:
            NormalizationError: When priority parsing fails
        """
        if not priority_str:
            raise NormalizationError("Empty priority string")

        try:
            # Clean the string and extract number
            cleaned = priority_str.strip()

            # Extract first number found
            match = re.search(r'\d+', cleaned)
            if match:
                return int(match.group())
            else:
                raise NormalizationError(f"No number found in priority: {priority_str}")

        except (ValueError, AttributeError) as e:
            raise NormalizationError(f"Unable to parse priority: {priority_str}") from e

    def _parse_units(self, units_str: str) -> List[str]:
        """Parse units string into list of unit identifiers.

        Args:
            units_str: Units string like "E25 L10" or "E17*"

        Returns:
            List of unit identifiers

        Raises:
            NormalizationError: When units parsing fails
        """
        if not units_str:
            logger.warning("Empty units string, returning empty list")
            return []

        try:
            # Clean the string
            cleaned = units_str.strip()

            # Split on common delimiters and clean each unit
            units = []

            # Split on spaces first
            parts = re.split(r'\s+', cleaned)

            for part in parts:
                if not part:
                    continue

                # Remove trailing asterisks and other symbols
                unit = re.sub(r'[*]+$', '', part)

                # Further split on other delimiters if needed
                sub_units = re.split(r'[,;]+', unit)

                for sub_unit in sub_units:
                    sub_unit = sub_unit.strip()
                    if sub_unit and len(sub_unit) > 0:
                        units.append(sub_unit)

            return units

        except Exception as e:
            logger.warning(f"Error parsing units '{units_str}': {e}")
            # Return the original string as a single unit if parsing fails
            return [units_str.strip()] if units_str.strip() else []