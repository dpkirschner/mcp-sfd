"""Tests for incident cache operations."""

import threading
import time
from datetime import datetime, timedelta

import pytest

from seattle_api.cache import IncidentCache
from seattle_api.models import Incident, IncidentSearchFilters, IncidentStatus


@pytest.fixture
def cache():
    """Create a fresh incident cache for testing."""
    return IncidentCache(retention_hours=24)


@pytest.fixture
def sample_incident():
    """Create a sample incident for testing."""
    now = datetime.utcnow()
    return Incident(
        incident_id="F230001234",
        incident_datetime=now,
        priority=3,
        units=["E17", "L9"],
        address="123 Test St",
        incident_type="Aid Response",
        status=IncidentStatus.ACTIVE,
        first_seen=now,
        last_seen=now,
    )


@pytest.fixture
def sample_incidents():
    """Create multiple sample incidents for testing."""
    base_time = datetime.utcnow()
    incidents = []

    # Active incident 1
    incidents.append(
        Incident(
            incident_id="F230001234",
            incident_datetime=base_time,
            priority=3,
            units=["E17", "L9"],
            address="123 Test St",
            incident_type="Aid Response",
            status=IncidentStatus.ACTIVE,
            first_seen=base_time,
            last_seen=base_time,
        )
    )

    # Active incident 2
    incidents.append(
        Incident(
            incident_id="F230001235",
            incident_datetime=base_time - timedelta(minutes=30),
            priority=1,
            units=["E22"],
            address="456 Main Ave",
            incident_type="Structure Fire",
            status=IncidentStatus.ACTIVE,
            first_seen=base_time - timedelta(minutes=30),
            last_seen=base_time,
        )
    )

    # Closed incident
    incidents.append(
        Incident(
            incident_id="F230001236",
            incident_datetime=base_time - timedelta(hours=2),
            priority=5,
            units=["M15"],
            address="789 Oak Blvd",
            incident_type="Medical Aid",
            status=IncidentStatus.CLOSED,
            first_seen=base_time - timedelta(hours=2),
            last_seen=base_time - timedelta(hours=1),
            closed_at=base_time - timedelta(hours=1),
        )
    )

    return incidents


