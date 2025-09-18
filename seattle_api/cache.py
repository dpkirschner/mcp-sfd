"""In-memory incident cache with thread-safe operations."""

import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import logging

from .models import Incident, IncidentStatus, IncidentSearchFilters

logger = logging.getLogger(__name__)


class IncidentCache:
    """Thread-safe in-memory cache for Seattle Fire Department incidents.

    Features:
    - Thread-safe operations using RWLock pattern
    - Automatic cleanup of expired incidents (24h retention for closed)
    - Incident status tracking with timestamps
    - Search and filtering capabilities
    """

    def __init__(self, retention_hours: int = 24):
        """Initialize the incident cache.

        Args:
            retention_hours: How long to retain closed incidents (default: 24 hours)
        """
        self._incidents: Dict[str, Incident] = {}
        self._retention_hours = retention_hours
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        logger.info(f"Initialized incident cache with {retention_hours}h retention")

    def add_incident(self, incident: Incident) -> None:
        """Add or update an incident in the cache.

        Args:
            incident: The incident to add/update
        """
        with self._lock:
            existing = self._incidents.get(incident.incident_id)

            if existing:
                # Update existing incident, preserving first_seen timestamp
                incident.first_seen = existing.first_seen
                logger.debug(f"Updated incident {incident.incident_id}")
            else:
                logger.debug(f"Added new incident {incident.incident_id}")

            self._incidents[incident.incident_id] = incident

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        """Get a specific incident by ID.

        Args:
            incident_id: The incident ID to retrieve

        Returns:
            The incident if found, None otherwise
        """
        with self._lock:
            return self._incidents.get(incident_id)

    def get_active_incidents(self) -> List[Incident]:
        """Get all currently active incidents.

        Returns:
            List of active incidents sorted by incident_datetime (newest first)
        """
        with self._lock:
            active = [
                incident for incident in self._incidents.values()
                if incident.status == IncidentStatus.ACTIVE.value
            ]
            return sorted(active, key=lambda x: x.incident_datetime, reverse=True)

    def get_all_incidents(self) -> List[Incident]:
        """Get all incidents in the cache (active and closed within retention period).

        Returns:
            List of all incidents sorted by incident_datetime (newest first)
        """
        with self._lock:
            all_incidents = list(self._incidents.values())
            return sorted(all_incidents, key=lambda x: x.incident_datetime, reverse=True)

    def search_incidents(self, filters: IncidentSearchFilters) -> List[Incident]:
        """Search incidents based on provided filters.

        Args:
            filters: Search criteria

        Returns:
            List of matching incidents sorted by incident_datetime (newest first)
        """
        with self._lock:
            results = []

            for incident in self._incidents.values():
                # Status filter
                if filters.status and incident.status != filters.status.value:
                    continue

                # Incident type filter (case-insensitive partial match)
                if filters.incident_type:
                    if filters.incident_type.lower() not in incident.incident_type.lower():
                        continue

                # Address filter (case-insensitive partial match)
                if filters.address_contains:
                    if filters.address_contains.lower() not in incident.address.lower():
                        continue

                # Priority filter
                if filters.priority and incident.priority != filters.priority:
                    continue

                # Time range filters
                if filters.since and incident.incident_datetime < filters.since:
                    continue

                if filters.until and incident.incident_datetime > filters.until:
                    continue

                results.append(incident)

            return sorted(results, key=lambda x: x.incident_datetime, reverse=True)

    def mark_incident_closed(self, incident_id: str) -> bool:
        """Mark an incident as closed with current timestamp.

        Args:
            incident_id: The incident ID to mark as closed

        Returns:
            True if incident was found and marked closed, False otherwise
        """
        with self._lock:
            incident = self._incidents.get(incident_id)
            if incident and incident.status == IncidentStatus.ACTIVE.value:
                incident.status = IncidentStatus.CLOSED.value
                incident.closed_at = datetime.utcnow()
                logger.debug(f"Marked incident {incident_id} as closed")
                return True
            return False

    def update_active_incidents(self, active_incident_ids: Set[str]) -> None:
        """Update incident statuses based on currently active incident IDs.

        This method marks incidents as closed if they're no longer in the active set.

        Args:
            active_incident_ids: Set of incident IDs that are currently active
        """
        with self._lock:
            for incident_id, incident in self._incidents.items():
                if incident.status == IncidentStatus.ACTIVE.value:
                    if incident_id not in active_incident_ids:
                        # Incident is no longer active, mark as closed
                        incident.status = IncidentStatus.CLOSED.value
                        incident.closed_at = datetime.utcnow()
                        logger.debug(f"Auto-closed incident {incident_id}")
                    else:
                        # Update last_seen timestamp for active incidents
                        incident.last_seen = datetime.utcnow()

    def cleanup_expired(self) -> int:
        """Remove incidents that have been closed longer than retention period.

        Returns:
            Number of incidents removed
        """
        with self._lock:
            cutoff_time = datetime.utcnow() - timedelta(hours=self._retention_hours)
            expired_ids = []

            for incident_id, incident in self._incidents.items():
                if (incident.status == IncidentStatus.CLOSED.value and
                    incident.closed_at and
                    incident.closed_at < cutoff_time):
                    expired_ids.append(incident_id)

            for incident_id in expired_ids:
                del self._incidents[incident_id]
                logger.debug(f"Removed expired incident {incident_id}")

            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired incidents")

            return len(expired_ids)

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            active_count = sum(1 for i in self._incidents.values()
                             if i.status == IncidentStatus.ACTIVE.value)
            closed_count = sum(1 for i in self._incidents.values()
                             if i.status == IncidentStatus.CLOSED.value)

            return {
                "total_incidents": len(self._incidents),
                "active_incidents": active_count,
                "closed_incidents": closed_count,
                "retention_hours": self._retention_hours
            }

    def clear(self) -> None:
        """Clear all incidents from cache. Mainly for testing."""
        with self._lock:
            incident_count = len(self._incidents)
            self._incidents.clear()
            logger.info(f"Cleared {incident_count} incidents from cache")