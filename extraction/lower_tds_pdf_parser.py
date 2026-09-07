"""
TRACES Automation — Lower TDS PDF Parser

Extracts certificate data from Lower TDS / Section 197(1) PDFs.

Uses pdfplumber for text-based extraction (no OCR).
Handles multiline fields, whitespace normalization, and common PDF quirks.
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


def parse_lower_tds_pdf(pdf_path: Path, expected_fy: str = "") -> CertificateRecord:
    """Parse a Lower TDS certificate PDF and return a CertificateRecord.

    Args:
        pdf_path:    Path to the downloaded PDF file.
        expected_fy: Expected financial year for validation.

    Returns:
        CertificateRecord populated with extracted data.

    Raises:
        PDFParseError: If the PDF cannot be read or critical fields are missing.
    """
    if not pdf_path.exists():
        raise PDFParseError(f"PDF file not found: {pdf_path}")

    text = _extract_text(pdf_path)
    if not text or len(text.strip()) < 50:
        raise PDFParseError(f"PDF appears empty or unreadable: {pdf_path}")

    logger.debug("Extracted %d chars from %s", len(text), pdf_path.name)

    record = CertificateRecord()

    # ── PAN ──
    record.pan = _extract_pan(text)

    # ── Vendor / Payee Name ──
    record.vendor_name = _extract_vendor_name(text)

    # ── Certificate Number ──
    record.certificate_number = _extract_certificate_number(text)

    # ── Financial Year ──
    record.financial_year = _extract_financial_year(text) or expected_fy

    # ── TDS Rate ──
    record.tds_rate = _extract_tds_rate(text)

    # ── Nature of Payment ──
    record.nature_of_payment = _extract_nature_of_payment(text)

    # ── Section ──
    record.section = _extract_section(text)

    # ── Certificate Limit / Amount ──
    record.certificate_limit = _extract_certificate_limit(text)

    # ── Valid From / To ──
    record.valid_from = _extract_date_field(text, "valid from", "validity.*?from")
    record.valid_to = _extract_date_field(text, "valid to", "validity.*?to", "valid upto")

    # CPCTDS lays labels and values in separate columns. Text order alone can
    # associate a certificate number with "Tax" or the payee with the payer.
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            _apply_certificate_tables(record, page.extract_tables())

    # ── Certificate Name ──
    record.certificate_name = pdf_path.name

    logger.info(
        "Parsed Lower TDS: PAN=%s, Cert=%s, Vendor=%s",
        record.pan, record.certificate_number, record.vendor_name[:40],
    )

    return record


def _apply_certificate_tables(record: CertificateRecord, tables: list) -> None:
    """Read the bordered header, payee and certificate detail tables."""
    for table in tables:
        if not table:
            continue
        normalized = [[_normalize(cell or "") for cell in row] for row in table]
        for row in normalized:
            for cell in row:
                cert = re.fullmatch(r"Certificate No\.:\s*([A-Z0-9]{8,})", cell)
                if cert:
                    record.certificate_number = cert.group(1)
                year = re.fullmatch(r"Tax Year:\s*(\d{4}-\d{2})", cell)
                if year:
                    record.financial_year = year.group(1)
        fields = {row[0].rstrip(":"): row[1] for row in normalized if len(row) == 2}
        # Payer uses TAN; the payee table contains PAN. Never use the payer name.
        if "PAN" in fields and "Name" in fields:
            record.pan = fields["PAN"]
            record.vendor_name = fields["Name"]
        headers = normalized[0]
        if "Section" in headers and "Valid From" in headers and "Valid Upto" in headers:
            data = [row for row in normalized[1:] if len(row) == len(headers)
                    and re.fullmatch(r"\d{2}-\d{2}-\d{4}", row[headers.index("Valid From")])]
            if len(data) != 1:
                raise PDFParseError("Expected one certificate detail row; review PDF with multiple/invalid rows")
            values = dict(zip(headers, data[0]))
            record.section_code = values["Section"]
            record.nature_of_payment = values.get("Nature of Transaction", "")
            amount_key = next((key for key in headers if key.startswith("Amount")), None)
            rate_key = next((key for key in headers if key.startswith("Rate")), None)
            if not amount_key or not rate_key:
                raise PDFParseError("Certificate table is missing Amount or Rate")
            amount = values[amount_key].replace(",", "")
            rate = values[rate_key].rstrip("%")
            if not re.fullmatch(r"\d+(?:\.\d+)?", amount) or not re.fullmatch(r"\d+(?:\.\d+)?", rate):
                raise PDFParseError("Certificate table amount/rate is not numeric")
            record.certificate_limit = float(amount)
            record.tds_rate = rate + "%"
            record.valid_from = values["Valid From"]
            record.valid_to = values["Valid Upto"]


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


# ──────────────────────────────────────────────
# Field Extractors
# ──────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Normalize whitespace: collapse multiple spaces/newlines."""
    return re.sub(r"\s+", " ", text).strip()


