"""
TRACES Automation — Validators

Cross-validates extracted PDF data against portal row metadata.
Ensures PAN, certificate number, and financial year consistency.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from config import PAN_REGEX
from data.models import CertificateRecord, PortalCertificateRow
from utils.logger import logger


def validate_extracted_data(
    record: CertificateRecord,
    portal_row: PortalCertificateRow,
    expected_fy: str,
) -> Tuple[bool, List[str]]:
    """Validate extracted PDF data against the portal row.

    Returns:
        (is_valid, list_of_error_messages)
    """
    errors: List[str] = []

    # ── PAN Validation ──
    if not record.pan:
        errors.append("PAN not extracted from PDF")
    elif not is_valid_pan(record.pan):
        errors.append(f"Invalid PAN format: '{record.pan}'")
    elif portal_row.pan and record.pan.upper() != portal_row.pan.upper():
        errors.append(
            f"PAN mismatch: PDF='{record.pan}' vs Portal='{portal_row.pan}'"
        )

    # ── Certificate Number Validation ──
    if not record.certificate_number:
        errors.append("Certificate number not extracted from PDF")
    elif (
        portal_row.certificate_number
        and record.certificate_number.strip() != portal_row.certificate_number.strip()
    ):
        errors.append(
            f"Certificate number mismatch: PDF='{record.certificate_number}' "
            f"vs Portal='{portal_row.certificate_number}'"
        )

    # ── Financial Year Validation ──
    if record.financial_year and expected_fy:
        if normalize_fy(record.financial_year) != normalize_fy(expected_fy):
            errors.append(
                f"Financial year mismatch: PDF='{record.financial_year}' "
                f"vs Expected='{expected_fy}'"
            )

    # ── Vendor Name ──
    if not record.vendor_name:
        # Warning, not a hard failure
        logger.warning("Vendor name is empty for cert %s", record.certificate_number)

    is_valid = len(errors) == 0

    if not is_valid:
        for err in errors:
            logger.warning("Validation: %s", err)

    return is_valid, errors


def is_valid_pan(pan: str) -> bool:
    """Check whether a string matches the Indian PAN format: AAAAA9999A."""
    return bool(re.fullmatch(PAN_REGEX, pan.strip().upper()))


def normalize_fy(fy: str) -> str:
    """Normalize a financial year string to YYYY-YY format.

    Handles:
        - 2026-27  → 2026-27
        - 2026-2027 → 2026-27
        - 202627   → 2026-27
    """
    fy = fy.strip().replace(" ", "")

    # Already in YYYY-YY
    if re.fullmatch(r"\d{4}-\d{2}", fy):
        return fy

    # YYYY-YYYY
    match = re.fullmatch(r"(\d{4})-(\d{4})", fy)
    if match:
        return f"{match.group(1)}-{match.group(2)[2:]}"

    # YYYYYYYY or YYYYYY
    match = re.fullmatch(r"(\d{4})(\d{2,4})", fy)
    if match:
        second = match.group(2)
        if len(second) == 4:
            second = second[2:]
        return f"{match.group(1)}-{second}"

    return fy


def validate_certificate_number_format(cert_no: str) -> bool:
    """Basic validation that a certificate number looks reasonable.

    TRACES certificate numbers are typically alphanumeric, 8+ characters.
    """
    if not cert_no:
        return False
    cleaned = cert_no.strip()
    if len(cleaned) < 5:
        return False
    if not re.search(r"[A-Z0-9]", cleaned, re.IGNORECASE):
        return False
    return True


def validate_amount(amount) -> bool:
    """Check that an amount value is numeric and non-negative."""
    if amount is None:
        return True  # None is acceptable (not extracted)
    try:
        val = float(amount)
        return val >= 0
    except (ValueError, TypeError):
        return False
