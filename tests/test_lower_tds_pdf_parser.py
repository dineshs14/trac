import pytest

from data.models import CertificateRecord
from extraction.lower_tds_pdf_parser import (
    _apply_certificate_tables, _extract_certificate_number, _extract_tds_rate, PDFParseError,
)


def test_column_headers_are_not_certificate_numbers():
    text = 'Certificate No.: Tax Year: Date:\n1NA0000001 2026-27 03-09-2026\nCertificate No.: 1NA0000001'
    assert _extract_certificate_number(text) == '1NA0000001'
    assert _extract_tds_rate('rate. It does not include surcharge') == ''


def test_structured_tables_distinguish_payer_from_payee():
    record = CertificateRecord()
    _apply_certificate_tables(record, [
        [['Certificate No.:\n1NA0000001', 'Tax Year:\n2026-27']],
        [['Name:', 'PAYER LIMITED'], ['TAN:', 'ABCD12345E']],
        [['Name:', 'PAYEE PRIVATE LIMITED'], ['PAN:', 'AAAAA1234A']],
        [['Section','Nature of\nTransaction','Amount\n(Rs.)','Rate (%)','Valid From','Valid Upto'],
         ['(1)','(2)','(3)','(4)','(5)','(6)'],
         ['393(1)','Commission or\nbrokerage','42,449,720','5.00','03-09-2026','31-03-2027']],
    ])
    assert record.certificate_number == '1NA0000001'
    assert record.vendor_name == 'PAYEE PRIVATE LIMITED'
    assert record.pan == 'AAAAA1234A'
    assert record.financial_year == '2026-27'
    assert record.certificate_limit == 42449720
    assert record.tds_rate == '5.00%'
    assert record.nature_of_payment == 'Commission or brokerage'
    assert record.valid_to == '31-03-2027'


def test_multiple_detail_rows_require_review():
    headers = ['Section','Amount','Rate','Valid From','Valid Upto']
    data = ['393(1)','100','5','01-09-2026','31-03-2027']
    with pytest.raises(PDFParseError, match='Expected one'):
        _apply_certificate_tables(CertificateRecord(), [[headers,data,data]])
