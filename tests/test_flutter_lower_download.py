"""Browser regressions for the inspected Form 128 table and request controls."""

import pytest
from playwright.sync_api import sync_playwright

from automation import flutter_lower_download as module
from automation.flutter_lower_download import FlutterLowerDownload
from automation.portal_utils import ElementNotFoundError


@pytest.fixture
def popup():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('''
          <div role="group" aria-label="Latest Certificate Card">ARN/Request Number AA0000000001</div>
          <div id="initiated" role="group" aria-label="Initiated Downloads"></div>
          <button id="open" onclick="render(0)">Initiate Download</button>
          <div id="popup"></div>
          <script>
            const headers = ['', '', 'Certificate Number', 'Section Code', 'Deductee PAN',
              'Valid From Date', 'Valid To Date', 'Remarks'];
            const pages = [
              [['1NA0000001','AAAAA1234A'], ['1NA0000002','BBBBB1234B']],
              [['1NA0000003','CCCCC1234C']]
            ];
            function toggle(el) {
              el.textContent = el.textContent === 'Icon (unselected Checkbox)' ?
                'Icon (selected Checkbox)' : 'Icon (unselected Checkbox)';
            }
            function render(index) {
              document.querySelector('#popup').innerHTML = `<div role="dialog">
                Download Certificate against Form No. 128
                <div role="table"><div role="row">${headers.map(h=>`<div role="cell">${h}</div>`).join('')}</div></div>
                <div role="table">${pages[index].map((r,i)=>`<div role="row">
                  <div role="cell"><button onclick="toggle(this)">Icon (unselected Checkbox)</button></div>
                  ${[i+1,r[0],'393(1)',r[1],'01-Sep-2026','31-Mar-2027','-'].map(v=>`<div role="cell">${v}</div>`).join('')}
                </div>`).join('')}</div>
                <button ${index===pages.length-1 ? 'disabled' : ''} onclick="setTimeout(()=>render(${index+1}),150)">Next</button>
                <button onclick="document.querySelector('#popup').innerHTML=''">Cancel</button>
                <button onclick="submit()">Initiate Download</button>
              </div>`;
            }
            function submit() {
              const row = [...document.querySelectorAll('[role=row]')].find(r=>r.textContent.includes('Icon (selected Checkbox)'));
              const pan = row.querySelectorAll('[role=cell]')[4].textContent;
              document.querySelector('#popup').innerHTML='';
              const section = document.querySelector('#initiated');
              section.setAttribute('aria-label',`Initiated Downloads Tax/Financial Year 2026-27 Deductee PAN ${pan} ARN/Request Number AA1234567890`);
              section.innerHTML=`<button onclick="this.textContent='Download'">Refresh</button>`;
            }
          </script>
        ''')
        yield FlutterLowerDownload(page, '2026-27')
        browser.close()


def test_discovers_actual_certificates_across_all_pages(popup):
    rows = popup.discover()
    assert [r.certificate_number for r in rows] == ['1NA0000001','1NA0000002','1NA0000003']
    assert [r.page_number for r in rows] == [1,1,2]
    assert all(r.pan for r in rows)


def test_selects_only_target_then_matches_request(popup, monkeypatch):
    monkeypatch.setattr(module, 'REFRESH_INTERVAL_SECONDS', 0.1)
    rows = popup.discover()
    popup.select(rows[0])  # Reopen after discovery ended on page two.
    popup.select(rows[1])  # Clear the previous selection, not select-all.
    assert popup.dialog.get_by_role('button', name='Icon (selected Checkbox)', exact=True).count() == 1
    popup.submit()
    assert popup.request_arn == 'AA1234567890'
    assert popup.download_button().count() == 0  # Initiate Download is still on the page.
    popup.wait_ready()
    assert popup.download_button().count() == 1
    popup.initiated.evaluate("e=>e.setAttribute('aria-label','Initiated Downloads Tax/Financial Year 2026-27 Deductee PAN ZZZZZ1234Z ARN/Request Number AA1234567890')")
    with pytest.raises(ElementNotFoundError, match='different request'):
        popup.download_button()


def test_missing_pan_fails_before_submission(popup):
    popup.open()
    popup.dialog.locator('[role=row]').nth(1).locator('[role=cell]').nth(4).evaluate("e=>e.textContent=''")
    with pytest.raises(ElementNotFoundError, match='valid PAN'):
        popup.rows()


def test_wait_ready_polls_when_refresh_control_is_absent(popup, monkeypatch):
    monkeypatch.setattr(module, 'REFRESH_INTERVAL_SECONDS', 0.05)
    popup.selected = type('Selected', (), {'pan': 'AAAAA1234A'})()
    popup.request_arn = 'AA1234567890'
    popup.initiated.evaluate("""section => {
      section.setAttribute('aria-label', 'Initiated Downloads Tax/Financial Year 2026-27 Deductee PAN AAAAA1234A ARN/Request Number AA1234567890');
      section.innerHTML = '';
      setTimeout(() => section.innerHTML = '<button>Download</button>', 100);
    }""")
    popup.wait_ready()
    assert popup.download_button().count() == 1


def test_pagination_must_change_rows(popup, monkeypatch):
    monkeypatch.setattr(module, 'ELEMENT_WAIT_TIMEOUT_MS', 300)
    popup.open()
    popup.dialog.get_by_role('button', name='Next', exact=True).evaluate("e=>e.removeAttribute('onclick')")
    with pytest.raises(ElementNotFoundError, match='did not load/change'):
        popup.next_page()
