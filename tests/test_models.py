"""
Tests for data/models.py — Data model integrity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.models import CertificateRecord, PortalCertificateRow, RunSummary
from datetime import datetime


class TestCertificateRecord:
    """Tests for the CertificateRecord dataclass."""

    def test_unique_key(self):
        record = CertificateRecord(
            certificate_type="LOWER_TDS",
            financial_year="2026-27",
            pan="AAHCP9855G",
            certificate_number="1NA0926KBC",
        )
        assert record.unique_key == "LOWER_TDS|2026-27|AAHCP9855G|1NA0926KBC"

    def test_defaults(self):
        record = CertificateRecord()
        assert record.certificate_type == ""
        assert record.certificate_limit is None
        assert record.q1_amount_consumed is None


class TestPortalCertificateRow:
    """Tests for the PortalCertificateRow dataclass."""

    def test_pan_property(self):
        row = PortalCertificateRow(
            certificate_number="CERT1",
            deductee_pan="AAHCP9855G",
        )
        assert row.pan == "AAHCP9855G"


class TestRunSummary:
    """Tests for the RunSummary dataclass."""

    def test_run_duration(self):
        summary = RunSummary()
        summary.run_start = datetime(2026, 1, 1, 10, 0, 0)
        summary.run_end = datetime(2026, 1, 1, 10, 5, 30)
        assert summary.run_duration == "0h 5m 30s"

    def test_run_duration_no_times(self):
        summary = RunSummary()
        assert summary.run_duration == "N/A"

    def test_print_summary(self):
        summary = RunSummary(task="test", financial_year="2026-27")
        summary.portal_records_discovered = 10
        summary.downloads_successful = 8
        summary.failed = 2
        output = summary.print_summary()
        assert "test" in output
        assert "10" in output
        assert "8" in output
