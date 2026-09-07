"""
TRACES Automation — Data Models

Dataclasses used across the project for structured data exchange.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PortalCertificateRow:
    """A single row as it appears in the portal download popup table."""

    certificate_number: str
    section_code: str = ""
    deductee_pan: str = ""
    valid_from: str = ""
    valid_to: str = ""
    remarks: str = ""
    page_number: int = 0
    row_index: int = 0  # zero-based index within the page

    @property
    def pan(self) -> str:
        return self.deductee_pan


@dataclass
class CertificateRecord:
    """Unified record representing a certificate (Lower TDS or Child)."""

    certificate_type: str = ""          # LOWER_TDS | CHILD
    pan: str = ""
    vendor_name: str = ""
    certificate_number: str = ""
    certificate_short_number: str = ""  # Derived — see naming.py
    financial_year: str = ""
    tds_rate: str = ""
    nature_of_payment: str = ""
    section: str = ""
    section_code: str = ""
    certificate_limit: Optional[float] = None
    valid_from: str = ""
    valid_to: str = ""
    certificate_name: str = ""
    date_received: str = ""
    date_of_issue: str = ""
    application_form_no: str = ""
    applicable_income_tax_act: str = ""
    q1_amount_consumed: Optional[float] = None
    q2_amount_consumed: Optional[float] = None
    q3_amount_consumed: Optional[float] = None
    q4_amount_consumed: Optional[float] = None
    total_amount_consumed: Optional[float] = None
    available_amount: Optional[float] = None
    date_of_cancellation: str = ""
    notes: str = ""
    pdf_path: str = ""
    processing_status: str = ""
    last_updated: str = ""

    @property
    def unique_key(self) -> str:
        return f"{self.certificate_type}|{self.financial_year}|{self.pan}|{self.certificate_number}"


@dataclass
class ConsumptionEntry:
    """One row from the Consumption Details table on the Services page."""

    token_acknowledgement_number: str = ""
    financial_year: str = ""
    quarter: str = ""          # Q1 / Q2 / Q3 / Q4
    form_type: str = ""
    consumed_amount: float = 0.0


@dataclass
class DownloadRequest:
    """Tracks an initiated download request in the portal."""

    certificate_number: str = ""
    certificate_type: str = ""
    financial_year: str = ""
    pan: str = ""
    arn_request_number: str = ""
    initiated_at: str = ""
    status: str = ""           # INITIATED / READY / DOWNLOADED / FAILED
    original_filename: str = ""
    final_filename: str = ""
    pdf_path: str = ""


@dataclass
class RunSummary:
    """Aggregated statistics for a single automation run."""

    task: str = ""
    financial_year: str = ""
    portal_records_discovered: int = 0
    already_completed: int = 0
    new_records: int = 0
    downloads_initiated: int = 0
    downloads_successful: int = 0
    master_rows_added: int = 0
    master_rows_updated: int = 0
    services_records_updated: int = 0
    failed: int = 0
    validation_failed: int = 0
    skipped_duplicates: int = 0
    run_start: Optional[datetime] = None
    run_end: Optional[datetime] = None

    @property
    def run_duration(self) -> str:
        if self.run_start and self.run_end:
            delta = self.run_end - self.run_start
            minutes, seconds = divmod(int(delta.total_seconds()), 60)
            hours, minutes = divmod(minutes, 60)
            return f"{hours}h {minutes}m {seconds}s"
        return "N/A"

    def print_summary(self) -> str:
        lines = [
            "",
            "=" * 50,
            "  RUN SUMMARY",
            "=" * 50,
            f"  Task:                      {self.task}",
            f"  Financial Year:            {self.financial_year}",
            f"  Portal records discovered: {self.portal_records_discovered}",
            f"  Already completed:         {self.already_completed}",
            f"  New:                       {self.new_records}",
            f"  Downloaded:                {self.downloads_successful}",
            f"  Master rows added:         {self.master_rows_added}",
            f"  Master rows updated:       {self.master_rows_updated}",
            f"  Services records updated:  {self.services_records_updated}",
            f"  Failed:                    {self.failed}",
            f"  Validation failed:         {self.validation_failed}",
            f"  Skipped duplicates:        {self.skipped_duplicates}",
            f"  Run duration:              {self.run_duration}",
            "=" * 50,
        ]
        return "\n".join(lines)