class TestIncidentCache:
    """Test cases for IncidentCache."""

    def test_cache_initialization(self):
        """Test cache initialization with custom retention."""
        cache = IncidentCache(retention_hours=48)
        stats = cache.get_cache_stats()
        assert stats["total_incidents"] == 0
        assert stats["retention_hours"] == 48

    def test_add_new_incident(self, cache, sample_incident):
        """Test adding a new incident to cache."""
        cache.add_incident(sample_incident)

        retrieved = cache.get_incident(sample_incident.incident_id)
        assert retrieved is not None
        assert retrieved.incident_id == sample_incident.incident_id
        assert retrieved.address == sample_incident.address

    def test_update_existing_incident(self, cache, sample_incident):
        """Test updating an existing incident preserves first_seen."""
        # Add initial incident
        cache.add_incident(sample_incident)
        original_first_seen = sample_incident.first_seen

        # Update the incident with new data
        updated_incident = sample_incident.model_copy()
        updated_incident.address = "Updated Address"
        updated_incident.first_seen = datetime.utcnow() + timedelta(
            hours=1
        )  # Try to change first_seen

        cache.add_incident(updated_incident)

        retrieved = cache.get_incident(sample_incident.incident_id)
        assert retrieved.address == "Updated Address"
        assert (
            retrieved.first_seen == original_first_seen
        )  # Should preserve original first_seen

    def test_get_nonexistent_incident(self, cache):
        """Test retrieving a non-existent incident returns None."""
        result = cache.get_incident("NONEXISTENT")
        assert result is None

    def test_get_active_incidents(self, cache, sample_incidents):
        """Test retrieving only active incidents."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        active = cache.get_active_incidents()
        assert len(active) == 2  # Only the active ones
        assert all(inc.status == IncidentStatus.ACTIVE for inc in active)

        # Check sorting (newest first)
        assert active[0].incident_datetime > active[1].incident_datetime

    def test_get_all_incidents(self, cache, sample_incidents):
        """Test retrieving all incidents."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        all_incidents = cache.get_all_incidents()
        assert len(all_incidents) == 3

        # Check sorting (newest first)
        for i in range(len(all_incidents) - 1):
            assert (
                all_incidents[i].incident_datetime
                >= all_incidents[i + 1].incident_datetime
            )

    def test_mark_incident_closed(self, cache, sample_incident):
        """Test marking an incident as closed."""
        cache.add_incident(sample_incident)

        success = cache.mark_incident_closed(sample_incident.incident_id)
        assert success is True

        retrieved = cache.get_incident(sample_incident.incident_id)
        assert retrieved.status == IncidentStatus.CLOSED
        assert retrieved.closed_at is not None

        # Test marking already closed incident
        success = cache.mark_incident_closed(sample_incident.incident_id)
        assert success is False

    def test_mark_nonexistent_incident_closed(self, cache):
        """Test marking non-existent incident as closed."""
        success = cache.mark_incident_closed("NONEXISTENT")
        assert success is False

    def test_update_active_incidents(self, cache, sample_incidents):
        """Test updating active incidents based on current active set."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        # Only keep one active incident
        active_ids = {"F230001234"}
        cache.update_active_incidents(active_ids)

        # Check that F230001235 was marked as closed
        incident_235 = cache.get_incident("F230001235")
        assert incident_235.status == IncidentStatus.CLOSED
        assert incident_235.closed_at is not None

        # Check that F230001234 is still active with updated last_seen
        incident_234 = cache.get_incident("F230001234")
        assert incident_234.status == IncidentStatus.ACTIVE

    def test_search_incidents_by_type(self, cache, sample_incidents):
        """Test searching incidents by type."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        filters = IncidentSearchFilters(incident_type="Aid Response")
        results = cache.search_incidents(filters)
        assert len(results) == 1
        assert results[0].incident_type == "Aid Response"

    def test_search_incidents_by_address(self, cache, sample_incidents):
        """Test searching incidents by address."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        filters = IncidentSearchFilters(address_contains="Test")
        results = cache.search_incidents(filters)
        assert len(results) == 1
        assert "Test" in results[0].address

    def test_search_incidents_by_status(self, cache, sample_incidents):
        """Test searching incidents by status."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        filters = IncidentSearchFilters(status=IncidentStatus.ACTIVE)
        results = cache.search_incidents(filters)
        assert len(results) == 2
        assert all(inc.status == IncidentStatus.ACTIVE for inc in results)

    def test_search_incidents_by_priority(self, cache, sample_incidents):
        """Test searching incidents by priority."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        filters = IncidentSearchFilters(priority=1)
        results = cache.search_incidents(filters)
        assert len(results) == 1
        assert results[0].priority == 1

    def test_search_incidents_by_time_range(self, cache, sample_incidents):
        """Test searching incidents by time range."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        # Search for incidents in the last hour
        since = datetime.utcnow() - timedelta(hours=1)
        filters = IncidentSearchFilters(since=since)
        results = cache.search_incidents(filters)
        assert len(results) == 2  # The two recent ones

    def test_search_incidents_multiple_filters(self, cache, sample_incidents):
        """Test searching with multiple filters."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        filters = IncidentSearchFilters(status=IncidentStatus.ACTIVE, priority=3)
        results = cache.search_incidents(filters)
        assert len(results) == 1
        assert results[0].incident_id == "F230001234"

    def test_cleanup_expired_incidents(self, cache):
        """Test cleanup of expired incidents."""
        now = datetime.utcnow()

        # Create an old closed incident
        old_incident = Incident(
            incident_id="F230000001",
            incident_datetime=now - timedelta(hours=48),
            priority=1,
            units=["E1"],
            address="Old Address",
            incident_type="Old Incident",
            status=IncidentStatus.CLOSED,
            first_seen=now - timedelta(hours=48),
            last_seen=now - timedelta(hours=25),
            closed_at=now - timedelta(hours=25),
        )

        # Create a recent closed incident
        recent_incident = Incident(
            incident_id="F230000002",
            incident_datetime=now - timedelta(hours=2),
            priority=1,
            units=["E2"],
            address="Recent Address",
            incident_type="Recent Incident",
            status=IncidentStatus.CLOSED,
            first_seen=now - timedelta(hours=2),
            last_seen=now - timedelta(hours=1),
            closed_at=now - timedelta(hours=1),
        )

        cache.add_incident(old_incident)
        cache.add_incident(recent_incident)

        # Initial state
        assert len(cache.get_all_incidents()) == 2

        # Cleanup expired incidents
        removed_count = cache.cleanup_expired()
        assert removed_count == 1

        # Check that only recent incident remains
        remaining = cache.get_all_incidents()
        assert len(remaining) == 1
        assert remaining[0].incident_id == "F230000002"

    def test_cache_stats(self, cache, sample_incidents):
        """Test cache statistics."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        stats = cache.get_cache_stats()
        assert stats["total_incidents"] == 3
        assert stats["active_incidents"] == 2
        assert stats["closed_incidents"] == 1
        assert stats["retention_hours"] == 24

    def test_clear_cache(self, cache, sample_incidents):
        """Test clearing cache."""
        for incident in sample_incidents:
            cache.add_incident(incident)

        assert len(cache.get_all_incidents()) == 3

        cache.clear()
        assert len(cache.get_all_incidents()) == 0

    def test_thread_safety(self, cache):
        """Test thread safety of cache operations."""
        results = []
        errors = []

        def add_incidents(start_id: int, count: int):
            """Add multiple incidents in a thread."""
            try:
                for i in range(count):
                    incident = Incident(
                        incident_id=f"F23000{start_id + i:04d}",
                        incident_datetime=datetime.utcnow(),
                        priority=1,
                        units=["E1"],
                        address=f"Address {start_id + i}",
                        incident_type="Test Incident",
                        status=IncidentStatus.ACTIVE,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                    cache.add_incident(incident)
                results.append(f"Thread {start_id} completed")
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads adding incidents
        threads = []
        for i in range(5):
            thread = threading.Thread(target=add_incidents, args=(i * 100, 50))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Check results
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 5
        assert len(cache.get_all_incidents()) == 250

    def test_concurrent_read_write(self, cache, sample_incidents):
        """Test concurrent read and write operations."""
        # Add initial incidents
        for incident in sample_incidents:
            cache.add_incident(incident)

        results = []
        errors = []

        def reader():
            """Continuously read from cache."""
            try:
                for _ in range(100):
                    cache.get_all_incidents()
                    cache.get_active_incidents()
                    time.sleep(0.001)
                results.append("Reader completed")
            except Exception as e:
                errors.append(f"Reader error: {e}")

        def writer():
            """Continuously write to cache."""
            try:
                for i in range(100):
                    incident = Incident(
                        incident_id=f"F23999{i:04d}",
                        incident_datetime=datetime.utcnow(),
                        priority=1,
                        units=["E1"],
                        address=f"Writer Address {i}",
                        incident_type="Writer Incident",
                        status=IncidentStatus.ACTIVE,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                    cache.add_incident(incident)
                    time.sleep(0.001)
                results.append("Writer completed")
            except Exception as e:
                errors.append(f"Writer error: {e}")

        # Start reader and writer threads
        reader_thread = threading.Thread(target=reader)
        writer_thread = threading.Thread(target=writer)

        reader_thread.start()
        writer_thread.start()

        reader_thread.join()
        writer_thread.join()

        # Check results
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 2

        # Should have original incidents + writer incidents
        all_incidents = cache.get_all_incidents()
        assert len(all_incidents) >= 103  # 3 original + 100 from writer
