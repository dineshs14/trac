"""
Tests for data/tracker_store.py — Excel-based Tracker CRUD operations.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from data.tracker_store import TrackerStore


@pytest.fixture
def tracker(tmp_path):
    """Create a temporary tracker store for testing."""
    excel_path = tmp_path / "test_automation_tracker.xlsx"
    return TrackerStore(path=excel_path)


class TestTrackerStore:
    """Tests for the TrackerStore class."""

    def test_upsert_discovered_new(self, tracker):
        result = tracker.upsert_discovered(
            unique_key="LOWER_TDS|2026-27|AAHCP9855G|1NA0926KBC",
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="AAHCP9855G",
            certificate_number="1NA0926KBC",
            portal_page=1,
        )
        assert result is True

    def test_upsert_discovered_duplicate(self, tracker):
        tracker.upsert_discovered(
            unique_key="LOWER_TDS|2026-27|AAHCP9855G|1NA0926KBC",
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="AAHCP9855G",
            certificate_number="1NA0926KBC",
        )
        result = tracker.upsert_discovered(
            unique_key="LOWER_TDS|2026-27|AAHCP9855G|1NA0926KBC",
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="AAHCP9855G",
            certificate_number="1NA0926KBC",
        )
        assert result is False

    def test_get_by_key_and_case_insensitivity(self, tracker):
        tracker.upsert_discovered(
            unique_key="TEST|2026-27|PAN1|CERT1",
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="PAN1",
            certificate_number="CERT1",
        )
        row = tracker.get_by_key("TEST|2026-27|PAN1|CERT1")
        assert row is not None
        # Verify access by Title_Case and lowercase/snake_case
        assert row["PAN"] == "PAN1"
        assert row["pan"] == "PAN1"
        assert row["Status"] == "DISCOVERED"
        assert row["status"] == "DISCOVERED"
        assert row.get("Certificate_Number") == "CERT1"
        assert row.get("certificate_number") == "CERT1"

    def test_update_status_and_extra_fields(self, tracker):
        key = "TEST|2026-27|PAN1|CERT1"
        tracker.upsert_discovered(
            unique_key=key,
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="PAN1",
            certificate_number="CERT1",
        )
        tracker.update_status(
            key,
            "DOWNLOADED",
            downloaded_at="2026-09-06 12:00:00",
            original_filename="temp.pdf",
            pdf_path="/path/to/final.pdf",
        )
        row = tracker.get_by_key(key)
        assert row["Status"] == "DOWNLOADED"
        assert row["status"] == "DOWNLOADED"
        assert row["Downloaded_At"] == "2026-09-06 12:00:00"
        assert row["original_filename"] == "temp.pdf"
        assert row["pdf_path"] == "/path/to/final.pdf"

    def test_is_completed(self, tracker):
        key = "TEST|2026-27|PAN1|CERT1"
        tracker.upsert_discovered(
            unique_key=key,
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="PAN1",
            certificate_number="CERT1",
        )
        assert tracker.is_completed(key) is False
        tracker.update_status(key, "COMPLETED")
        assert tracker.is_completed(key) is True

    def test_increment_retry(self, tracker):
        key = "TEST|2026-27|PAN1|CERT1"
        tracker.upsert_discovered(
            unique_key=key,
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="PAN1",
            certificate_number="CERT1",
        )
        c1 = tracker.increment_retry(key, "Error 1")
        assert c1 == 1
        c2 = tracker.increment_retry(key, "Error 2")
        assert c2 == 2
        row = tracker.get_by_key(key)
        assert row.get("retry_count") == "2"

    def test_mark_failed(self, tracker):
        key = "TEST|2026-27|PAN1|CERT1"
        tracker.upsert_discovered(
            unique_key=key,
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="PAN1",
            certificate_number="CERT1",
        )
        tracker.mark_failed(key, "Timeout error")
        row = tracker.get_by_key(key)
        assert row["Status"] == "FAILED"
        assert row["Error_Message"] == "Timeout error"

    def test_reset_failed_to_discovered(self, tracker):
        key1 = "TEST|2026-27|PAN1|CERT1"
        key2 = "TEST|2026-27|PAN2|CERT2"
        key3 = "TEST|2026-27|PAN3|CERT3"
        tracker.upsert_discovered(key1, "LOWER_TDS", "2026-27", "PAN1", "CERT1")
        tracker.upsert_discovered(key2, "LOWER_TDS", "2026-27", "PAN2", "CERT2")
        tracker.upsert_discovered(key3, "LOWER_TDS", "2026-27", "PAN3", "CERT3")

        tracker.mark_failed(key1, "Failed")
        tracker.update_status(key2, "VALIDATION_FAILED")
        tracker.update_status(key3, "COMPLETED")

        reset_count = tracker.reset_failed_to_discovered("2026-27")
        assert reset_count == 2
        assert tracker.get_by_key(key1)["Status"] == "DISCOVERED"
        assert tracker.get_by_key(key2)["Status"] == "DISCOVERED"
        assert tracker.get_by_key(key3)["Status"] == "COMPLETED"

    def test_count_by_status(self, tracker):
        tracker.upsert_discovered("K1", "LOWER_TDS", "2026-27", "P1", "C1")
        tracker.upsert_discovered("K2", "LOWER_TDS", "2026-27", "P2", "C2")
        tracker.update_status("K2", "COMPLETED")

        counts = tracker.count_by_status("2026-27")
        assert counts.get("DISCOVERED") == 1
        assert counts.get("COMPLETED") == 1
