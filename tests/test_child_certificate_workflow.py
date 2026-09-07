"""Comprehensive verification tests for Child Certificate Download (Process 2)."""

from unittest.mock import MagicMock, patch
import pytest

from automation.child_certificate_downloader import ChildCertificateDownloader
from data.models import PortalCertificateRow
from data.master_tracker import MasterTracker
from data.tracker_store import TrackerStore
from data.process_tracker import ProcessTracker


@pytest.fixture
def mock_deps():
    db = MagicMock(spec=TrackerStore)
    master = MagicMock(spec=MasterTracker)
    process_tracker = MagicMock(spec=ProcessTracker)
    failed_tracker = MagicMock()
    return db, master, process_tracker, failed_tracker


def test_child_downloader_initialization(mock_deps):
    db, master, pt, ft = mock_deps
    page = MagicMock()
    downloader = ChildCertificateDownloader(
        page=page,
        fy="2026-27",
        db=db,
        master=master,
        process_tracker=pt,
        failed_tracker=ft,
    )
    assert downloader.fy == "2026-27"
    assert downloader.summary.task == "child-download"
    assert downloader.summary.financial_year == "2026-27"


def test_child_downloader_discover_delegates_to_flutter(mock_deps):
    db, master, pt, ft = mock_deps
    page = MagicMock()
    downloader = ChildCertificateDownloader(
        page=page,
        fy="2026-27",
        db=db,
        master=master,
        process_tracker=pt,
        failed_tracker=ft,
    )

    mock_row = PortalCertificateRow(
        certificate_number="4NA0826ACF4A010",
        deductee_pan="AAABT1234A",
        section_code="194C",
    )

    with patch("automation.child_certificate_downloader.is_flutter_portal", return_value=True), \
         patch.object(downloader.flutter, "discover", return_value=[mock_row]):
        discovered = downloader._discover_all_certificates()
        assert len(discovered) == 1
        assert discovered[0].certificate_number == "4NA0826ACF4A010"
        assert discovered[0].deductee_pan == "AAABT1234A"
