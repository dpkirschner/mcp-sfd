"""Tests for incident search filtering functionality."""

from datetime import UTC, datetime

from seattle_api.models import Incident, IncidentStatus



class TestSearchEndpoint:
    """Test cases for the search endpoint."""

    def test_search_general_query_incident_type(self, client):
        """Test general query searching in incident type."""
        response = client.get("/incidents/search?q=fire")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2  # Structure Fire and Brush Fire
        assert data["metadata"]["total_matches"] == 2
        assert data["metadata"]["search_query"] == "fire"

        # Check that both fire incidents are returned
        incident_types = [incident["incident_type"] for incident in data["data"]]
        assert "Structure Fire" in incident_types
        assert "Brush Fire" in incident_types

    def test_search_general_query_address(self, client):
        """Test general query searching in address."""
        response = client.get("/incidents/search?q=seattle")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 3  # All Seattle incidents
        assert data["metadata"]["search_query"] == "seattle"

        # Check that all Seattle incidents are returned
        addresses = [incident["address"] for incident in data["data"]]
        seattle_addresses = [addr for addr in addresses if "Seattle" in addr]
        assert len(seattle_addresses) == 3

    def test_search_general_query_incident_id(self, client):
        """Test general query searching in incident ID."""
        response = client.get("/incidents/search?q=FIRE")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2  # FIRE001 and FIRE002

        incident_ids = [incident["incident_id"] for incident in data["data"]]
        assert "FIRE001" in incident_ids
        assert "FIRE002" in incident_ids

    def test_search_general_query_units(self, client):
        """Test general query searching in units."""
        response = client.get("/incidents/search?q=E16")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1  # Only FIRE001 has E16
        assert data["data"][0]["incident_id"] == "FIRE001"

    def test_search_by_status(self, client):
        """Test filtering by status."""
        response = client.get("/incidents/search?status=active")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 3  # 3 active incidents

        # Verify all returned incidents are active
        for incident in data["data"]:
            assert incident["status"] == "active"

    def test_search_by_incident_type(self, client):
        """Test filtering by incident type."""
        response = client.get("/incidents/search?incident_type=fire")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2  # Structure Fire and Brush Fire

        # Verify all returned incidents contain "fire" in type
        for incident in data["data"]:
            assert "fire" in incident["incident_type"].lower()

    def test_search_by_address(self, client):
        """Test filtering by address."""
        response = client.get("/incidents/search?address=main")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1  # Only 123 Main St
        assert "Main St" in data["data"][0]["address"]

    def test_search_by_priority(self, client):
        """Test filtering by priority."""
        response = client.get("/incidents/search?priority=3")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1  # Only FIRE001 has priority 3
        assert data["data"][0]["priority"] == 3

    def test_search_by_datetime_range(self, client):
        """Test filtering by datetime range."""
        since_time = "2023-12-25T22:00:00Z"
        until_time = "2023-12-25T23:30:00Z"

        response = client.get(
            f"/incidents/search?since={since_time}&until={until_time}"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2  # FIRE001 and MED001

        # Verify datetime filtering worked
        for incident in data["data"]:
            incident_time = datetime.fromisoformat(
                incident["incident_datetime"].replace("Z", "+00:00")
            )
            assert incident_time >= datetime.fromisoformat(
                since_time.replace("Z", "+00:00")
            )
            assert incident_time <= datetime.fromisoformat(
                until_time.replace("Z", "+00:00")
            )

    def test_search_combined_filters(self, client):
        """Test combining multiple filters."""
        response = client.get("/incidents/search?q=fire&status=active&address=seattle")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1  # Only FIRE001 matches all criteria

        incident = data["data"][0]
        assert incident["incident_id"] == "FIRE001"
        assert "fire" in incident["incident_type"].lower()
        assert incident["status"] == "active"
        assert "Seattle" in incident["address"]

    def test_search_no_results(self, client):
        """Test search with no matching results."""
        response = client.get("/incidents/search?q=nonexistent")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 0
        assert data["metadata"]["total_matches"] == 0
        assert len(data["data"]) == 0

    def test_search_pagination(self, client):
        """Test search with pagination."""
        response = client.get("/incidents/search?limit=2&offset=1")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2  # Limited to 2
        assert data["metadata"]["limit"] == 2
        assert data["metadata"]["offset"] == 1
        assert data["metadata"]["total_matches"] == 5  # Total available
        assert data["metadata"]["has_more"] is True

    def test_search_invalid_datetime_range(self, client):
        """Test search with invalid datetime range."""
        response = client.get(
            "/incidents/search?since=2023-12-25T23:00:00Z&until=2023-12-25T22:00:00Z"
        )
        assert response.status_code == 400
        assert "since" in response.json()["detail"]
        assert "until" in response.json()["detail"]

    def test_search_invalid_pagination(self, client):
        """Test search with invalid pagination parameters."""
        # Invalid limit
        response = client.get("/incidents/search?limit=0")
        assert response.status_code == 422

        # Invalid offset
        response = client.get("/incidents/search?offset=-1")
        assert response.status_code == 422

    def test_search_invalid_priority(self, client):
        """Test search with invalid priority."""
        response = client.get("/incidents/search?priority=15")
        assert response.status_code == 422

    def test_search_case_insensitive(self, client):
        """Test that search is case-insensitive."""
        # Test different case variations
        test_cases = ["FIRE", "fire", "Fire", "FiRe"]

        for query in test_cases:
            response = client.get(f"/incidents/search?q={query}")
            assert response.status_code == 200

            data = response.json()
            assert data["count"] == 2  # Should always find the same 2 fire incidents

    def test_search_partial_matching(self, client):
        """Test partial matching functionality."""
        # Test partial matches
        response = client.get("/incidents/search?incident_type=aid")
        assert response.status_code == 200

        data = response.json()
        assert data["count"] == 1  # "Aid Response"
        assert "Aid Response" in data["data"][0]["incident_type"]

        # Test partial address match
        response = client.get("/incidents/search?address=st")
        assert response.status_code == 200

        data = response.json()
        assert data["count"] >= 2  # Should match "Main St", "First St", "Water St"

    def test_search_empty_query(self, client):
        """Test search with empty query returns all incidents."""
        response = client.get("/incidents/search")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["count"] == 5  # All incidents
        assert data["metadata"]["total_matches"] == 5


class TestSearchFilterHelpers:
    """Test the search filter helper functions."""

    def test_apply_search_filters_general_query(self):
        """Test _apply_search_filters with general query."""
        from seattle_api.routes.incidents import _apply_search_filters

        # Create test incidents for this specific test
        comprehensive_incidents = self._get_test_incidents()

        # Test searching for "fire"
        result = _apply_search_filters(comprehensive_incidents, general_query="fire")
        assert len(result) == 2  # Structure Fire and Brush Fire

        # Test searching for "seattle"
        result = _apply_search_filters(comprehensive_incidents, general_query="seattle")
        assert len(result) == 3  # All Seattle incidents

    def test_apply_search_filters_specific_filters(self):
        """Test _apply_search_filters with specific filters."""
        from seattle_api.routes.incidents import _apply_search_filters

        comprehensive_incidents = self._get_test_incidents()

        # Test status filter - count active incidents
        # Note: Due to use_enum_values=True, status is stored as string
        active_incidents = [
            i
            for i in comprehensive_incidents
            if i.status == IncidentStatus.ACTIVE
        ]
        result = _apply_search_filters(
            comprehensive_incidents, status_filter=IncidentStatus.ACTIVE
        )
        assert len(result) == len(active_incidents)

        # Test incident type filter
        result = _apply_search_filters(comprehensive_incidents, incident_type="fire")
        assert len(result) == 2

        # Test address filter
        result = _apply_search_filters(comprehensive_incidents, address="seattle")
        assert len(result) == 3

    def test_apply_search_filters_combined(self):
        """Test _apply_search_filters with combined filters."""
        from seattle_api.routes.incidents import _apply_search_filters

        comprehensive_incidents = self._get_test_incidents()

        # Combine general query with specific filters
        # Find fire incidents that are active
        # Note: Due to use_enum_values=True, status is stored as string
        fire_active_count = len(
            [
                i
                for i in comprehensive_incidents
                if "fire" in i.incident_type.lower()
                and i.status == IncidentStatus.ACTIVE
            ]
        )

        result = _apply_search_filters(
            comprehensive_incidents,
            general_query="fire",
            status_filter=IncidentStatus.ACTIVE,
        )
        assert len(result) == fire_active_count

        # Combine multiple specific filters
        result = _apply_search_filters(
            comprehensive_incidents, incident_type="fire", address="seattle"
        )
        assert len(result) == 2  # Both fire incidents are in Seattle

    def _get_test_incidents(self):
        """Get test incidents for filter helper tests."""
        return [
            Incident(
                incident_id="FIRE001",
                incident_datetime=datetime(2023, 12, 25, 22, 30, 45, tzinfo=UTC),
                priority=3,
                units=["E16", "L9", "BC4"],
                address="123 Main St, Seattle",
                incident_type="Structure Fire",
                status=IncidentStatus.ACTIVE,
                first_seen=datetime(2023, 12, 25, 22, 30, 45, tzinfo=UTC),
                last_seen=datetime(2023, 12, 25, 22, 35, 45, tzinfo=UTC),
            ),
            Incident(
                incident_id="MED001",
                incident_datetime=datetime(2023, 12, 25, 23, 15, 30, tzinfo=UTC),
                priority=5,
                units=["M32", "E25"],
                address="456 Pine Ave, Bellevue",
                incident_type="Aid Response",
                status=IncidentStatus.ACTIVE,
                first_seen=datetime(2023, 12, 25, 23, 15, 30, tzinfo=UTC),
                last_seen=datetime(2023, 12, 25, 23, 20, 30, tzinfo=UTC),
            ),
            Incident(
                incident_id="FIRE002",
                incident_datetime=datetime(2023, 12, 25, 20, 45, 15, tzinfo=UTC),
                priority=2,
                units=["E10", "L6"],
                address="789 Oak Blvd, Seattle",
                incident_type="Brush Fire",
                status=IncidentStatus.CLOSED,
                first_seen=datetime(2023, 12, 25, 20, 45, 15, tzinfo=UTC),
                last_seen=datetime(2023, 12, 25, 21, 15, 15, tzinfo=UTC),
                closed_at=datetime(2023, 12, 25, 21, 15, 15, tzinfo=UTC),
            ),
            Incident(
                incident_id="ALARM001",
                incident_datetime=datetime(2023, 12, 26, 8, 30, 0, tzinfo=UTC),
                priority=7,
                units=["E8"],
                address="321 First St, Redmond",
                incident_type="Alarm Response",
                status=IncidentStatus.ACTIVE,
                first_seen=datetime(2023, 12, 26, 8, 30, 0, tzinfo=UTC),
                last_seen=datetime(2023, 12, 26, 8, 45, 0, tzinfo=UTC),
            ),
            Incident(
                incident_id="RESCUE001",
                incident_datetime=datetime(2023, 12, 24, 14, 20, 0, tzinfo=UTC),
                priority=4,
                units=["L12", "BC2"],
                address="555 Water St, Seattle",
                incident_type="Water Rescue",
                status=IncidentStatus.CLOSED,
                first_seen=datetime(2023, 12, 24, 14, 20, 0, tzinfo=UTC),
                last_seen=datetime(2023, 12, 24, 15, 30, 0, tzinfo=UTC),
                closed_at=datetime(2023, 12, 24, 15, 30, 0, tzinfo=UTC),
            ),
        ]


if __name__ == "__main__":
    pytest.main([__file__])
