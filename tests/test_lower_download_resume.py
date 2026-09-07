from unittest.mock import Mock

from automation import lower_tds_downloader as module
from data.models import CertificateRecord, PortalCertificateRow
from data.tracker_store import TrackerStore
from data.master_tracker import MasterTracker


def test_saved_pdf_finishes_and_is_skipped_without_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'LOWER_TDS_DIR', tmp_path / 'pdfs')
    row = PortalCertificateRow('1NA0000001', deductee_pan='AAAAA1234A', page_number=1)
    key = 'LOWER_TDS|2026-27|AAAAA1234A|1NA0000001'
    store = TrackerStore(tmp_path / 'process.xlsx')
    master = MasterTracker(tmp_path / 'master.xlsx')
    saved = tmp_path / 'saved.pdf'
    saved.write_bytes(b'fixture PDF bytes')
    store.upsert_discovered(key, 'LOWER_TDS', '2026-27', row.pan, row.certificate_number)
    store.update_status(key, 'DOWNLOADED', pdf_path=str(saved))
    monkeypatch.setattr(module, 'parse_lower_tds_pdf', lambda *args: CertificateRecord(
        pan=row.pan, certificate_number=row.certificate_number,
        vendor_name='PAYEE LIMITED', financial_year='2026-27'))
    worker = module.LowerTDSDownloader(Mock(), '2026-27', store, master, Mock(), Mock())
    worker._navigate_to_page_and_select = Mock(side_effect=AssertionError('Must not submit again'))
    worker._download_pdf = Mock(side_effect=AssertionError('Must not download again'))
    worker._reopen_popup_if_needed = Mock()
    worker._process_single_certificate(row)
    assert store.is_completed(key)
    final = next((tmp_path / 'pdfs' / 'FY2026-27').glob('*.pdf'))
    assert final.read_bytes() == b'fixture PDF bytes'
    assert master.find_row('LOWER_TDS', '2026-27', row.pan, row.certificate_number) == 2
    # Resume after a crash between moving the file and marking it complete.
    store.update_status(key, 'VALIDATED', pdf_path=str(final))
    worker._process_single_certificate(row)
    assert final.exists()
    assert store.is_completed(key)
    worker._process_single_certificate(row)
    assert worker.summary.skipped_duplicates == 1
    worker._download_pdf.assert_not_called()
