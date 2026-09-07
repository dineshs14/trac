"""Comprehensive verification tests for Services Data Enrichment (Process 3)."""

from unittest.mock import MagicMock, patch
import pytest

from automation.services_updater import ServicesUpdater
from data.models import ConsumptionEntry, CertificateRecord
from data.master_tracker import MasterTracker
from data.tracker_store import TrackerStore
from config import STATUS_SERVICES_UPDATED


@pytest.fixture
def mock_master():
    master = MagicMock(spec=MasterTracker)
    master.find_row_by_pan_cert_fy.return_value = 2
    master.update_services_data.return_value = True
    return master


@pytest.fixture
def mock_tracker():
    tracker = MagicMock(spec=TrackerStore)
    tracker.get_by_key.return_value = {"status": "PARSED"}
    return tracker


def test_services_parse_amount():
    """Verify currency amount parsing handles symbols, commas, spaces."""
    assert ServicesUpdater._parse_amount("1,25,000.50") == 125000.50
    assert ServicesUpdater._parse_amount("₹ 50,000") == 50000.0
    assert ServicesUpdater._parse_amount("$ 1,000,000.00") == 1000000.0
    assert ServicesUpdater._parse_amount("0") == 0.0
    assert ServicesUpdater._parse_amount("") is None
    assert ServicesUpdater._parse_amount("INVALID") is None


def test_services_normalize_quarter():
    """Verify quarter normalization handles Q1-Q4, numbers, and month names."""
    assert ServicesUpdater._normalize_quarter("Q1") == "Q1"
    assert ServicesUpdater._normalize_quarter("1") == "Q1"
    assert ServicesUpdater._normalize_quarter("Apr - Jun") == "Q1"
    assert ServicesUpdater._normalize_quarter("Q2") == "Q2"
    assert ServicesUpdater._normalize_quarter("Jul - Sep") == "Q2"
    assert ServicesUpdater._normalize_quarter("Q3") == "Q3"
    assert ServicesUpdater._normalize_quarter("Oct - Dec") == "Q3"
    assert ServicesUpdater._normalize_quarter("Q4") == "Q4"
    assert ServicesUpdater._normalize_quarter("Jan - Mar") == "Q4"


def test_services_quarter_aggregation_and_sum():
    """Verify multiple consumption entries for the same quarter are correctly summed."""
    entries = [
        ConsumptionEntry(quarter="Q1", consumed_amount=10000.0),
        ConsumptionEntry(quarter="Q1", consumed_amount=15000.0),
        ConsumptionEntry(quarter="Q2", consumed_amount=25000.0),
        ConsumptionEntry(quarter="Q3", consumed_amount=0.0),
        ConsumptionEntry(quarter="Q4", consumed_amount=50000.0),
    ]
    updater = ServicesUpdater(MagicMock(), "2026-27", MagicMock(), MagicMock())
    q_totals = updater._aggregate_by_quarter(entries)

    assert q_totals["Q1"] == 25000.0
    assert q_totals["Q2"] == 25000.0
    assert q_totals["Q3"] == 0.0
    assert q_totals["Q4"] == 50000.0
    assert sum(q_totals.values()) == 100000.0


def test_services_process_entry_end_to_end(mock_master, mock_tracker):
    """Verify _process_entry extracts metadata, aggregates, and updates Master Tracker."""
    page = MagicMock()
    updater = ServicesUpdater(page, "2026-27", mock_tracker, mock_master)

    entry = {
        "pan": "AAABT1234A",
        "certificate_number": "4NA0826ACF4A010",
        "financial_year": "2026-27",
        "row_index": "0",
    }

    mock_details = {
        "certificate_number": "4NA0826ACF4A010",
        "pan": "AAABT1234A",
        "financial_year": "2026-27",
        "application_form_no": "FORM13_2026",
        "applicable_income_tax_act": "Income Tax Act 1961",
        "date_of_issue": "01/04/2026",
        "certificate_validity": "31/03/2027",
        "section": "197",
        "section_code": "194C",
        "nature_of_payment": "Contractor Payment",
        "certificate_limit": "5,00,000",
        "rate_as_per_certificate": "1.00",
        "total_amount_consumed": "1,00,000",
        "date_of_cancellation": "Not Cancelled",
    }

    mock_consumption = [
        ConsumptionEntry(quarter="Q1", consumed_amount=40000.0),
        ConsumptionEntry(quarter="Q2", consumed_amount=60000.0),
    ]

    with patch.object(updater, "_click_certificate_details"), \
         patch.object(updater, "_extract_certificate_details", return_value=mock_details), \
         patch.object(updater, "_extract_consumption_details", return_value=mock_consumption), \
         patch.object(updater, "_go_back_to_list"):
        
        updater._process_entry(entry)

    assert updater.summary.services_records_updated == 1
    mock_master.update_services_data.assert_called_once()
    
    # Check the passed updates dict
    call_args = mock_master.update_services_data.call_args[0]
    pan, cert_no, fy, updates = call_args
    assert pan == "AAABT1234A"
    assert cert_no == "4NA0826ACF4A010"
    assert fy == "2026-27"
    assert updates["Certificate_Limit"] == 500000.0
    assert updates["Q1_Amount_Consumed"] == 40000.0
    assert updates["Q2_Amount_Consumed"] == 60000.0
    assert updates["Total_Amount_Consumed"] == 100000.0
    assert updates["Available_Amount"] == 400000.0
    assert updates["Processing_Status"] == STATUS_SERVICES_UPDATED
