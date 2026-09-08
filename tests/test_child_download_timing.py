from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from automation.child_certificate_downloader import ChildCertificateDownloader
from automation.flutter_child_download import FlutterChildDownload
from automation.portal_utils import ElementNotFoundError


def card_at(minute):
    card = MagicMock()
    card.get_attribute.return_value = f'Date & Time of Initiating Download 08/09/2026 at 08:{minute} PM'
    card.inner_text.return_value = ''
    return card


def workflow(cards):
    child = FlutterChildDownload(MagicMock(), '2026-27')
    child.initiated_at = datetime(2026, 9, 8, 20, 30, 45)
    collection = child.page.get_by_role.return_value.locator.return_value
    collection.count.return_value = len(cards)
    collection.all.return_value = cards
    return child


def test_previous_minute_is_never_downloaded():
    old = card_at('29')
    assert workflow([old])._matching_modal_card() is None


def test_exact_minute_wins_over_previous_ready_download():
    old, current = card_at('29'), card_at('30')
    assert workflow([old, current])._matching_modal_card() is current


def test_duplicate_minutes_are_rejected():
    with pytest.raises(ElementNotFoundError, match='same initiation minute'):
        workflow([card_at('30'), card_at('30')])._matching_modal_card()


def test_missing_timestamp_does_not_select_first_card():
    child = workflow([card_at('30')])
    child.initiated_at = None
    assert child._matching_modal_card() is None


def test_full_minute_gap_is_waited_without_real_sleep():
    child = ChildCertificateDownloader.__new__(ChildCertificateDownloader)
    child.page = MagicMock()
    child._next_initiation_at = 160.0
    now = [100.0]
    child.page.wait_for_timeout.side_effect = lambda ms: now.__setitem__(0, now[0] + ms / 1000)
    with patch('automation.child_certificate_downloader.time.monotonic', side_effect=lambda: now[0]), patch('automation.child_certificate_downloader.assert_session_alive'):
        child._wait_for_initiation_gap()
    assert now[0] == 160.0
    assert sum(call.args[0] for call in child.page.wait_for_timeout.call_args_list) == 60000


def test_first_certificate_has_no_gap():
    child = ChildCertificateDownloader.__new__(ChildCertificateDownloader)
    child.page = MagicMock()
    child._next_initiation_at = 0.0
    child._wait_for_initiation_gap()
    child.page.wait_for_timeout.assert_not_called()


def test_submission_across_minute_boundary_matches_server_minute():
    old, current = card_at('29'), card_at('31')
    child = workflow([old, current])
    child.initiated_at = datetime(2026, 9, 8, 20, 30, 59)
    child.submission_finished_at = datetime(2026, 9, 8, 20, 31, 2)
    assert child._matching_modal_card() is current


def test_future_minute_outside_submission_is_rejected():
    child = workflow([card_at('31')])
    child.submission_finished_at = datetime(2026, 9, 8, 20, 30, 48)
    assert child._matching_modal_card() is None
