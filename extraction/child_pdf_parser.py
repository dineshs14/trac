"""
TRACES Automation — Child Certificate PDF Parser

Extracts certificate data from Child Certificate PDFs issued under Rule No. 213(9).

The Child Certificate layout differs from Lower TDS certificates.
Uses pdfplumber for text-based extraction.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from data.models import CertificateRecord
from utils.logger import logger


class PDFParseError(Exception):
    """Raised when PDF text extraction or parsing fails."""


def parse_child_pdf(pdf_path: Path, expected_fy: str = "") -> CertificateRecord:
    """Parse a Child Certificate PDF and return a CertificateRecord.

    Args:
        pdf_path:    Path to the downloaded PDF file.
        expected_fy: Expected financial year for validation.

    Returns:
        CertificateRecord populated with extracted data.

    Raises:
        PDFParseError: If critical extraction fails.
    """
    if not pdf_path.exists():
        raise PDFParseError(f"PDF file not found: {pdf_path}")

    text = _extract_text(pdf_path)
    if not text or len(text.strip()) < 50:
        raise PDFParseError(f"PDF appears empty or unreadable: {pdf_path}")

    logger.debug("Extracted %d chars from child PDF %s", len(text), pdf_path.name)

    record = CertificateRecord()

    # ── PAN (from "Details of Payee" section) ──
    record.pan = _extract_payee_pan(text)

    # ── Vendor Name (from "Details of Payee" section) ──
    record.vendor_name = _extract_payee_name(text)

    # ── Child Certificate Number ──
    record.certificate_number = _extract_child_cert_number(text)

    # ── Financial Year ──
    record.financial_year = _extract_financial_year(text) or expected_fy

    # ── TDS Rate ──
    record.tds_rate = _extract_tds_rate(text)

    # ── Nature of Payment ──
    record.nature_of_payment = _extract_nature_of_payment(text)

    # ── Section ──
    record.section = _extract_section(text)

    # ── Certificate Amount ──
    record.certificate_limit = _extract_certificate_amount(text)

    # ── Valid From / To ──
    record.valid_from = _extract_date_field(text, "valid from", "validity.*?from")
    record.valid_to = _extract_date_field(text, "valid to", "validity.*?to", "valid upto")

    # ── Certificate Name ──
    record.certificate_name = pdf_path.name

    logger.info(
        "Parsed Child Cert: PAN=%s, Cert=%s, Vendor=%s",
        record.pan, record.certificate_number, record.vendor_name[:40],
    )

    return record


# ──────────────────────────────────────────────
# Text Extraction
# ──────────────────────────────────────────────

def _extract_text(pdf_path: Path) -> str:
    """Extract all text from all pages of the PDF."""
    all_text = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    all_text.append(page_text)
    except Exception as exc:
        raise PDFParseError(f"Cannot read PDF '{pdf_path}': {exc}") from exc

    return "\n".join(all_text)


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


# ──────────────────────────────────────────────
# Field Extractors — Child-specific patterns
# ──────────────────────────────────────────────

def _extract_payee_pan(text: str) -> str:
    """Extract PAN from the 'Details of Payee' section.

    Child certificates have a distinct section:
        'Details of Payee'
        'PAN: AAHCC2532P'
    """
    # Look in "Details of Payee" context
    match = re.search(
        r"Details\s+of\s+Payee.*?PAN\s*[:\-]?\s*([A-Z]{5}\d{4}[A-Z])",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).upper()

    # Fallback: any PAN near "PAN" keyword
    match = re.search(r"PAN\s*[:\-]?\s*([A-Z]{5}\d{4}[A-Z])", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    # Last resort: first PAN pattern
    pans = re.findall(r"[A-Z]{5}\d{4}[A-Z]", text)
    if pans:
        return pans[0]

    logger.warning("PAN not found in child PDF")
    return ""


def _extract_payee_name(text: str) -> str:
    """Extract vendor/payee name from 'Details of Payee' section."""
    # Pattern: "Details of Payee ... Name: CELLCURE CANCER CENTRE PRIVATE LIMITED"
    match = re.search(
        r"Details\s+of\s+Payee.*?Name\s*[:\-]?\s*(.+?)(?:\n|PAN|Address|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _normalize(match.group(1))

    # Fallback patterns
    match = re.search(
        r"(?:Payee\s*Name|Name\s+of\s+(?:the\s+)?Payee)\s*[:\-]?\s*(.+?)(?:\n|PAN|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        return _normalize(match.group(1))

    # "M/s" pattern
    match = re.search(r"M/s\.?\s+(.+?)(?:\n|PAN|$)", text)
    if match:
        return _normalize(match.group(1))

    logger.warning("Vendor name not found in child PDF")
    return ""


def _extract_child_cert_number(text: str) -> str:
    """Extract the child certificate number.

    Child cert numbers tend to be longer (e.g., 4NA0826ACO4A023).
    """
    # The portal PDF prints a two-line header:
    #   Certificate Number Tax Year Date
    #   4NA0826ACO4A023 2026-27 04-Sep-2026
    # Keep the value on the following line separate from the header labels.
    cert_token = r"[A-Z0-9]{12,}"
    match = re.search(
        rf"Certificate\s+Number\s+Tax\s+Year\s+Date\s*\n\s*({cert_token})\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    # Fallback for alternate portal layouts with a same-line label/value.
    match = re.search(
        rf"^(?:Child\s+)?Certificate\s*(?:No\.?|Number)\s*[:\-]\s*({cert_token})\s*$",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if match:
        return match.group(1).strip()

    # Last fallback: use the certificate number in the explanatory paragraph.
    match = re.search(rf"Certificate\s+Number\s+({cert_token})\b", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    logger.warning("Child certificate number not found in PDF text")
    return ""


def _extract_financial_year(text: str) -> str:
    """Extract the financial/tax year."""
    match = re.search(
        r"(?:Financial|Assessment|Tax)\s*Year\s*[:\-]?\s*(\d{4}\s*-\s*\d{2,4})",
        text,
        re.IGNORECASE,
    )
    if match:
        fy = match.group(1).replace(" ", "")
        parts = fy.split("-")
        if len(parts) == 2 and len(parts[1]) == 4:
            fy = f"{parts[0]}-{parts[1][2:]}"
        return fy

    match = re.search(r"20\d{2}-\d{2}", text)
    return match.group() if match else ""


def _extract_tds_rate(text: str) -> str:
    """Extract the TDS rate."""
    match = re.search(
        r"Rate\s*(?:of\s+(?:Deduction|TDS))?\s*[:\-]?\s*([\d.]+\s*%?)",
        text,
        re.IGNORECASE,
    )
    if match:
        rate = match.group(1).strip()
        if "%" not in rate:
            rate += "%"
        return rate
    return ""


def _extract_nature_of_payment(text: str) -> str:
    """Extract nature of payment."""
    match = re.search(
        r"Nature\s+of\s+Payment\s*[:\-]?\s*(.+?)(?:\n|Section|Rate|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        return _normalize(match.group(1))
    return ""


def _extract_section(text: str) -> str:
    """Extract the section."""
    match = re.search(
        r"(?:Section|u/s)\s*[:\-]?\s*([\d]+[A-Z]*(?:\(\d+\))?)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""


def _extract_certificate_amount(text: str) -> Optional[float]:
    """Extract the child certificate amount."""
    # "Child Certificate Amount" or "Certificate Amount" or "Certificate Limit"
    match = re.search(
        r"(?:Child\s+)?Certificate\s+(?:Amount|Limit)\s*[:\-]?\s*(?:Rs\.?|₹|INR)?\s*([\d,]+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Fallback: "Amount" near cert context
    match = re.search(
        r"Amount\s*[:\-]?\s*(?:Rs\.?|₹|INR)?\s*([\d,]+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass

    return None


def _extract_date_field(text: str, *keywords: str) -> str:
    """Extract a date near one of the given keywords."""
    for kw in keywords:
        pattern = rf"{kw}\s*[:\-]?\s*(\d{{1,2}}[/\-.]\d{{1,2}}[/\-.]\d{{4}})"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""
