"""Tests for the circuit breaker implementation."""

import asyncio

import pytest

from seattle_api.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    HTTPCircuitBreaker,
    ParsingCircuitBreaker,
)


class TestException(Exception):
    """Test exception for circuit breaker testing."""

    pass


class TestCircuitBreaker:
    """Test cases for CircuitBreaker class."""

    @pytest.mark.asyncio
    async def test_circuit_closed_allows_requests(self):
        """Test that closed circuit allows requests through."""
        cb = CircuitBreaker(failure_threshold=2, expected_exception=TestException)

        async def successful_function():
            return "success"

        result = await cb.call(successful_function)
        assert result == "success"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self):
        """Test that circuit opens after reaching failure threshold."""
        cb = CircuitBreaker(failure_threshold=2, expected_exception=TestException)

        async def failing_function():
            raise TestException("Test failure")

        # First failure
        with pytest.raises(TestException):
            await cb.call(failing_function)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 1

        # Second failure - should open circuit
        with pytest.raises(TestException):
            await cb.call(failing_function)
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 2

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_requests(self):
        """Test that open circuit rejects requests."""
        cb = CircuitBreaker(failure_threshold=1, expected_exception=TestException)

        async def failing_function():
            raise TestException("Test failure")

        # Cause circuit to open
        with pytest.raises(TestException):
            await cb.call(failing_function)
        assert cb.state == CircuitState.OPEN

        # Next request should be rejected
        with pytest.raises(CircuitBreakerError):
            await cb.call(failing_function)

    @pytest.mark.asyncio
    async def test_circuit_recovery(self):
        """Test circuit breaker recovery after timeout."""
        cb = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.1,  # 100ms
            expected_exception=TestException,
        )

        async def initially_failing_then_successful():
            if cb.state == CircuitState.HALF_OPEN:
                return "recovered"
            raise TestException("Still failing")

        # Cause circuit to open
        with pytest.raises(TestException):
            await cb.call(initially_failing_then_successful)
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Should transition to half-open and then closed on success
        result = await cb.call(initially_failing_then_successful)
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_half_open_failed_recovery(self):
        """Test that failed recovery reopens the circuit."""
        cb = CircuitBreaker(
            failure_threshold=1, recovery_timeout=0.1, expected_exception=TestException
        )

        async def always_failing():
            raise TestException("Always fails")

        # Open circuit
        with pytest.raises(TestException):
            await cb.call(always_failing)
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Recovery attempt should fail and reopen circuit
        with pytest.raises(TestException):
            await cb.call(always_failing)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_manual_reset(self):
        """Test manual circuit reset functionality."""
        cb = CircuitBreaker(failure_threshold=1, expected_exception=TestException)

        async def failing_function():
            raise TestException("Test failure")

        # Open circuit
        with pytest.raises(TestException):
            await cb.call(failing_function)
        assert cb.state == CircuitState.OPEN

        # Manual reset
        await cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_manual_force_open(self):
        """Test manual circuit force open functionality."""
        cb = CircuitBreaker(failure_threshold=5, expected_exception=TestException)

        async def successful_function():
            return "success"

        # Circuit should be closed initially
        assert cb.state == CircuitState.CLOSED

        # Force open
        await cb.force_open()
        assert cb.state == CircuitState.OPEN

        # Requests should be rejected
        with pytest.raises(CircuitBreakerError):
            await cb.call(successful_function)

    def test_statistics(self):
        """Test circuit breaker statistics collection."""
        cb = CircuitBreaker(failure_threshold=2, expected_exception=TestException)

        stats = cb.get_statistics()

        assert stats["name"] == "CircuitBreaker"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["failure_threshold"] == 2
        assert stats["total_requests"] == 0
        assert stats["successful_requests"] == 0
        assert stats["failed_requests"] == 0
        assert stats["rejected_requests"] == 0
        assert stats["success_rate_percent"] == 0.0

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        """Test that success resets failure count in closed state."""
        cb = CircuitBreaker(failure_threshold=3, expected_exception=TestException)

        async def sometimes_failing():
            if cb.failure_count == 0:
                raise TestException("First failure")
            return "success"

        # First call fails
        with pytest.raises(TestException):
            await cb.call(sometimes_failing)
        assert cb.failure_count == 1

        # Second call succeeds - should reset failure count
        result = await cb.call(sometimes_failing)
        assert result == "success"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_unexpected_exception_not_handled(self):
        """Test that unexpected exceptions pass through without affecting circuit."""
        cb = CircuitBreaker(failure_threshold=1, expected_exception=TestException)

        async def different_failure():
            raise ValueError("Different exception type")

        # Should pass through without opening circuit
        with pytest.raises(ValueError):
            await cb.call(different_failure)

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestHTTPCircuitBreaker:
    """Test cases for HTTPCircuitBreaker."""

    def test_http_circuit_breaker_initialization(self):
        """Test HTTP circuit breaker has appropriate defaults."""
        cb = HTTPCircuitBreaker()

        assert cb.name == "HTTPCircuitBreaker"
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30.0

    @pytest.mark.asyncio
    async def test_http_circuit_breaker_with_httpx_error(self):
        """Test HTTP circuit breaker handles httpx errors."""
        import httpx

        cb = HTTPCircuitBreaker(failure_threshold=1)

        async def http_timeout():
            raise httpx.TimeoutException("Request timeout")

        # Should trigger circuit breaker
        with pytest.raises(httpx.TimeoutException):
            await cb.call(http_timeout)

        assert cb.state == CircuitState.OPEN


class TestParsingCircuitBreaker:
    """Test cases for ParsingCircuitBreaker."""

    def test_parsing_circuit_breaker_initialization(self):
        """Test parsing circuit breaker has appropriate defaults."""
        cb = ParsingCircuitBreaker()

        assert cb.name == "ParsingCircuitBreaker"
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60.0

    @pytest.mark.asyncio
    async def test_parsing_circuit_breaker_with_parse_error(self):
        """Test parsing circuit breaker handles parse errors."""
        from seattle_api.parser import HTMLParseError

        cb = ParsingCircuitBreaker(failure_threshold=1)

        async def parsing_failure():
            raise HTMLParseError("Invalid HTML structure")

        # Should trigger circuit breaker
        with pytest.raises(HTMLParseError):
            await cb.call(parsing_failure)

        assert cb.state == CircuitState.OPEN


if __name__ == "__main__":
    pytest.main([__file__])
