"""Tests for incident cache cleanup and retention functionality."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from seattle_api.cache import IncidentCache
from seattle_api.models import Incident, IncidentStatus


@pytest.fixture
def cache_with_short_retention():
    """Create a cache with short retention for faster testing."""
    return IncidentCache(
        retention_hours=1,  # 1 hour for testing
        cleanup_interval_minutes=1,  # 1 minute for testing
        max_cache_size=100,
        memory_warning_threshold=0.5,
    )


@pytest.fixture
def expired_incident():
    """Create an incident that should be expired."""
    old_time = datetime.utcnow() - timedelta(hours=2)
    return Incident(
        incident_id="F230000001",
        incident_datetime=old_time,
        priority=1,
        units=["E1"],
        address="Old Address",
        incident_type="Old Incident",
        status=IncidentStatus.CLOSED,
        first_seen=old_time,
        last_seen=old_time - timedelta(minutes=30),
        closed_at=old_time - timedelta(minutes=30),
    )


@pytest.fixture
def recent_closed_incident():
    """Create a recently closed incident that should not be expired."""
    recent_time = datetime.utcnow() - timedelta(minutes=30)
    return Incident(
        incident_id="F230000002",
        incident_datetime=recent_time,
        priority=1,
        units=["E2"],
        address="Recent Address",
        incident_type="Recent Incident",
        status=IncidentStatus.CLOSED,
        first_seen=recent_time,
        last_seen=recent_time - timedelta(minutes=15),
        closed_at=recent_time - timedelta(minutes=15),
    )


@pytest.fixture
def active_incident():
    """Create an active incident."""
    now = datetime.utcnow()
    return Incident(
        incident_id="F230000003",
        incident_datetime=now,
        priority=1,
        units=["E3"],
        address="Active Address",
        incident_type="Active Incident",
        status=IncidentStatus.ACTIVE,
        first_seen=now,
        last_seen=now,
    )


class TestCleanupRetentionPolicy:
    """Test the 24-hour retention policy for closed incidents."""

    def test_retention_policy_expired_incidents(
        self, cache_with_short_retention, expired_incident, recent_closed_incident
    ):
        """Test that expired incidents are removed but recent ones are kept."""
        cache = cache_with_short_retention

        # Add incidents
        cache.add_incident(expired_incident)
        cache.add_incident(recent_closed_incident)

        assert len(cache.get_all_incidents()) == 2

        # Run cleanup
        removed_count = cache.cleanup_expired()

        # Only the expired incident should be removed
        assert removed_count == 1
        remaining = cache.get_all_incidents()
        assert len(remaining) == 1
        assert remaining[0].incident_id == "F230000002"

    def test_retention_policy_active_incidents_preserved(
        self, cache_with_short_retention, expired_incident, active_incident
    ):
        """Test that active incidents are never removed by retention policy."""
        cache = cache_with_short_retention

        # Create an old active incident (should not be removed)
        old_time = datetime.utcnow() - timedelta(hours=48)
        old_active = Incident(
            incident_id="F230000004",
            incident_datetime=old_time,
            priority=1,
            units=["E4"],
            address="Old Active",
            incident_type="Old Active Incident",
            status=IncidentStatus.ACTIVE,
            first_seen=old_time,
            last_seen=datetime.utcnow(),  # Still being seen
        )

        cache.add_incident(expired_incident)
        cache.add_incident(old_active)
        cache.add_incident(active_incident)

        removed_count = cache.cleanup_expired()

        # Only the expired closed incident should be removed
        assert removed_count == 1
        remaining = cache.get_all_incidents()
        assert len(remaining) == 2

        # Both active incidents should remain
        remaining_ids = {inc.incident_id for inc in remaining}
        assert "F230000004" in remaining_ids  # Old active
        assert "F230000003" in remaining_ids  # Recent active

    def test_retention_policy_no_closed_at_timestamp(self, cache_with_short_retention):
        """Test that incidents without closed_at timestamp are not removed."""
        now = datetime.utcnow()
        incident_no_closed_at = Incident(
            incident_id="F230000005",
            incident_datetime=now - timedelta(hours=48),
            priority=1,
            units=["E5"],
            address="No Closed At",
            incident_type="No Timestamp",
            status=IncidentStatus.CLOSED,
            first_seen=now - timedelta(hours=48),
            last_seen=now - timedelta(hours=47),
            closed_at=None,  # No closed timestamp
        )

        cache_with_short_retention.add_incident(incident_no_closed_at)
        removed_count = cache_with_short_retention.cleanup_expired()

        # Should not be removed since closed_at is None
        assert removed_count == 0
        assert len(cache_with_short_retention.get_all_incidents()) == 1

    def test_cleanup_statistics_tracking(
        self, cache_with_short_retention, expired_incident
    ):
        """Test that cleanup statistics are properly tracked."""
        cache = cache_with_short_retention
        cache.add_incident(expired_incident)

        initial_stats = cache.get_cache_stats()
        assert initial_stats["total_cleanups"] == 0
        assert initial_stats["total_removed"] == 0
        assert initial_stats["last_cleanup"] is None

        # Run cleanup
        removed_count = cache.cleanup_expired()

        stats = cache.get_cache_stats()
        assert stats["total_removed"] == removed_count
        assert (
            stats["last_cleanup"] is None
        )  # Manual cleanup doesn't update last_cleanup


class TestBackgroundCleanupTask:
    """Test the background cleanup task functionality."""

    @pytest.mark.asyncio
    async def test_start_stop_background_cleanup(self, cache_with_short_retention):
        """Test starting and stopping the background cleanup task."""
        cache = cache_with_short_retention

        # Initially not running
        assert not cache._cleanup_running

        # Start cleanup
        await cache.start_background_cleanup()
        assert cache._cleanup_running
        assert cache._cleanup_task is not None

        # Try to start again (should warn but not fail)
        await cache.start_background_cleanup()
        assert cache._cleanup_running

        # Stop cleanup
        await cache.stop_background_cleanup()
        assert not cache._cleanup_running
        assert cache._cleanup_task is None

    @pytest.mark.asyncio
    async def test_background_cleanup_removes_expired(
        self, cache_with_short_retention, expired_incident, recent_closed_incident
    ):
        """Test that background cleanup removes expired incidents."""
        cache = cache_with_short_retention

        # Add incidents
        cache.add_incident(expired_incident)
        cache.add_incident(recent_closed_incident)

        # Start background cleanup with very short interval
        cache._cleanup_interval_minutes = 0.01  # 0.6 seconds
        await cache.start_background_cleanup()

        # Wait for at least one cleanup cycle
        await asyncio.sleep(1.0)

        # Stop cleanup
        await cache.stop_background_cleanup()

        # Check that expired incident was removed
        remaining = cache.get_all_incidents()
        assert len(remaining) == 1
        assert remaining[0].incident_id == "F230000002"

        # Check statistics
        stats = cache.get_cache_stats()
        assert stats["total_cleanups"] > 0
        assert stats["total_removed"] >= 1
        assert stats["last_cleanup"] is not None

    @pytest.mark.asyncio
    async def test_cleanup_callbacks(
        self, cache_with_short_retention, expired_incident
    ):
        """Test that cleanup callbacks are called correctly."""
        cache = cache_with_short_retention
        cache.add_incident(expired_incident)

        # Create mock callback
        callback_mock = Mock()
        cache.add_cleanup_callback(callback_mock)

        # Start background cleanup
        cache._cleanup_interval_minutes = 0.01
        await cache.start_background_cleanup()

        # Wait for cleanup
        await asyncio.sleep(1.0)
        await cache.stop_background_cleanup()

        # Verify callback was called
        callback_mock.assert_called()

        # Remove callback and verify it works
        cache.remove_cleanup_callback(callback_mock)
        assert callback_mock not in cache._cleanup_callbacks

    @pytest.mark.asyncio
    async def test_cleanup_callback_exception_handling(
        self, cache_with_short_retention
    ):
        """Test that exceptions in callbacks don't crash the cleanup task."""
        cache = cache_with_short_retention

        # Create a callback that raises an exception
        def failing_callback(removed_count):
            raise ValueError("Test exception")

        cache.add_cleanup_callback(failing_callback)

        # Start cleanup
        cache._cleanup_interval_minutes = 0.01
        await cache.start_background_cleanup()

        # Wait and verify cleanup task is still running
        await asyncio.sleep(1.0)
        assert cache._cleanup_running

        await cache.stop_background_cleanup()

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, cache_with_short_retention):
        """Test graceful shutdown of the cache."""
        cache = cache_with_short_retention

        await cache.start_background_cleanup()
        assert cache._cleanup_running

        # Shutdown should stop cleanup
        await cache.shutdown()
        assert not cache._cleanup_running
        assert len(cache._cleanup_callbacks) == 0


