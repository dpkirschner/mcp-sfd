"""Tests for HTML parser module."""

from unittest.mock import patch

import pytest

from seattle_api.parser import HTMLParseError, IncidentHTMLParser


class TestIncidentHTMLParser:
    """Test cases for IncidentHTMLParser."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = IncidentHTMLParser()

    def test_parse_valid_html_single_incident(self):
        """Test parsing HTML with a single valid incident."""
        html = """
        <html>
        <body>
        <table>
            <tr>
                <th>Date/Time</th>
                <th>Incident #</th>
                <th>Priority</th>
                <th>Units</th>
                <th>Address</th>
                <th>Type</th>
            </tr>
            <tr id="row_1">
                <td class="active">9/17/2025 8:39:31 PM</td>
                <td class="active">F250129499</td>
                <td class="active">1</td>
                <td class="active">E25 L10</td>
                <td class="active">515 Minor Ave</td>
                <td class="active">Auto Fire Alarm</td>
            </tr>
        </table>
        </body>
        </html>
        """

        incidents = self.parser.parse_incidents(html)

        assert len(incidents) == 1
        incident = incidents[0]
        assert incident.datetime_str == "9/17/2025 8:39:31 PM"
        assert incident.incident_id == "F250129499"
        assert incident.priority_str == "1"
        assert incident.units_str == "E25 L10"
        assert incident.address == "515 Minor Ave"
        assert incident.incident_type == "Auto Fire Alarm"

    def test_parse_valid_html_multiple_incidents(self):
        """Test parsing HTML with multiple valid incidents."""
        html = """
        <table>
            <tr id="row_1">
                <td class="active">9/17/2025 8:39:31 PM</td>
                <td class="active">F250129499</td>
                <td class="active">1</td>
                <td class="active">E25 L10</td>
                <td class="active">515 Minor Ave</td>
                <td class="active">Auto Fire Alarm</td>
            </tr>
            <tr id="row_2">
                <td class="active">9/17/2025 9:15:22 PM</td>
                <td class="active">F250129500</td>
                <td class="active">2</td>
                <td class="active">E17*</td>
                <td class="active">1200 3rd Ave</td>
                <td class="active">Aid Response</td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)

        assert len(incidents) == 2
        assert incidents[0].incident_id == "F250129499"
        assert incidents[1].incident_id == "F250129500"

    def test_parse_html_with_malformed_rows(self):
        """Test parsing HTML with some malformed rows."""
        html = """
        <table>
            <tr id="row_1">
                <td class="active">9/17/2025 8:39:31 PM</td>
                <td class="active">F250129499</td>
                <td class="active">1</td>
                <td class="active">E25 L10</td>
                <td class="active">515 Minor Ave</td>
                <td class="active">Auto Fire Alarm</td>
            </tr>
            <tr id="row_2">
                <td class="active">Invalid Date</td>
                <td class="active">F250129500</td>
                <td class="active">2</td>
            </tr>
            <tr id="row_3">
                <td class="active">9/17/2025 9:15:22 PM</td>
                <td class="active">F250129501</td>
                <td class="active">3</td>
                <td class="active">E17</td>
                <td class="active">1200 3rd Ave</td>
                <td class="active">Aid Response</td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)

        # Should parse 2 valid incidents, skip the malformed one
        assert len(incidents) == 2
        assert incidents[0].incident_id == "F250129499"
        assert incidents[1].incident_id == "F250129501"

    def test_parse_empty_html(self):
        """Test parsing empty HTML."""
        with pytest.raises(HTMLParseError, match="Empty HTML content"):
            self.parser.parse_incidents("")

    def test_parse_invalid_html(self):
        """Test parsing invalid HTML."""
        # BeautifulSoup is very resilient, so this won't raise an exception
        # but will return no incidents
        incidents = self.parser.parse_incidents("<<>>invalid html<<>>")
        assert len(incidents) == 0

    def test_parse_html_no_table(self):
        """Test parsing HTML with no incident table."""
        html = """
        <html>
        <body>
        <p>No table here</p>
        </body>
        </html>
        """

        incidents = self.parser.parse_incidents(html)
        assert len(incidents) == 0

    def test_parse_html_empty_table(self):
        """Test parsing HTML with empty table."""
        html = """
        <table>
            <tr>
                <th>Header</th>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)
        assert len(incidents) == 0

    def test_find_incident_table_multiple_tables(self):
        """Test finding the correct table when multiple tables exist."""
        html = """
        <table>
            <tr><td>Wrong table</td></tr>
        </table>
        <table>
            <tr id="row_1">
                <td class="active">9/17/2025 8:39:31 PM</td>
                <td class="active">F250129499</td>
                <td class="active">1</td>
                <td class="active">E25 L10</td>
                <td class="active">515 Minor Ave</td>
                <td class="active">Auto Fire Alarm</td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)
        assert len(incidents) == 1
        assert incidents[0].incident_id == "F250129499"

    def test_parse_incident_row_insufficient_cells(self):
        """Test parsing row with insufficient cells."""
        html = """
        <table>
            <tr>
                <td>9/17/2025 8:39:31 PM</td>
                <td>F250129499</td>
                <td>1</td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)
        assert len(incidents) == 0

    def test_parse_incident_row_empty_cells(self):
        """Test parsing row with empty critical cells."""
        html = """
        <table>
            <tr>
                <td></td>
                <td></td>
                <td>1</td>
                <td>E25</td>
                <td>515 Minor Ave</td>
                <td>Auto Fire Alarm</td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)
        assert len(incidents) == 0

    def test_clean_datetime_string(self):
        """Test datetime string cleaning."""
        # Test with extra whitespace
        result = self.parser._clean_datetime_string("  9/17/2025   8:39:31   PM  ")
        assert result == "9/17/2025 8:39:31 PM"

        # Test with multiple spaces
        result = self.parser._clean_datetime_string("9/17/2025     8:39:31     PM")
        assert result == "9/17/2025 8:39:31 PM"

    def test_clean_units_string(self):
        """Test units string cleaning."""
        # Test with extra whitespace
        result = self.parser._clean_units_string("  E25   L10  ")
        assert result == "E25 L10"

        # Test with multiple spaces
        result = self.parser._clean_units_string("E25     L10")
        assert result == "E25 L10"

    def test_clean_address_string(self):
        """Test address string cleaning."""
        # Test with extra whitespace
        result = self.parser._clean_address_string("  515   Minor   Ave  ")
        assert result == "515 Minor Ave"

    def test_clean_incident_type_string(self):
        """Test incident type string cleaning."""
        # Test with extra whitespace
        result = self.parser._clean_incident_type_string("  Auto   Fire   Alarm  ")
        assert result == "Auto Fire Alarm"

    def test_looks_like_datetime_valid(self):
        """Test datetime validation with valid strings."""
        assert self.parser._looks_like_datetime("9/17/2025 8:39:31 PM")
        assert self.parser._looks_like_datetime("12/31/2024 11:59:59 AM")
        assert self.parser._looks_like_datetime("1/1/2025 1:00:00 PM")

    def test_looks_like_datetime_invalid(self):
        """Test datetime validation with invalid strings."""
        assert not self.parser._looks_like_datetime("")
        assert not self.parser._looks_like_datetime("Not a date")
        assert not self.parser._looks_like_datetime("F250129499")
        assert not self.parser._looks_like_datetime("Auto Fire Alarm")

    def test_parse_incidents_with_whitespace_variations(self):
        """Test parsing incidents with various whitespace patterns."""
        html = """
        <table>
            <tr>
                <td>   9/17/2025 8:39:31 PM   </td>
                <td>  F250129499  </td>
                <td>    1    </td>
                <td>   E25   L10   </td>
                <td>   515   Minor   Ave   </td>
                <td>   Auto   Fire   Alarm   </td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)

        assert len(incidents) == 1
        incident = incidents[0]
        assert incident.datetime_str == "9/17/2025 8:39:31 PM"
        assert incident.incident_id == "F250129499"
        assert incident.priority_str == "1"
        assert incident.units_str == "E25 L10"
        assert incident.address == "515 Minor Ave"
        assert incident.incident_type == "Auto Fire Alarm"

    def test_parse_incidents_with_html_entities(self):
        """Test parsing incidents with HTML entities."""
        html = """
        <table>
            <tr>
                <td>9/17/2025 8:39:31 PM</td>
                <td>F250129499</td>
                <td>1</td>
                <td>E25&nbsp;L10</td>
                <td>515&nbsp;Minor&nbsp;Ave</td>
                <td>Auto&nbsp;Fire&nbsp;Alarm</td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)

        assert len(incidents) == 1
        incident = incidents[0]
        # BeautifulSoup should handle HTML entities
        assert "E25" in incident.units_str and "L10" in incident.units_str

    @patch("seattle_api.parser.logger")
    def test_parse_incidents_logs_failures(self, mock_logger):
        """Test that parsing failures are properly logged."""
        html = """
        <table>
            <tr>
                <td>Invalid Date</td>
                <td>F250129499</td>
                <td>1</td>
                <td>E25</td>
                <td>515 Minor Ave</td>
                <td>Auto Fire Alarm</td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)

        assert len(incidents) == 0
        # Check that warning was logged for failed parsing
        mock_logger.warning.assert_called()

    def test_parse_complex_units_string(self):
        """Test parsing complex units strings."""
        html = """
        <table>
            <tr>
                <td>9/17/2025 8:39:31 PM</td>
                <td>F250129499</td>
                <td>1</td>
                <td>E25* L10 BC4</td>
                <td>515 Minor Ave</td>
                <td>Auto Fire Alarm</td>
            </tr>
        </table>
        """

        incidents = self.parser.parse_incidents(html)

        assert len(incidents) == 1
        assert incidents[0].units_str == "E25* L10 BC4"
