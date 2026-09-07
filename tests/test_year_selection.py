"""Browser regression tests using the saved portal accessibility structure."""

import pytest
from playwright.sync_api import sync_playwright

from automation import year_selection
from automation.navigation import setup_lower_tds_download, setup_child_certificate_download
from automation.portal_utils import ElementNotFoundError


@pytest.fixture
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('''
            <style>flt-semantics {display:block; padding:8px}</style>
            <flutter-view></flutter-view>
            <flt-semantics-host>
              <flt-semantics role="button">Downloads Menu button 6 of 8</flt-semantics>
              <flt-semantics id="child-service" flt-tappable>
                Child Certificate(s) issued under Rule No. 213(9)
              </flt-semantics>
              <flt-semantics role="button">User is Recipient tab selected 2 of 2</flt-semantics>
              <flt-semantics role="group" aria-label="Tax/Financial Year">
                <flt-semantics role="radio" aria-checked="false"
                  onclick="this.setAttribute('aria-checked', 'true')"></flt-semantics>
              </flt-semantics>
              <flt-semantics role="button" id="year"
                onclick="document.querySelector('#options').hidden=false">
                Tax Year , is required, combo box, collapsed
              </flt-semantics>
              <div id="options" hidden>
                <flt-semantics role="option" onclick="
                  document.querySelector('#year').textContent='Tax Year 2026-27 combo box collapsed';
                  document.querySelector('#options').hidden=true">2026-27</flt-semantics>
              </div>
              <div>Latest Certificates T.Y.2026-27</div>
              <flt-semantics role="button">Search</flt-semantics>
            </flt-semantics-host>
        ''')
        yield page
        browser.close()


@pytest.mark.parametrize('setup', [setup_lower_tds_download])
def test_selects_year_even_with_latest_certificates(page, setup):
    setup(page, '2026-27')
    assert page.get_by_role('radio').get_attribute('aria-checked') == 'true'
    assert '2026-27' in page.locator('#year').inner_text()


def test_unavailable_year_stops_instead_of_using_default(page, monkeypatch):
    monkeypatch.setattr(year_selection, 'ELEMENT_WAIT_TIMEOUT_MS', 300)
    with pytest.raises(ElementNotFoundError, match='Could not select'):
        year_selection.select_flutter_year(page, '2025-26')


def test_selects_child_certificate_tax_year(page):
    page.set_content('''
        <flutter-view style="position:fixed;top:200px;left:10px;width:316px;height:56px"></flutter-view>
        <flt-semantics-host>
          <flt-semantics role="group" aria-label="Tax year dropdown">
            <flt-semantics role="button" id="child-year"
              style="position:fixed;top:200px;left:10px;width:300px;height:40px">
              Tax Year, combo box, collapsed
            </flt-semantics>
          </flt-semantics>
          <div id="child-options" hidden>
            <flt-semantics role="option" onclick="
              document.querySelector('#child-year').textContent='Tax Year 2026-27 combo box collapsed';
              document.querySelector('#child-options').hidden=true">2026-27</flt-semantics>
          </div>
        </flt-semantics-host>
    ''')
    page.locator('flutter-view').evaluate("""el => {
        el.onclick = () => document.querySelector('#child-options').hidden = false;
    }""")
    year_selection.select_flutter_child_year(page, '2026-27')
    assert '2026-27' in page.locator('#child-year').inner_text()


def test_unconfirmed_selection_stops(page, monkeypatch):
    monkeypatch.setattr(year_selection, 'ELEMENT_WAIT_TIMEOUT_MS', 300)
    page.get_by_role('option', include_hidden=True).evaluate("el => el.removeAttribute('onclick')")
    with pytest.raises(ElementNotFoundError, match=r'Year control did not confirm|Could not select'):
        year_selection.select_flutter_year(page, '2026-27')


def test_already_selected_year_does_not_open_dropdown(page):
    page.locator('#year').evaluate("el => el.textContent = 'Tax Year 2026-27 combo box collapsed'")
    year_selection.select_flutter_year(page, '2026-27')
    assert page.locator('#options').is_hidden()


def test_live_flutter_option_name(page):
    page.locator('#options [role=option]').evaluate("""el => {
        el.setAttribute('role', 'button');
        el.textContent = '2026-27 not selected 1 of 1';
    }""")
    year_selection.select_flutter_year(page, '2026-27')
    assert '2026-27' in page.locator('#year').inner_text()


def test_inert_semantics_click_reaches_flutter_surface(page):
    page.locator('#year').evaluate("""el => {
        el.removeAttribute('onclick');
        el.style.cssText = 'position:fixed;top:200px;left:10px;width:300px;height:40px;pointer-events:all';
    }""")
    page.locator('flutter-view').evaluate("""el => {
        el.style.cssText = 'position:fixed;top:200px;left:10px;width:316px;height:56px';
        el.onclick = () => document.querySelector('#options').hidden = false;
    }""")
    year_selection.select_flutter_year(page, '2026-27')
    assert '2026-27' in page.locator('#year').inner_text()
    assert page.locator('style').count() == 1  # Temporary pointer style was removed.