class TestCacheSizeAndMemoryManagement:
    """Test cache size limits and memory management."""

    def test_cache_size_limit_enforcement(self):
        """Test that cache size limits are enforced."""
        cache = IncidentCache(max_cache_size=5, cleanup_interval_minutes=60)

        # Add more incidents than the limit
        for i in range(10):
            incident = Incident(
                incident_id=f"F23000{i:04d}",
                incident_datetime=datetime.utcnow() - timedelta(hours=i),
                priority=1,
                units=["E1"],
                address=f"Address {i}",
                incident_type="Test",
                status=IncidentStatus.CLOSED,
                first_seen=datetime.utcnow() - timedelta(hours=i),
                last_seen=datetime.utcnow() - timedelta(hours=i - 1),
                closed_at=datetime.utcnow() - timedelta(hours=i - 1),
            )
            cache.add_incident(incident)

        # Trigger limit check
        cache._check_memory_and_cache_limits()

        # Should have removed excess incidents
        assert len(cache.get_all_incidents()) <= cache._max_cache_size

    def test_force_cleanup_oldest(self):
        """Test forced cleanup of oldest incidents."""
        cache = IncidentCache()

        # Add incidents with different closed_at times
        incidents = []
        for i in range(5):
            closed_time = datetime.utcnow() - timedelta(hours=i + 1)
            incident = Incident(
                incident_id=f"F23000{i:04d}",
                incident_datetime=closed_time,
                priority=1,
                units=["E1"],
                address=f"Address {i}",
                incident_type="Test",
                status=IncidentStatus.CLOSED,
                first_seen=closed_time,
                last_seen=closed_time,
                closed_at=closed_time,
            )
            cache.add_incident(incident)
            incidents.append(incident)

        # Force removal of 3 oldest
        removed = cache._force_cleanup_oldest(3)

        assert removed == 3
        remaining = cache.get_all_incidents()
        assert len(remaining) == 2

        # Verify the oldest ones were removed (higher hours = older)
        remaining_ids = {inc.incident_id for inc in remaining}
        assert "F230000000" in remaining_ids  # Most recent (0 hours ago)
        assert "F230000001" in remaining_ids  # Second most recent (1 hour ago)

    def test_force_cleanup_no_closed_incidents(self):
        """Test force cleanup when there are no closed incidents."""
        cache = IncidentCache()

        # Add only active incidents
        for i in range(3):
            incident = Incident(
                incident_id=f"F23000{i:04d}",
                incident_datetime=datetime.utcnow(),
                priority=1,
                units=["E1"],
                address=f"Address {i}",
                incident_type="Test",
                status=IncidentStatus.ACTIVE,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
            cache.add_incident(incident)

        # Force cleanup should remove nothing
        removed = cache._force_cleanup_oldest(5)
        assert removed == 0
        assert len(cache.get_all_incidents()) == 3

    def test_memory_monitoring_with_psutil(self):
        """Test memory monitoring when psutil is available."""
        # Mock psutil module and process
        mock_psutil = Mock()
        mock_process = Mock()
        mock_process.memory_percent.return_value = 85.0  # High memory usage
        mock_psutil.Process.return_value = mock_process

        # Patch the import to return our mock
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            cache = IncidentCache(memory_warning_threshold=0.8)

            # Add some incidents
            for i in range(3):
                incident = Incident(
                    incident_id=f"F23000{i:04d}",
                    incident_datetime=datetime.utcnow(),
                    priority=1,
                    units=["E1"],
                    address=f"Address {i}",
                    incident_type="Test",
                    status=IncidentStatus.ACTIVE,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
                cache.add_incident(incident)

            initial_warnings = cache._memory_warnings
            cache._check_memory_and_cache_limits()

            # Should have triggered a memory warning
            assert cache._memory_warnings > initial_warnings

    def test_memory_monitoring_without_psutil(self):
        """Test memory monitoring when psutil is not available."""
        cache = IncidentCache()

        # Should not crash when psutil is not available
        try:
            cache._check_memory_and_cache_limits()
        except ImportError:
            pytest.fail("Should handle missing psutil gracefully")


class TestCacheStatistics:
    """Test enhanced cache statistics and metrics."""

    def test_comprehensive_cache_stats(self):
        """Test that comprehensive statistics are returned."""
        cache = IncidentCache(
            retention_hours=48,
            cleanup_interval_minutes=30,
            max_cache_size=1000,
            memory_warning_threshold=0.75,
        )

        # Add some incidents
        for i in range(5):
            status = (
                IncidentStatus.ACTIVE if i < 3 else IncidentStatus.CLOSED
            )
            incident = Incident(
                incident_id=f"F23000{i:04d}",
                incident_datetime=datetime.utcnow(),
                priority=1,
                units=["E1"],
                address=f"Address {i}",
                incident_type="Test",
                status=status,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
            cache.add_incident(incident)

        stats = cache.get_cache_stats()

        # Verify all expected fields are present
        expected_fields = [
            "total_incidents",
            "active_incidents",
            "closed_incidents",
            "retention_hours",
            "max_cache_size",
            "cleanup_interval_minutes",
            "memory_warning_threshold",
            "cleanup_running",
            "total_cleanups",
            "total_removed",
            "last_cleanup",
            "memory_warnings",
            "estimated_memory_mb",
            "cache_utilization",
        ]

        for field in expected_fields:
            assert field in stats, f"Missing field: {field}"

        # Verify counts
        assert stats["total_incidents"] == 5
        assert stats["active_incidents"] == 3
        assert stats["closed_incidents"] == 2
        assert stats["retention_hours"] == 48
        assert stats["max_cache_size"] == 1000
        assert stats["cache_utilization"] == 0.5  # 5/1000 * 100

    def test_cache_stats_memory_estimates(self):
        """Test memory estimation in cache statistics."""
        cache = IncidentCache()

        # Add incident
        incident = Incident(
            incident_id="F230000001",
            incident_datetime=datetime.utcnow(),
            priority=1,
            units=["E1"],
            address="Test Address",
            incident_type="Test",
            status=IncidentStatus.ACTIVE,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        cache.add_incident(incident)

        stats = cache.get_cache_stats()

        # Memory estimate should be present (might be 0 if sys.getsizeof fails)
        assert "estimated_memory_mb" in stats
        assert isinstance(stats["estimated_memory_mb"], (int, float))

    def test_clear_resets_statistics(self):
        """Test that clearing cache resets statistics."""
        cache = IncidentCache()

        # Simulate some cleanup activity
        cache._total_cleanups = 5
        cache._total_removed = 10
        cache._last_cleanup = datetime.utcnow()
        cache._memory_warnings = 2

        # Add incident then clear
        incident = Incident(
            incident_id="F230000001",
            incident_datetime=datetime.utcnow(),
            priority=1,
            units=["E1"],
            address="Test",
            incident_type="Test",
            status=IncidentStatus.ACTIVE,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        cache.add_incident(incident)

        cache.clear()

        # Statistics should be reset
        stats = cache.get_cache_stats()
        assert stats["total_incidents"] == 0
        assert stats["total_cleanups"] == 0
        assert stats["total_removed"] == 0
        assert stats["last_cleanup"] is None
        assert stats["memory_warnings"] == 0


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_cleanup_with_empty_cache(self):
        """Test cleanup when cache is empty."""
        cache = IncidentCache()
        removed = cache.cleanup_expired()
        assert removed == 0

    def test_force_cleanup_zero_target(self):
        """Test force cleanup with zero target count."""
        cache = IncidentCache()
        removed = cache._force_cleanup_oldest(0)
        assert removed == 0

    def test_force_cleanup_negative_target(self):
        """Test force cleanup with negative target count."""
        cache = IncidentCache()
        removed = cache._force_cleanup_oldest(-5)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_stop_cleanup_when_not_running(self):
        """Test stopping cleanup when it's not running."""
        cache = IncidentCache()
        # Should not raise an exception
        await cache.stop_background_cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_task_cancellation(self):
        """Test cleanup task handles cancellation and shutdown gracefully."""
        cache = IncidentCache()
        cache._cleanup_interval_minutes = 10  # Long interval

        await cache.start_background_cleanup()
        assert cache._cleanup_running

        # Test that shutdown handles cleanup properly
        await cache.shutdown()
        assert not cache._cleanup_running
