"""CPCTDS Form 128 popup workflow, inspected against the live semantic DOM."""

import re
import time

from playwright.sync_api import Page, Locator, expect

from automation.portal_utils import ElementNotFoundError, SessionLostError, assert_session_alive
from config import ELEMENT_WAIT_TIMEOUT_MS, MAX_REFRESH_ATTEMPTS, REFRESH_INTERVAL_SECONDS
from data.models import PortalCertificateRow
from utils.logger import logger


class FlutterLowerDownload:
    def __init__(self, page: Page, fy: str):
        self.page = page
        self.fy = fy
        self.page_number = 1
        self.selected = None
        self.request_arn = ""

    @property
    def dialog(self) -> Locator:
        return self.page.get_by_role("dialog").filter(
            has_text="Download Certificate against Form No. 128"
        )

    @property
    def initiated(self) -> Locator:
        return self.page.get_by_role("group", name=re.compile(r"^Initiated Downloads\b"))

    def _alive(self):
        if self.page.is_closed():
            raise SessionLostError("Browser was closed. Stopping the download run.")
        assert_session_alive(self.page)

    def open(self):
        self._alive()
        if self.dialog.count() == 0:
            button = self.page.get_by_role("button", name="Initiate Download", exact=True)
            expect(button).to_have_count(1, timeout=ELEMENT_WAIT_TIMEOUT_MS)
            button.click()
            self.page_number = 1
        expect(self.dialog).to_be_visible(timeout=ELEMENT_WAIT_TIMEOUT_MS)
        self._wait_rows()

    def _cells(self):
        return self.dialog.locator('[role="row"]').evaluate_all("""rows => rows.map(row =>
            Array.from(row.querySelectorAll('[role="cell"]')).map(cell => cell.textContent.trim()))""")

    def _wait_rows(self, previous=None):
        deadline = time.monotonic() + ELEMENT_WAIT_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            self._alive()
            cells = self._cells()
            if len(cells) > 1 and cells != previous:
                return cells
            self.page.wait_for_timeout(100)
        raise ElementNotFoundError("Certificate popup rows did not load/change")

    def rows(self):
        cells = self._wait_rows()
        headers = cells[0]
        required = ["Certificate Number", "Section Code", "Deductee PAN",
                    "Valid From Date", "Valid To Date", "Remarks"]
        if any(name not in headers for name in required):
            raise ElementNotFoundError(f"Unexpected certificate table headers: {headers}")
        indexes = {name: headers.index(name) for name in required}
        result = []
        for i, values in enumerate(cells[1:]):
            if len(values) != len(headers):
                raise ElementNotFoundError("Incomplete certificate row in popup")
            fields = {name: values[index] for name, index in indexes.items()}
            pan = fields["Deductee PAN"]
            cert = fields["Certificate Number"]
            if not re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan) or not re.fullmatch(r"[A-Z0-9]{8,}", cert):
                raise ElementNotFoundError("Popup row is missing a valid PAN/certificate number")
            result.append(PortalCertificateRow(
                certificate_number=cert, deductee_pan=pan,
                section_code=fields["Section Code"], valid_from=fields["Valid From Date"],
                valid_to=fields["Valid To Date"], remarks=fields["Remarks"],
                page_number=self.page_number, row_index=i,
            ))
        return result

    def next_page(self):
        button = self.dialog.get_by_role("button", name="Next", exact=True)
        expect(button).to_have_count(1, timeout=ELEMENT_WAIT_TIMEOUT_MS)
        if button.is_disabled():
            return False
        previous = self._cells()
        button.click()
        self._wait_rows(previous)
        self.page_number += 1
        return True

    def discover(self):
        self.open()
        found = {}
        signatures = set()
        while True:
            rows = self.rows()
            signature = tuple((row.pan, row.certificate_number) for row in rows)
            if signature in signatures:
                raise ElementNotFoundError("Certificate pagination repeated a page; stopping")
            signatures.add(signature)
            for row in rows:
                found[(row.pan, row.certificate_number)] = row
            logger.info("Certificate popup page %d: %d rows; %d discovered so far.",
                        self.page_number, len(rows), len(found))
            if not self.next_page():
                return list(found.values())

    def select(self, row):
        self.open()
        if self.page_number > row.page_number:
            self.dialog.get_by_role("button", name="Cancel", exact=True).click()
            expect(self.dialog).to_have_count(0, timeout=ELEMENT_WAIT_TIMEOUT_MS)
            self.open()
        while self.page_number < row.page_number:
            if not self.next_page():
                raise ElementNotFoundError(f"Certificate page disappeared for {row.certificate_number}")
        # Only data-row checkboxes: never toggle the select-all header.
        rows = self.dialog.get_by_role("row")
        # The header can also be marked selected; exclude it explicitly.
        for item in rows.all()[1:]:
            button = item.get_by_role("button", name="Icon (selected Checkbox)", exact=True)
            if button.count():
                button.click()
                expect(item.get_by_role("button", name="Icon (unselected Checkbox)", exact=True)).to_have_count(1)
        target = rows.filter(has=self.page.get_by_role("cell", name=row.certificate_number, exact=True))
        expect(target).to_have_count(1, timeout=ELEMENT_WAIT_TIMEOUT_MS)
        expect(target.get_by_role("cell", name=row.pan, exact=True)).to_have_count(1)
        target.get_by_role("button", name="Icon (unselected Checkbox)", exact=True).click()
        expect(target.get_by_role("button", name="Icon (selected Checkbox)", exact=True)).to_have_count(1)
        selected_rows = [item for item in rows.all()[1:] if item.get_by_role(
            "button", name="Icon (selected Checkbox)", exact=True).count()]
        if len(selected_rows) != 1:
            raise ElementNotFoundError("Exactly one certificate must be selected before submission")
        self.selected = row
        self.request_arn = ""
        logger.info("Selected certificate %s (%s).", row.certificate_number, row.pan)

    def submit(self):
        if self.selected is None:
            raise ElementNotFoundError("No certificate selected for initiation")
        self.dialog.get_by_role("button", name="Initiate Download", exact=True).click()
        expect(self.dialog).to_have_count(0, timeout=ELEMENT_WAIT_TIMEOUT_MS)
        expect(self.initiated).to_have_count(1, timeout=ELEMENT_WAIT_TIMEOUT_MS)
        expect(self.initiated).to_have_attribute("aria-label", re.compile(
            r"\b" + re.escape(self.selected.pan) + r"\b"), timeout=ELEMENT_WAIT_TIMEOUT_MS)
        label = self.initiated.get_attribute("aria-label") or ""
        if not re.search(r"Tax/Financial Year\s+" + re.escape(self.fy) + r"\b", label):
            raise ElementNotFoundError("Initiated request year does not match the selected year")
        match = re.search(r"ARN/Request Number\s+([A-Z0-9]+)", label)
        if not match:
            raise ElementNotFoundError("Initiated request did not provide an ARN")
        self.request_arn = match.group(1)
        logger.info("Submitted %s; request ARN %s.", self.selected.certificate_number, self.request_arn)

    def download_button(self):
        if not self.request_arn or self.selected is None:
            raise ElementNotFoundError("No correlated certificate download request")
        label = self.initiated.get_attribute("aria-label") or ""
        for token in (self.request_arn, self.selected.pan, self.fy):
            if not re.search(r"(?<![A-Z0-9])" + re.escape(token) + r"(?![A-Z0-9])", label):
                raise ElementNotFoundError("Initiated download changed to a different request")
        return self.initiated.get_by_role("button", name="Download", exact=True)

    def wait_ready(self):
        for attempt in range(1, MAX_REFRESH_ATTEMPTS + 1):
            self._alive()
            button = self.download_button()
            if button.count() == 1 and button.is_enabled():
                return
            refresh = self.initiated.get_by_role("button", name="Refresh", exact=True)
            logger.info("Waiting for request %s (%d/%d).", self.request_arn, attempt, MAX_REFRESH_ATTEMPTS)
            self.page.wait_for_timeout(REFRESH_INTERVAL_SECONDS * 1000)
            if refresh.count() == 1 and refresh.is_visible() and refresh.is_enabled():
                refresh.click(force=True)
        button = self.download_button()
        if button.count() == 1 and button.is_enabled():
            return
        raise ElementNotFoundError(f"Request {self.request_arn} did not become ready")
