"""
TRACES Automation — Naming Conventions

Business-defined filename generation and sanitization.
"""

import re

from config import INVALID_FILENAME_CHARS


def sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in Windows filenames.

    Preserves spaces — only strips the specific characters:
    < > : " / \\ | ? *
    Also collapses multiple consecutive spaces into one and strips edges.
    """
    for ch in INVALID_FILENAME_CHARS:
        name = name.replace(ch, "")
    # Collapse multiple spaces
    name = re.sub(r"\s{2,}", " ", name)
    return name.strip()


def lower_tds_filename(pan: str, vendor_name: str, cert_no: str, fy: str) -> str:
    """Build the filename for a Lower TDS certificate PDF.

    Format: {PAN}_{VENDOR}_{CERT_NO}_FY{FY}.pdf
    Example: AAHCP9855G_PROVIDENCE INDIA INSURANCE BROKING PRIVATE LIMITED_1NA0926KBC_FY2026-27.pdf
    """
    vendor_clean = sanitize_filename(vendor_name)
    return f"{pan}_{vendor_clean}_{cert_no}_FY{fy}.pdf"


def child_cert_filename(pan: str, vendor_name: str, cert_no: str) -> str:
    """Build the filename for a Child certificate PDF.

    Format: {PAN}_{VENDOR}_{CERT_NO}.pdf
    Example: AAHCC2532P_CELLCURE CANCER CENTRE PRIVATE LIMITED_4NA0826ACO4A023.pdf
    """
    vendor_clean = sanitize_filename(vendor_name)
    return f"{pan}_{vendor_clean}_{cert_no}.pdf"


def build_unique_key(cert_type: str, fy: str, pan: str, cert_no: str) -> str:
    """Build the composite unique key used for deduplication.

    Format: LOWER_TDS|2026-27|AAHCP9855G|1NA0926KBC
    """
    return f"{cert_type}|{fy}|{pan}|{cert_no}"


def derive_short_certificate_number(cert_no: str) -> str:
    """Derive a short certificate number from the full number.

    TODO: The exact business rule for deriving the short number
    has not been specified. This function is a placeholder.
    When the rule is known, implement it here.
    Returns empty string until business rule is confirmed.
    """
    # Placeholder — do not invent logic
    return ""
