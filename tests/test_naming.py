"""
Tests for utils/naming.py — Filename sanitization and naming conventions.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.naming import (
    sanitize_filename,
    lower_tds_filename,
    child_cert_filename,
    build_unique_key,
    derive_short_certificate_number,
)


class TestSanitizeFilename:
    """Tests for the sanitize_filename function."""

    def test_removes_invalid_chars(self):
        assert sanitize_filename('file<>:"name') == "filename"

    def test_preserves_spaces(self):
        assert sanitize_filename("VENDOR NAME") == "VENDOR NAME"

    def test_collapses_multiple_spaces(self):
        assert sanitize_filename("VENDOR   NAME") == "VENDOR NAME"

    def test_strips_edges(self):
        assert sanitize_filename("  name  ") == "name"

    def test_removes_pipe_and_question(self):
        assert sanitize_filename("test|file?name") == "testfilename"

    def test_removes_backslash(self):
        assert sanitize_filename("path\\to\\file") == "pathtofile"

    def test_preserves_valid_special_chars(self):
        assert sanitize_filename("M&S COMPANY (INDIA)") == "M&S COMPANY (INDIA)"

    def test_empty_string(self):
        assert sanitize_filename("") == ""

    def test_real_vendor_name(self):
        result = sanitize_filename("PROVIDENCE INDIA INSURANCE BROKING PRIVATE LIMITED")
        assert result == "PROVIDENCE INDIA INSURANCE BROKING PRIVATE LIMITED"


class TestLowerTdsFilename:
    """Tests for Lower TDS filename generation."""

    def test_standard_format(self):
        result = lower_tds_filename(
            "AAHCP9855G",
            "PROVIDENCE INDIA INSURANCE BROKING PRIVATE LIMITED",
            "1NA0926KBC",
            "2026-27",
        )
        assert result == (
            "AAHCP9855G_PROVIDENCE INDIA INSURANCE BROKING PRIVATE LIMITED"
            "_1NA0926KBC_FY2026-27.pdf"
        )

    def test_sanitizes_vendor(self):
        result = lower_tds_filename(
            "AAHCP9855G", 'Vendor: "Test"', "CERT1", "2026-27"
        )
        assert '"' not in result
        assert ":" not in result

    def test_ends_with_pdf(self):
        result = lower_tds_filename("PAN12345X", "Vendor", "CERT", "2025-26")
        assert result.endswith(".pdf")


class TestChildCertFilename:
    """Tests for Child certificate filename generation."""

    def test_standard_format(self):
        result = child_cert_filename(
            "AAHCC2532P",
            "CELLCURE CANCER CENTRE PRIVATE LIMITED",
            "4NA0826ACO4A023",
        )
        assert result == (
            "AAHCC2532P_CELLCURE CANCER CENTRE PRIVATE LIMITED"
            "_4NA0826ACO4A023.pdf"
        )

    def test_no_fy_suffix(self):
        result = child_cert_filename("PAN12345X", "Vendor", "CERT")
        assert "FY" not in result


class TestBuildUniqueKey:
    """Tests for unique key construction."""

    def test_lower_tds_key(self):
        result = build_unique_key("LOWER_TDS", "2026-27", "AAHCP9855G", "1NA0926KBC")
        assert result == "LOWER_TDS|2026-27|AAHCP9855G|1NA0926KBC"

    def test_child_key(self):
        result = build_unique_key("CHILD", "2026-27", "AAHCC2532P", "4NA0826ACO4A023")
        assert result == "CHILD|2026-27|AAHCC2532P|4NA0826ACO4A023"


class TestDeriveShortCertificateNumber:
    """Tests for short certificate number derivation (placeholder)."""

    def test_returns_empty_string(self):
        """Until business rule is confirmed, should return empty."""
        assert derive_short_certificate_number("1NA0926KBC") == ""
