"""
Tests for extraction/validators.py — PAN, cert number, FY validation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extraction.validators import (
    is_valid_pan,
    normalize_fy,
    validate_certificate_number_format,
    validate_amount,
    validate_extracted_data,
)
from data.models import CertificateRecord, PortalCertificateRow


class TestIsValidPAN:
    """Tests for PAN format validation."""

    def test_valid_pan(self):
        assert is_valid_pan("AAHCP9855G") is True

    def test_valid_pan_lowercase(self):
        assert is_valid_pan("aahcp9855g") is True

    def test_invalid_too_short(self):
        assert is_valid_pan("AAHCP985") is False

    def test_invalid_wrong_format(self):
        assert is_valid_pan("12345ABCDE") is False

    def test_empty(self):
        assert is_valid_pan("") is False

    def test_valid_trust_pan(self):
        assert is_valid_pan("AAHCC2532P") is True


class TestNormalizeFY:
    """Tests for financial year normalization."""

    def test_already_normalized(self):
        assert normalize_fy("2026-27") == "2026-27"

    def test_full_year(self):
        assert normalize_fy("2026-2027") == "2026-27"

    def test_no_dash(self):
        assert normalize_fy("202627") == "2026-27"

    def test_with_spaces(self):
        assert normalize_fy(" 2026 - 27 ") == "2026-27"

    def test_long_no_dash(self):
        assert normalize_fy("20262027") == "2026-27"


class TestValidateCertificateNumber:
    """Tests for certificate number format validation."""

    def test_valid_lower_tds(self):
        assert validate_certificate_number_format("1NA0926KBC") is True

    def test_valid_child(self):
        assert validate_certificate_number_format("4NA0826ACO4A023") is True

    def test_empty(self):
        assert validate_certificate_number_format("") is False

    def test_too_short(self):
        assert validate_certificate_number_format("ABC") is False


class TestValidateAmount:
    """Tests for amount validation."""

    def test_valid_float(self):
        assert validate_amount(1700000.0) is True

    def test_zero(self):
        assert validate_amount(0) is True

    def test_none_is_ok(self):
        assert validate_amount(None) is True

    def test_negative_fails(self):
        assert validate_amount(-100) is False

    def test_string_number(self):
        assert validate_amount("1700000") is True

    def test_invalid_string(self):
        assert validate_amount("not_a_number") is False


class TestValidateExtractedData:
    """Tests for cross-validation of PDF data vs portal row."""

    def test_matching_data_passes(self):
        record = CertificateRecord(
            pan="AAHCP9855G",
            certificate_number="1NA0926KBC",
            financial_year="2026-27",
        )
        portal = PortalCertificateRow(
            certificate_number="1NA0926KBC",
            deductee_pan="AAHCP9855G",
        )
        is_valid, errors = validate_extracted_data(record, portal, "2026-27")
        assert is_valid is True
        assert len(errors) == 0

    def test_pan_mismatch_fails(self):
        record = CertificateRecord(
            pan="AAHCP9855G",
            certificate_number="1NA0926KBC",
        )
        portal = PortalCertificateRow(
            certificate_number="1NA0926KBC",
            deductee_pan="XXXXX1234Y",
        )
        is_valid, errors = validate_extracted_data(record, portal, "2026-27")
        assert is_valid is False
        assert any("PAN mismatch" in e for e in errors)

    def test_cert_number_mismatch_fails(self):
        record = CertificateRecord(
            pan="AAHCP9855G",
            certificate_number="WRONG",
        )
        portal = PortalCertificateRow(
            certificate_number="1NA0926KBC",
            deductee_pan="AAHCP9855G",
        )
        is_valid, errors = validate_extracted_data(record, portal, "2026-27")
        assert is_valid is False
        assert any("Certificate number mismatch" in e for e in errors)

    def test_missing_pan_fails(self):
        record = CertificateRecord(
            pan="",
            certificate_number="1NA0926KBC",
        )
        portal = PortalCertificateRow(
            certificate_number="1NA0926KBC",
            deductee_pan="AAHCP9855G",
        )
        is_valid, errors = validate_extracted_data(record, portal, "2026-27")
        assert is_valid is False
        assert any("PAN not extracted" in e for e in errors)