def _extract_pan(text: str) -> str:
    """Extract PAN number (format: 5 alpha + 4 digit + 1 alpha)."""
    # Look near "PAN" keyword first
    pan_context = re.search(r"PAN\s*[:\-]?\s*([A-Z]{5}\d{4}[A-Z])", text, re.IGNORECASE)
    if pan_context:
        return pan_context.group(1).upper()

    # Fallback: any PAN-like pattern
    all_pans = re.findall(r"[A-Z]{5}\d{4}[A-Z]", text)
    if all_pans:
        return all_pans[0]

    logger.warning("PAN not found in PDF text")
    return ""


def _extract_vendor_name(text: str) -> str:
    """Extract the vendor/payee name from the PDF.

    Common patterns:
        - "Name of the Payee: VENDOR NAME"
        - "Details of Payee ... Name: VENDOR NAME"
        - "Payee Name: VENDOR NAME"
        - "M/s VENDOR NAME"
    """
    # Pattern 1: "Name of the Payee" or "Payee Name"
    match = re.search(
        r"(?:Name\s+of\s+(?:the\s+)?Payee|Payee\s*Name)\s*[:\-]?\s*(.+?)(?:\n|PAN|Address|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        return _normalize(match.group(1))

    # Pattern 2: "Details of Payee" block
    match = re.search(
        r"Details\s+of\s+Payee.*?Name\s*[:\-]?\s*(.+?)(?:\n|PAN|Address|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _normalize(match.group(1))

    # Pattern 3: "M/s" prefix
    match = re.search(r"M/s\.?\s+(.+?)(?:\n|PAN|Address|$)", text)
    if match:
        return _normalize(match.group(1))

    # Pattern 4: After "Name" in a structured layout
    match = re.search(r"\bName\b\s*[:\-]?\s*([A-Z][A-Z\s&.,]+(?:PRIVATE|LIMITED|LLP|COMPANY|TRUST|FIRM)?[A-Z\s.]*)", text)
    if match:
        name = _normalize(match.group(1))
        if len(name) > 3:
            return name

    logger.warning("Vendor name not found in PDF text")
    return ""


def _extract_certificate_number(text: str) -> str:
    """Extract the certificate number.

    Common patterns:
        - "Certificate No.: 1NA0926KBC"
        - "Certificate Number: 1NA0926KBC"
    """
    match = re.search(
        r"Certificate\s*(?:No\.?|Number)\s*[:\-]?\s*([A-Z0-9]{8,})\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    logger.warning("Certificate number not found in PDF text")
    return ""


def _extract_financial_year(text: str) -> str:
    """Extract the financial year (format: YYYY-YY)."""
    # Pattern: "Financial Year: 2026-27" or "Assessment Year: 2026-27"
    match = re.search(
        r"(?:Financial|Assessment|Tax)\s*Year\s*[:\-]?\s*(\d{4}\s*-\s*\d{2,4})",
        text,
        re.IGNORECASE,
    )
    if match:
        fy = match.group(1).replace(" ", "")
        # Normalize to YYYY-YY
        parts = fy.split("-")
        if len(parts) == 2 and len(parts[1]) == 4:
            fy = f"{parts[0]}-{parts[1][2:]}"
        return fy

    # Fallback: any YYYY-YY pattern
    match = re.search(r"20\d{2}-\d{2}", text)
    if match:
        return match.group()

    return ""


def _extract_tds_rate(text: str) -> str:
    """Extract the TDS rate percentage."""
    # "Rate: 5%" or "Rate of Deduction: 5.00%"
    match = re.search(
        r"Rate\s*(?:of\s+(?:Deduction|TDS))?\s*[:\-]?\s*(\d+(?:\.\d+)?\s*%?)",
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
    """Extract the nature of payment field."""
    match = re.search(
        r"Nature\s+of\s+Payment\s*[:\-]?\s*(.+?)(?:\n|Section|Rate|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        return _normalize(match.group(1))
    return ""


def _extract_section(text: str) -> str:
    """Extract the section under which the certificate is issued."""
    # "Section 194C" or "Section: 194C" or "u/s 194C"
    match = re.search(
        r"(?:Section|u/s)\s*[:\-]?\s*([\d]+[A-Z]*(?:\(\d+\))?)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""


def _extract_certificate_limit(text: str) -> Optional[float]:
    """Extract the certificate limit/amount."""
    # "Certificate Limit: Rs. 1,700,000" or "Amount: ₹ 17,00,000"
    match = re.search(
        r"(?:Certificate\s+Limit|Amount|Limit)\s*[:\-]?\s*(?:Rs\.?|₹|INR)?\s*([\d,]+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if match:
        amount_str = match.group(1).replace(",", "")
        try:
            return float(amount_str)
        except ValueError:
            pass
    return None


def _extract_date_field(text: str, *keywords: str) -> str:
    """Extract a date near one of the given keywords.

    Matches dates in formats: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    """
    for kw in keywords:
        pattern = rf"{kw}\s*[:\-]?\s*(\d{{1,2}}[/\-.]\d{{1,2}}[/\-.]\d{{4}})"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""
