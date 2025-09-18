"""Incident poller for periodic data collection from Seattle Fire Department."""

import asyncio
import logging
import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .cache import IncidentCache
from .circuit_breaker import CircuitBreakerError, HTTPCircuitBreaker, ParsingCircuitBreaker
from .config import FastAPIConfig
from .http_client import SeattleHTTPClient
from .models import Incident, IncidentStatus
from .normalizer import IncidentNormalizer
from .parser import IncidentHTMLParser

logger = logging.getLogger(__name__)


class PollingError(Exception):
    """Exception raised during polling operations."""
    pass


class IncidentPoller:
    """Async background task for periodic incident data polling.

    Features:
    - Configurable polling intervals
    - Graceful startup and shutdown handling
    - Integration with scraper and cache components
    - Error handling with exponential backoff
    - Signal handling for clean shutdown
    - Health monitoring and metrics
    """

    def __init__(self,
                 config: FastAPIConfig,
                 http_client: SeattleHTTPClient,
                 cache: IncidentCache):
        """Initialize the incident poller.

        Args:
            config: Configuration containing polling settings
            http_client: HTTP client for fetching incident data
            cache: Cache for storing processed incidents
        """
        self.config = config
        self.http_client = http_client
        self.cache = cache
        self.parser = IncidentHTMLParser()
        self.normalizer = IncidentNormalizer()

        # Circuit breakers for resilience
        self.http_circuit_breaker = HTTPCircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30.0,
            name="HTTPCircuitBreaker"
        )
        self.parsing_circuit_breaker = ParsingCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            name="ParsingCircuitBreaker"
        )

        # Polling state
        self._polling_task: asyncio.Task | None = None
        self._is_running = False
        self._shutdown_event = asyncio.Event()
        self._startup_complete = asyncio.Event()

        # Enhanced error handling
        self._consecutive_failures = 0
        self._max_failures = 10  # Increased since we have circuit breakers
        self._base_retry_delay = 1.0  # seconds
        self._max_retry_delay = 300.0  # 5 minutes
        self._degraded_mode = False  # Flag for graceful degradation

        # Health metrics
        self._last_successful_poll: datetime | None = None
        self._total_polls = 0
        self._successful_polls = 0
        self._failed_polls = 0

        # Shutdown callbacks
        self._shutdown_callbacks: set[Callable[[], Any]] = set()

        # Signal handling setup
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            asyncio.create_task(self.shutdown())

        # Only setup signal handlers if we're in the main thread
        try:
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, signal_handler)
                signal.signal(signal.SIGTERM, signal_handler)
        except ValueError:
            # Not in main thread, skip signal handling
            logger.debug("Not in main thread, skipping signal handler setup")

    async def start_polling(self) -> None:
        """Start the background polling task.

        Raises:
            PollingError: If polling is already running or fails to start
        """
        if self._is_running:
            raise PollingError("Polling is already running")

        logger.info(f"Starting incident poller with {self.config.polling_interval_minutes}min interval")

        try:
            # Reset shutdown event
            self._shutdown_event.clear()
            self._startup_complete.clear()

            # Start the polling task
            self._polling_task = asyncio.create_task(self._polling_loop())
            self._is_running = True

            # Wait for startup to complete or fail
            try:
                await asyncio.wait_for(self._startup_complete.wait(), timeout=30.0)
                logger.info("Incident poller started successfully")
            except TimeoutError:
                logger.error("Poller startup timed out")
                await self.shutdown()
                raise PollingError("Poller startup timed out") from None

        except Exception as e:
            logger.error(f"Failed to start polling: {e}")
            self._is_running = False
            raise PollingError(f"Failed to start polling: {e}") from e

    async def shutdown(self) -> None:
        """Gracefully shutdown the polling task."""
        if not self._is_running:
            logger.debug("Poller is not running, nothing to shutdown")
            return

        logger.info("Shutting down incident poller...")
        self._is_running = False
        self._shutdown_event.set()

        # Cancel the polling task
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            try:
                await asyncio.wait_for(self._polling_task, timeout=10.0)
            except (TimeoutError, asyncio.CancelledError):
                logger.debug("Polling task cancelled or timed out during shutdown")

        # Run shutdown callbacks
        for callback in self._shutdown_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Error in shutdown callback: {e}")

        logger.info("Incident poller shutdown complete")

    def add_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        """Add a callback to be called during shutdown.

        Args:
            callback: Function to call during shutdown (can be async)
        """
        self._shutdown_callbacks.add(callback)

    def remove_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        """Remove a shutdown callback.

        Args:
            callback: Function to remove from shutdown callbacks
        """
        self._shutdown_callbacks.discard(callback)

    async def poll_once(self) -> bool:
        """Perform a single polling operation with circuit breaker protection.

        Returns:
            bool: True if polling was successful, False otherwise
        """
        start_time = datetime.now(UTC)
        self._total_polls += 1
        successful_operations = 0
        total_operations = 2  # HTTP fetch + parsing

        try:
            logger.debug("Starting incident polling cycle")

            # Try to fetch HTML content through HTTP circuit breaker
            html_content = None
            try:
                html_content = await self.http_circuit_breaker.call(
                    lambda: self.http_client.fetch_incidents()
                )
                successful_operations += 1
                logger.debug("HTTP fetch completed successfully")
            except CircuitBreakerError as e:
                logger.warning(f"HTTP circuit breaker blocked request: {e}")
                return await self._handle_degraded_operation("http_circuit_open")
            except Exception as e:
                logger.error(f"HTTP fetch failed: {e}")
                self._failed_polls += 1
                self._consecutive_failures += 1
                return await self._handle_degraded_operation("http_error", error=e)

            # Try to parse incidents through parsing circuit breaker
            incidents = []
            try:
                async def parse_wrapper():
                    return self.parser.parse_incidents(html_content)

                raw_incidents = await self.parsing_circuit_breaker.call(parse_wrapper)
                successful_operations += 1
                logger.debug(f"Parsed {len(raw_incidents)} raw incidents from HTML")

                # Normalize incidents (with individual error handling)
                normalization_errors = 0
                for raw_incident in raw_incidents:
                    try:
                        incident = self.normalizer.normalize_incident(raw_incident)
                        incidents.append(incident)
                    except Exception as e:
                        normalization_errors += 1
                        logger.warning(f"Failed to normalize incident {raw_incident.incident_id}: {e}")
                        continue

                if normalization_errors > 0:
                    logger.warning(f"Failed to normalize {normalization_errors} out of {len(raw_incidents)} incidents")

                logger.info(f"Successfully normalized {len(incidents)} incidents")

            except CircuitBreakerError as e:
                logger.warning(f"Parsing circuit breaker blocked request: {e}")
                return await self._handle_degraded_operation("parsing_circuit_open")
            except Exception as e:
                logger.error(f"Parsing failed: {e}")
                return await self._handle_degraded_operation("parsing_error", error=e)

            # Update cache with new incidents
            try:
                await self._update_cache_with_incidents(incidents)
                logger.debug("Cache updated successfully")
            except Exception as e:
                logger.error(f"Failed to update cache: {e}")
                # Cache update failure is not fatal, continue

            # Update success metrics
            await self._record_polling_success(start_time, successful_operations, total_operations)

            return True

        except Exception as e:
            # Unexpected error
            logger.error(f"Unexpected error in polling cycle: {e}", exc_info=True)
            self._failed_polls += 1
            self._consecutive_failures += 1

            # Check if we've exceeded max failures
            if self._consecutive_failures >= self._max_failures:
                logger.critical(f"Max consecutive failures ({self._max_failures}) reached, stopping poller")
                await self.shutdown()

            return False

    async def _handle_degraded_operation(self, operation_type: str, error: Exception | None = None) -> bool:
        """Handle degraded operation by serving from cache.

        Args:
            operation_type: Type of operation that failed
            error: Optional error that caused the degradation

        Returns:
            bool: True if degraded operation succeeded, False otherwise
        """
        was_degraded = self._degraded_mode
        self._degraded_mode = True

        if not was_degraded:
            logger.warning(f"Entering degraded mode due to {operation_type}")

        # Log the specific error with appropriate detail level
        if error:
            if operation_type.startswith("http"):
                logger.error(f"HTTP operation failed, serving from cache: {error}")
            elif operation_type.startswith("parsing"):
                logger.error(f"Parsing operation failed, serving from cache: {error}")
            else:
                logger.error(f"Operation {operation_type} failed, serving from cache: {error}")
        else:
            logger.info(f"Circuit breaker blocked {operation_type}, serving from cache")

        try:
            # Get current active incidents from cache
            cached_incidents = await asyncio.get_event_loop().run_in_executor(
                None, self.cache.get_active_incidents
            )

            if cached_incidents:
                logger.info(f"Serving {len(cached_incidents)} incidents from cache (degraded mode)")
                # Update last seen times for cached incidents to keep them fresh
                for incident in cached_incidents:
                    incident.last_seen = datetime.now(UTC)
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.cache.add_incident, incident
                    )

                # Partial success in degraded mode
                self._failed_polls += 1  # Still count as a failed poll
                logger.debug("Degraded operation completed with cached data")
                return True
            else:
                logger.warning("No cached incidents available for degraded mode")
                self._failed_polls += 1
                return False

        except Exception as e:
            logger.error(f"Failed to serve from cache in degraded mode: {e}")
            self._failed_polls += 1
            return False

    async def _record_polling_success(self, start_time: datetime, successful_ops: int, total_ops: int) -> None:
        """Record successful polling operation and update metrics.

        Args:
            start_time: When the polling cycle started
            successful_ops: Number of successful operations
            total_ops: Total number of operations attempted
        """
        # Exit degraded mode on successful poll
        if self._degraded_mode:
            self._degraded_mode = False
            logger.info("Exiting degraded mode after successful poll")

        # Update success metrics
        self._last_successful_poll = datetime.now(UTC)
        self._successful_polls += 1
        self._consecutive_failures = 0

        # Calculate and log performance metrics
        duration = (datetime.now(UTC) - start_time).total_seconds()
        success_rate = (successful_ops / total_ops) * 100

        if success_rate == 100:
            logger.debug(f"Polling cycle completed successfully in {duration:.2f}s")
        else:
            logger.info(f"Polling cycle completed with {success_rate:.1f}% success rate in {duration:.2f}s")

    async def _update_cache_with_incidents(self, incidents: list[Incident]) -> None:
        """Update cache with new incidents and handle status changes.

        Args:
            incidents: List of current incidents from the feed
        """
        current_incident_ids = {incident.incident_id for incident in incidents}

        # Get all active incidents from cache
        active_incidents = await asyncio.get_event_loop().run_in_executor(
            None, self.cache.get_active_incidents
        )
        active_incident_ids = {incident.incident_id for incident in active_incidents}

        # Find incidents that are no longer in the feed (should be marked closed)
        closed_incident_ids = active_incident_ids - current_incident_ids

        # Add/update current incidents
        for incident in incidents:
            await asyncio.get_event_loop().run_in_executor(
                None, self.cache.add_incident, incident
            )

        # Mark missing incidents as closed
        for incident_id in closed_incident_ids:
            try:
                existing_incident = await asyncio.get_event_loop().run_in_executor(
                    None, self.cache.get_incident, incident_id
                )
                if existing_incident and existing_incident.status == IncidentStatus.ACTIVE:
                    # Create a closed version of the incident
                    closed_incident = existing_incident.model_copy(update={
                        'status': IncidentStatus.CLOSED,
                        'closed_at': datetime.now(UTC),
                        'last_seen': datetime.now(UTC)
                    })
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.cache.add_incident, closed_incident
                    )
                    logger.debug(f"Marked incident {incident_id} as closed")
            except Exception as e:
                logger.warning(f"Failed to close incident {incident_id}: {e}")

    async def _polling_loop(self) -> None:
        """Main polling loop with error handling and backoff."""
        logger.debug("Starting polling loop")

        try:
            # Perform initial poll to verify everything works
            success = await self.poll_once()
            if success:
                self._startup_complete.set()
            else:
                logger.error("Initial poll failed, startup incomplete")
                return

            # Main polling loop
            while self._is_running and not self._shutdown_event.is_set():
                try:
                    # Calculate next poll time
                    interval_seconds = self.config.polling_interval_minutes * 60

                    # Wait for either shutdown or next poll time
                    try:
                        await asyncio.wait_for(
                            self._shutdown_event.wait(),
                            timeout=interval_seconds
                        )
                        # Shutdown was requested
                        break
                    except TimeoutError:
                        # Time for next poll
                        pass

                    # Perform polling if still running
                    if self._is_running:
                        success = await self.poll_once()

                        # If polling failed, apply exponential backoff
                        if not success and self._consecutive_failures > 0:
                            delay = min(
                                self._base_retry_delay * (2 ** (self._consecutive_failures - 1)),
                                self._max_retry_delay
                            )
                            logger.warning(f"Polling failed, waiting {delay:.1f}s before retry")

                            try:
                                await asyncio.wait_for(
                                    self._shutdown_event.wait(),
                                    timeout=delay
                                )
                                break  # Shutdown was requested during backoff
                            except TimeoutError:
                                continue  # Continue with next poll attempt

                except asyncio.CancelledError:
                    logger.debug("Polling loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error in polling loop: {e}")
                    self._consecutive_failures += 1

                    # Apply backoff for unexpected errors too
                    delay = min(
                        self._base_retry_delay * (2 ** (self._consecutive_failures - 1)),
                        self._max_retry_delay
                    )
                    try:
                        await asyncio.wait_for(
                            self._shutdown_event.wait(),
                            timeout=delay
                        )
                        break
                    except TimeoutError:
                        continue

        except Exception as e:
            logger.critical(f"Fatal error in polling loop: {e}")
        finally:
            self._is_running = False
            logger.debug("Polling loop ended")

    def configure_interval(self, minutes: int) -> None:
        """Configure polling interval.

        Args:
            minutes: New polling interval in minutes

        Raises:
            ValueError: If minutes is not positive
        """
        if minutes <= 0:
            raise ValueError("Polling interval must be positive")

        old_interval = self.config.polling_interval_minutes
        self.config.polling_interval_minutes = minutes
        logger.info(f"Polling interval changed from {old_interval} to {minutes} minutes")

    def get_health_status(self) -> dict:
        """Get current health and status information.

        Returns:
            dict: Health status information
        """
        now = datetime.now(UTC)
        time_since_last_poll = None

        if self._last_successful_poll:
            time_since_last_poll = (now - self._last_successful_poll).total_seconds()

        # Determine health status
        status = "healthy"
        if not self._is_running:
            status = "stopped"
        elif self.http_circuit_breaker.is_open or self.parsing_circuit_breaker.is_open:
            status = "circuit_open"
        elif self._degraded_mode:
            status = "degraded"
        elif self._consecutive_failures > 0:
            status = "degraded"
        elif self._consecutive_failures >= self._max_failures:
            status = "unhealthy"
        elif time_since_last_poll and time_since_last_poll > (self.config.polling_interval_minutes * 60 * 2):
            status = "stale"

        return {
            "status": status,
            "is_running": self._is_running,
            "degraded_mode": self._degraded_mode,
            "polling_interval_minutes": self.config.polling_interval_minutes,
            "total_polls": self._total_polls,
            "successful_polls": self._successful_polls,
            "failed_polls": self._failed_polls,
            "consecutive_failures": self._consecutive_failures,
            "last_successful_poll": self._last_successful_poll.isoformat() if self._last_successful_poll else None,
            "time_since_last_poll_seconds": time_since_last_poll,
            "circuit_breakers": {
                "http": self.http_circuit_breaker.get_statistics(),
                "parsing": self.parsing_circuit_breaker.get_statistics()
            }
        }

    @property
    def is_running(self) -> bool:
        """Check if poller is currently running."""
        return self._is_running

    @property
    def startup_complete(self) -> bool:
        """Check if startup has completed successfully."""
        return self._startup_complete.is_set()

