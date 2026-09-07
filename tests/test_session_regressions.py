from unittest.mock import MagicMock, patch

from automation.session_manager import SessionManager
from automation.services_updater import ServicesUpdater
from config import TRACES_CHILD_CERT_URL


def page_at(url):
    page = MagicMock()
    page.url = url
    page.is_closed.return_value = False
    page.locator.return_value.count.return_value = 0
    page.get_by_text.return_value.count.return_value = 0
    return page


def test_child_page_is_reused_without_login_or_reload():
    session = SessionManager()
    page = page_at(TRACES_CHILD_CERT_URL)
    session._page = page
    assert session.ensure_authenticated(TRACES_CHILD_CERT_URL) is page
    page.goto.assert_not_called()


def test_route_exception_is_not_an_authenticated_session():
    page = page_at(TRACES_CHILD_CERT_URL)
    page.get_by_text.return_value.count.return_value = 1
    assert not SessionManager()._is_authenticated(page)


def test_services_unreadable_page_is_reported_as_failure():
    updater = ServicesUpdater(MagicMock(), '2026-27', MagicMock(), MagicMock())
    with patch('automation.services_updater.navigate_to_services_page'), patch(
        'automation.services_updater.assert_session_alive'
    ), patch.object(updater, '_extract_page_entries', return_value=[]):
        summary = updater.run()
    assert summary.failed == 1
    assert summary.services_records_updated == 0
