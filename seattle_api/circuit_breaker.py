"""Circuit breaker implementation for fault tolerance."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"         # Circuit is open, blocking calls
    HALF_OPEN = "half_open"  # Testing if service is recovered


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """Circuit breaker for fault tolerance and resilience.

    Implements the circuit breaker pattern to prevent cascading failures
    and provide fast failure when a service is down.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, all requests fail fast
    - HALF_OPEN: Testing if service has recovered
    """

    def __init__(self,
                 failure_threshold: int = 5,
                 recovery_timeout: float = 60.0,
                 expected_exception: type[Exception] = Exception,
                 name: str = "CircuitBreaker"):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Time to wait before attempting recovery (seconds)
            expected_exception: Exception type that triggers circuit breaker
            name: Name for logging and identification
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name

        # Circuit state
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: datetime | None = None
        self._next_attempt_time: datetime | None = None

        # Statistics
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._rejected_requests = 0

        # Lock for thread safety
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing fast)."""
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        return self._state == CircuitState.HALF_OPEN

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        """Execute function through circuit breaker.

        Args:
            func: Async function to execute

        Returns:
            Result of function execution

        Raises:
            CircuitBreakerError: When circuit is open
            Any exception raised by the function
        """
        async with self._lock:
            self._total_requests += 1

            # Check if we should allow the call
            if not await self._should_allow_request():
                self._rejected_requests += 1
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is {self._state.value}, "
                    f"rejecting request (failures: {self._failure_count}/{self.failure_threshold})"
                )

            # If half-open, only allow one request at a time
            if self._state == CircuitState.HALF_OPEN:
                logger.info(f"Circuit breaker '{self.name}' testing recovery with single request")

        try:
            # Execute the function
            result = await func()

            # Success - handle state transition
            async with self._lock:
                await self._on_success()

            return result

        except self.expected_exception as e:
            # Expected failure - handle state transition
            async with self._lock:
                await self._on_failure(e)
            raise

    async def _should_allow_request(self) -> bool:
        """Check if request should be allowed based on current state."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # Check if enough time has passed to try recovery
            if self._next_attempt_time and datetime.now(UTC) >= self._next_attempt_time:
                logger.info(f"Circuit breaker '{self.name}' transitioning to half-open for recovery test")
                self._state = CircuitState.HALF_OPEN
                return True
            return False

        if self._state == CircuitState.HALF_OPEN:
            # In half-open state, allow only one request at a time
            return True

        return False

    async def _on_success(self) -> None:
        """Handle successful request."""
        self._successful_requests += 1

        if self._state == CircuitState.HALF_OPEN:
            # Recovery successful - close circuit
            logger.info(f"Circuit breaker '{self.name}' recovery successful, closing circuit")
            self._reset_circuit()
        elif self._state == CircuitState.CLOSED:
            # Normal operation - reset failure count on success
            if self._failure_count > 0:
                logger.debug(f"Circuit breaker '{self.name}' resetting failure count after success")
                self._failure_count = 0

    async def _on_failure(self, exception: Exception) -> None:
        """Handle failed request."""
        self._failed_requests += 1
        self._failure_count += 1
        self._last_failure_time = datetime.now(UTC)

        logger.warning(
            f"Circuit breaker '{self.name}' recorded failure "
            f"({self._failure_count}/{self.failure_threshold}): {exception}"
        )

        if self._state == CircuitState.HALF_OPEN:
            # Recovery failed - open circuit again
            logger.warning(f"Circuit breaker '{self.name}' recovery failed, opening circuit")
            self._open_circuit()
        elif self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold:
            # Too many failures - open circuit
            logger.error(
                f"Circuit breaker '{self.name}' failure threshold reached "
                f"({self._failure_count}/{self.failure_threshold}), opening circuit"
            )
            self._open_circuit()

    def _open_circuit(self) -> None:
        """Open the circuit (block all requests)."""
        self._state = CircuitState.OPEN
        self._next_attempt_time = datetime.now(UTC) + timedelta(seconds=self.recovery_timeout)
        logger.info(
            f"Circuit breaker '{self.name}' opened, next recovery attempt at "
            f"{self._next_attempt_time.isoformat()}"
        )

    def _reset_circuit(self) -> None:
        """Reset circuit to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._next_attempt_time = None

    async def reset(self) -> None:
        """Manually reset the circuit breaker."""
        async with self._lock:
            logger.info(f"Circuit breaker '{self.name}' manually reset")
            self._reset_circuit()

    async def force_open(self) -> None:
        """Manually open the circuit breaker."""
        async with self._lock:
            logger.warning(f"Circuit breaker '{self.name}' manually opened")
            self._open_circuit()

    def get_statistics(self) -> dict[str, Any]:
        """Get circuit breaker statistics.

        Returns:
            Dictionary with statistics and current state
        """
        success_rate = 0.0
        if self._total_requests > 0:
            success_rate = (self._successful_requests / self._total_requests) * 100

        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "total_requests": self._total_requests,
            "successful_requests": self._successful_requests,
            "failed_requests": self._failed_requests,
            "rejected_requests": self._rejected_requests,
            "success_rate_percent": success_rate,
            "last_failure_time": self._last_failure_time.isoformat() if self._last_failure_time else None,
            "next_attempt_time": self._next_attempt_time.isoformat() if self._next_attempt_time else None,
        }


class HTTPCircuitBreaker(CircuitBreaker):
    """Circuit breaker specifically for HTTP operations."""

    def __init__(self, **kwargs):
        """Initialize HTTP circuit breaker with sensible defaults."""
        # Import here to avoid circular imports
        try:
            import httpx
            expected_exception = (httpx.HTTPError, asyncio.TimeoutError, ConnectionError)
        except ImportError:
            expected_exception = (asyncio.TimeoutError, ConnectionError)

        kwargs.setdefault('expected_exception', expected_exception)
        kwargs.setdefault('name', 'HTTPCircuitBreaker')
        kwargs.setdefault('failure_threshold', 3)  # More sensitive for HTTP
        kwargs.setdefault('recovery_timeout', 30.0)  # Shorter recovery time

        super().__init__(**kwargs)


class ParsingCircuitBreaker(CircuitBreaker):
    """Circuit breaker specifically for parsing operations."""

    def __init__(self, **kwargs):
        """Initialize parsing circuit breaker with sensible defaults."""
        from .parser import HTMLParseError

        kwargs.setdefault('expected_exception', (HTMLParseError, ValueError, TypeError))
        kwargs.setdefault('name', 'ParsingCircuitBreaker')
        kwargs.setdefault('failure_threshold', 5)  # Less sensitive for parsing
        kwargs.setdefault('recovery_timeout', 60.0)  # Longer recovery time

        super().__init__(**kwargs)