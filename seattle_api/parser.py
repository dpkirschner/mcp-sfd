"""HTML parser for Seattle Fire Department incident data."""

import logging
import re
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup, Tag
import pytz

from .models import RawIncident

logger = logging.getLogger(__name__)


class HTMLParseError(Exception):
    """Exception raised when HTML parsing fails."""
    pass


class IncidentHTMLParser:
    """Parser for Seattle Fire Department incident HTML tables."""

    def __init__(self):
        """Initialize the HTML parser."""
        self.seattle_tz = pytz.timezone('America/Los_Angeles')

    def parse_incidents(self, html_content: str) -> List[RawIncident]:
        """Parse incidents from HTML content.

        Args:
            html_content: HTML content containing incident table

        Returns:
            List of RawIncident objects

        Raises:
            HTMLParseError: When HTML parsing fails
        """
        if not html_content or not html_content.strip():
            raise HTMLParseError("Empty HTML content provided")

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
        except Exception as e:
            raise HTMLParseError(f"Failed to parse HTML: {e}") from e

        # Find the main table containing incidents
        table = self._find_incident_table(soup)
        if not table:
            logger.warning("No incident table found in HTML")
            return []

        # Extract incident rows
        rows = self._find_incident_rows(table)
        logger.info(f"Found {len(rows)} incident rows in HTML table")

        incidents = []
        failed_rows = 0

        for i, row in enumerate(rows):
            try:
                incident = self._parse_incident_row(row)
                if incident:
                    incidents.append(incident)
                else:
                    failed_rows += 1
                    logger.debug(f"Row {i + 1} did not produce a valid incident")
            except Exception as e:
                failed_rows += 1
                logger.warning(f"Failed to parse incident row {i + 1}: {e}")
                # Log the row content for debugging (but limit length)
                try:
                    row_text = row.get_text()[:200] + "..." if len(row.get_text()) > 200 else row.get_text()
                    logger.debug(f"Problematic row content: {row_text}")
                except:
                    logger.debug("Could not extract row content for debugging")
                continue

        if failed_rows > 0:
            logger.warning(f"Failed to parse {failed_rows} out of {len(rows)} rows")

        logger.info(f"Successfully parsed {len(incidents)} incidents from {len(rows)} rows")
        return incidents

    def _find_incident_table(self, soup: BeautifulSoup) -> Optional[Tag]:
        """Find the table containing incident data.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Table element or None if not found
        """
        # Look for tables with incident data
        tables = soup.find_all('table')

        for table in tables:
            # Check if table contains incident-like rows
            rows = table.find_all('tr')
            if len(rows) >= 1:  # At least one row
                # Look for rows with the expected structure
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 6:  # Expected number of columns
                        # Check if first cell looks like a datetime
                        first_cell = cells[0].get_text(strip=True)
                        if self._looks_like_datetime(first_cell):
                            return table

        return None

    def _find_incident_rows(self, table: Tag) -> List[Tag]:
        """Find incident data rows in the table.

        Args:
            table: Table element containing incidents

        Returns:
            List of row elements containing incident data
        """
        rows = table.find_all('tr')
        incident_rows = []

        for row in rows:
            # Skip header rows and empty rows
            if not row.find_all('td'):
                continue

            cells = row.find_all('td')
            if len(cells) >= 6:  # Expected number of columns
                # Check if first cell looks like a datetime
                first_cell = cells[0].get_text(strip=True)
                if self._looks_like_datetime(first_cell):
                    incident_rows.append(row)

        return incident_rows

    def _parse_incident_row(self, row: Tag) -> Optional[RawIncident]:
        """Parse a single incident row.

        Args:
            row: Table row element

        Returns:
            RawIncident object or None if parsing fails
        """
        cells = row.find_all('td')
        if len(cells) < 6:
            logger.warning(f"Incident row has only {len(cells)} cells, expected 6")
            return None

        try:
            # Extract cell text content
            datetime_str = cells[0].get_text(strip=True)
            incident_id = cells[1].get_text(strip=True)
            priority_str = cells[2].get_text(strip=True)
            units_str = cells[3].get_text(strip=True)
            address = cells[4].get_text(strip=True)
            incident_type = cells[5].get_text(strip=True)

            # Basic validation
            if not datetime_str or not incident_id:
                logger.warning("Missing datetime or incident_id in row")
                return None

            # Clean up the data
            datetime_str = self._clean_datetime_string(datetime_str)
            units_str = self._clean_units_string(units_str)
            address = self._clean_address_string(address)
            incident_type = self._clean_incident_type_string(incident_type)

            return RawIncident(
                datetime_str=datetime_str,
                incident_id=incident_id,
                priority_str=priority_str,
                units_str=units_str,
                address=address,
                incident_type=incident_type
            )

        except Exception as e:
            logger.error(f"Error parsing incident row: {e}")
            return None

    def _looks_like_datetime(self, text: str) -> bool:
        """Check if text looks like a datetime string.

        Args:
            text: Text to check

        Returns:
            True if text appears to be a datetime
        """
        if not text:
            return False

        # Look for common datetime patterns
        # M/D/YYYY H:MM:SS AM/PM
        datetime_pattern = r'\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M'
        return bool(re.search(datetime_pattern, text))

    def _clean_datetime_string(self, datetime_str: str) -> str:
        """Clean and normalize datetime string.

        Args:
            datetime_str: Raw datetime string

        Returns:
            Cleaned datetime string
        """
        # Remove extra whitespace and normalize
        cleaned = re.sub(r'\s+', ' ', datetime_str.strip())
        return cleaned

    def _clean_units_string(self, units_str: str) -> str:
        """Clean and normalize units string.

        Args:
            units_str: Raw units string

        Returns:
            Cleaned units string
        """
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', units_str.strip())
        return cleaned

    def _clean_address_string(self, address: str) -> str:
        """Clean and normalize address string.

        Args:
            address: Raw address string

        Returns:
            Cleaned address string
        """
        # Remove extra whitespace and normalize
        cleaned = re.sub(r'\s+', ' ', address.strip())
        return cleaned

    def _clean_incident_type_string(self, incident_type: str) -> str:
        """Clean and normalize incident type string.

        Args:
            incident_type: Raw incident type string

        Returns:
            Cleaned incident type string
        """
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', incident_type.strip())
        return cleaned