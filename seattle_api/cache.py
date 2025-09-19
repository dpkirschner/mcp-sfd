"""In-memory incident cache with thread-safe operations."""

import asyncio
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from .models import Incident, IncidentSearchFilters, IncidentStatus

logger = logging.getLogger(__name__)


class IncidentCache:
    """Thread-safe in-memory cache for Seattle Fire Department incidents.

    Features:
    - Thread-safe operations using RWLock pattern
    - Automatic cleanup of expired incidents (24h retention for closed)
    - Background cleanup task with configurable intervals
    - Memory monitoring and management
    - Incident status tracking with timestamps
    - Search and filtering capabilities
    """

    def __init__(
        self,
        retention_hours: int = 24,
        cleanup_interval_minutes: int = 15,
        max_cache_size: int = 10000,
        memory_warning_threshold: float = 0.8,
    ):
        """Initialize the incident cache.

        Args:
            retention_hours: How long to retain closed incidents (default: 24 hours)
            cleanup_interval_minutes: How often to run cleanup task (default: 15 minutes)
            max_cache_size: Maximum number of incidents to cache (default: 10000)
            memory_warning_threshold: Memory usage threshold for warnings (0.0-1.0)
        """
        self._incidents: dict[str, Incident] = {}
        self._retention_hours = retention_hours
        self._cleanup_interval_minutes = cleanup_interval_minutes
        self._max_cache_size = max_cache_size
        self._memory_warning_threshold = memory_warning_threshold
        self._lock = threading.RLock()  # Reentrant lock for nested calls

        # Background cleanup task
        self._cleanup_task: asyncio.Task | None = None
        self._cleanup_running = False
        self._stop_cleanup = asyncio.Event()

        # Statistics tracking
        self._total_cleanups = 0
        self._total_removed = 0
        self._last_cleanup = None
        self._memory_warnings = 0

        # Cleanup callbacks
        self._cleanup_callbacks: list[Callable[[int], None]] = []

        logger.info(
            f"Initialized incident cache: retention={retention_hours}h, "
            f"cleanup_interval={cleanup_interval_minutes}m, max_size={max_cache_size}"
        )

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

    def get_incident(self, incident_id: str) -> Incident | None:
        """Get a specific incident by ID.

        Args:
            incident_id: The incident ID to retrieve

        Returns:
            The incident if found, None otherwise
        """
        with self._lock:
            return self._incidents.get(incident_id)

    def get_active_incidents(self) -> list[Incident]:
        """Get all currently active incidents.

        Returns:
            List of active incidents sorted by incident_datetime (newest first)
        """
        with self._lock:
            active = [
                incident
                for incident in self._incidents.values()
                if incident.status == IncidentStatus.ACTIVE
            ]
            return sorted(active, key=lambda x: x.incident_datetime, reverse=True)

    def get_all_incidents(self) -> list[Incident]:
        """Get all incidents in the cache (active and closed within retention period).

        Returns:
            List of all incidents sorted by incident_datetime (newest first)
        """
        with self._lock:
            all_incidents = list(self._incidents.values())
            return sorted(
                all_incidents, key=lambda x: x.incident_datetime, reverse=True
            )

    def search_incidents(self, filters: IncidentSearchFilters) -> list[Incident]:
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
                if filters.status and incident.status != filters.status:
                    continue

                # Incident type filter (case-insensitive partial match)
                if filters.incident_type:
                    if (
                        filters.incident_type.lower()
                        not in incident.incident_type.lower()
                    ):
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
            if incident and incident.status == IncidentStatus.ACTIVE:
                incident.status = IncidentStatus.CLOSED
                incident.closed_at = datetime.utcnow()
                logger.debug(f"Marked incident {incident_id} as closed")
                return True
            return False

    def update_active_incidents(self, active_incident_ids: set[str]) -> None:
        """Update incident statuses based on currently active incident IDs.

        This method marks incidents as closed if they're no longer in the active set.

        Args:
            active_incident_ids: Set of incident IDs that are currently active
        """
        with self._lock:
            for incident_id, incident in self._incidents.items():
                if incident.status == IncidentStatus.ACTIVE:
                    if incident_id not in active_incident_ids:
                        # Incident is no longer active, mark as closed
                        incident.status = IncidentStatus.CLOSED
                        incident.closed_at = datetime.utcnow()
                        logger.debug(f"Auto-closed incident {incident_id}")
                    else:
                        # Update last_seen timestamp for active incidents
                        incident.last_seen = datetime.utcnow()

    async def start_background_cleanup(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_running:
            logger.warning("Background cleanup already running")
            return

        self._cleanup_running = True
        self._stop_cleanup.clear()
        self._cleanup_task = asyncio.create_task(self._background_cleanup_loop())
        logger.info(
            f"Started background cleanup task (interval: {self._cleanup_interval_minutes}m)"
        )

    async def stop_background_cleanup(self) -> None:
        """Stop the background cleanup task."""
        if not self._cleanup_running:
            return

        self._stop_cleanup.set()
        if self._cleanup_task:
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=5.0)
            except TimeoutError:
                logger.warning("Cleanup task did not stop gracefully, cancelling")
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass

        self._cleanup_running = False
        self._cleanup_task = None
        logger.info("Stopped background cleanup task")

    async def _background_cleanup_loop(self) -> None:
        """Background cleanup loop that runs periodically."""
        try:
            while not self._stop_cleanup.is_set():
                try:
                    # Run cleanup
                    removed_count = self.cleanup_expired()
                    self._total_cleanups += 1
                    self._last_cleanup = datetime.utcnow()

                    if removed_count > 0:
                        logger.info(
                            f"Background cleanup removed {removed_count} expired incidents"
                        )

                    # Check memory usage and cache size
                    self._check_memory_and_cache_limits()

                    # Notify callbacks
                    for callback in self._cleanup_callbacks:
                        try:
                            callback(removed_count)
                        except Exception as e:
                            logger.error(f"Cleanup callback error: {e}")

                except Exception as e:
                    logger.error(f"Error in background cleanup: {e}")

                # Wait for next cleanup interval or stop signal
                try:
                    await asyncio.wait_for(
                        self._stop_cleanup.wait(),
                        timeout=self._cleanup_interval_minutes * 60,
                    )
                    break  # Stop signal received
                except TimeoutError:
                    continue  # Continue cleanup loop

        except asyncio.CancelledError:
            logger.info("Background cleanup task was cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in background cleanup: {e}")
        finally:
            self._cleanup_running = False
            self._cleanup_task = None

    def _check_memory_and_cache_limits(self) -> None:
        """Check memory usage and cache size limits."""
        with self._lock:
            cache_size = len(self._incidents)

            # Check cache size limit
            if cache_size > self._max_cache_size:
                overage = cache_size - self._max_cache_size
                logger.warning(
                    f"Cache size ({cache_size}) exceeds limit ({self._max_cache_size})"
                )

                # Force cleanup of oldest closed incidents
                forced_removals = self._force_cleanup_oldest(overage)
                logger.info(
                    f"Force-removed {forced_removals} oldest incidents to stay within limits"
                )

            # Check memory usage
            try:
                import psutil

                process = psutil.Process()
                memory_percent = process.memory_percent()

                if memory_percent > self._memory_warning_threshold * 100:
                    self._memory_warnings += 1
                    logger.warning(
                        f"High memory usage: {memory_percent:.1f}% "
                        f"(cache size: {cache_size} incidents)"
                    )

                    # Trigger aggressive cleanup if memory is critical
                    if memory_percent > 90:
                        logger.warning(
                            "Critical memory usage, triggering aggressive cleanup"
                        )
                        self._force_cleanup_oldest(
                            cache_size // 4
                        )  # Remove 25% of cache

            except ImportError:
                # psutil not available, skip memory monitoring
                pass
            except Exception as e:
                logger.error(f"Error checking memory usage: {e}")

    def _force_cleanup_oldest(self, target_count: int) -> int:
        """Force removal of oldest closed incidents to free space.

        Args:
            target_count: Number of incidents to try to remove

        Returns:
            Number of incidents actually removed
        """
        if target_count <= 0:
            return 0

        # Get closed incidents sorted by closed_at (oldest first)
        closed_incidents = [
            (incident_id, incident)
            for incident_id, incident in self._incidents.items()
            if incident.status == IncidentStatus.CLOSED and incident.closed_at
        ]

        if not closed_incidents:
            return 0

        # Sort by closed_at timestamp
        closed_incidents.sort(key=lambda x: x[1].closed_at)

        # Remove oldest incidents up to target count
        removed_count = 0
        for incident_id, incident in closed_incidents[:target_count]:
            del self._incidents[incident_id]
            removed_count += 1
            logger.debug(
                f"Force-removed incident {incident_id} (closed: {incident.closed_at})"
            )

        return removed_count

    def add_cleanup_callback(self, callback: Callable[[int], None]) -> None:
        """Add a callback function to be called after each cleanup.

        Args:
            callback: Function that takes removed_count as parameter
        """
        self._cleanup_callbacks.append(callback)

    def remove_cleanup_callback(self, callback: Callable[[int], None]) -> None:
        """Remove a cleanup callback.

        Args:
            callback: The callback function to remove
        """
        if callback in self._cleanup_callbacks:
            self._cleanup_callbacks.remove(callback)

    def cleanup_expired(self) -> int:
        """Remove incidents that have been closed longer than retention period.

        Implements the 24-hour retention policy for closed incidents.

        Returns:
            Number of incidents removed
        """
        with self._lock:
            cutoff_time = datetime.utcnow() - timedelta(hours=self._retention_hours)
            expired_ids: list[str] = []
            before_count = len(self._incidents)

            for incident_id, incident in self._incidents.items():
                if (
                    incident.status == IncidentStatus.CLOSED
                    and incident.closed_at
                    and incident.closed_at < cutoff_time
                ):
                    expired_ids.append(incident_id)

            for incident_id in expired_ids:
                del self._incidents[incident_id]
                logger.debug(f"Removed expired incident {incident_id}")

            removed_count = len(expired_ids)
            self._total_removed += removed_count

            if expired_ids:
                logger.info(
                    f"Cleaned up {removed_count} expired incidents "
                    f"(cache: {before_count} -> {len(self._incidents)})"
                )

            return removed_count

    def get_cache_stats(self) -> dict:
        """Get comprehensive cache statistics and metrics.

        Returns:
            Dictionary with cache statistics and cleanup metrics
        """
        with self._lock:
            active_count = sum(
                1
                for i in self._incidents.values()
                if i.status == IncidentStatus.ACTIVE
            )
            closed_count = sum(
                1
                for i in self._incidents.values()
                if i.status == IncidentStatus.CLOSED
            )

            # Calculate memory usage estimate
            memory_estimate_mb = 0
            try:
                import sys

                memory_estimate_mb = sum(
                    sys.getsizeof(incident) for incident in self._incidents.values()
                ) / (1024 * 1024)
            except Exception:
                pass

            # Get process memory if psutil available
            process_memory_mb = None
            process_memory_percent = None
            try:
                import psutil

                process = psutil.Process()
                process_memory_mb = process.memory_info().rss / (1024 * 1024)
                process_memory_percent = process.memory_percent()
            except ImportError:
                pass
            except Exception:
                pass

            return {
                "total_incidents": len(self._incidents),
                "active_incidents": active_count,
                "closed_incidents": closed_count,
                "retention_hours": self._retention_hours,
                "max_cache_size": self._max_cache_size,
                "cleanup_interval_minutes": self._cleanup_interval_minutes,
                "memory_warning_threshold": self._memory_warning_threshold,
                "cleanup_running": self._cleanup_running,
                "total_cleanups": self._total_cleanups,
                "total_removed": self._total_removed,
                "last_cleanup": (
                    self._last_cleanup.isoformat() if self._last_cleanup else None
                ),
                "memory_warnings": self._memory_warnings,
                "estimated_memory_mb": round(memory_estimate_mb, 2),
                "process_memory_mb": (
                    round(process_memory_mb, 2) if process_memory_mb else None
                ),
                "process_memory_percent": (
                    round(process_memory_percent, 1) if process_memory_percent else None
                ),
                "cache_utilization": round(
                    len(self._incidents) / self._max_cache_size * 100, 1
                ),
            }

    def clear(self) -> None:
        """Clear all incidents from cache. Mainly for testing."""
        with self._lock:
            incident_count = len(self._incidents)
            self._incidents.clear()
            # Reset statistics
            self._total_cleanups = 0
            self._total_removed = 0
            self._last_cleanup = None
            self._memory_warnings = 0
            logger.info(f"Cleared {incident_count} incidents from cache")

    async def shutdown(self) -> None:
        """Gracefully shutdown the cache and cleanup tasks."""
        logger.info("Shutting down incident cache...")
        await self.stop_background_cleanup()
        with self._lock:
            self._cleanup_callbacks.clear()
        logger.info("Incident cache shutdown complete")

    def __del__(self):
        """Destructor to ensure cleanup task is stopped."""
        if hasattr(self, "_cleanup_running") and self._cleanup_running:
            # Note: We can't await in __del__, so we just log a warning
            logger.warning(
                "IncidentCache destroyed while cleanup task still running. "
                "Call shutdown() explicitly for clean shutdown."
            )
