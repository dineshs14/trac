"""CPCTDS 2.0 Child Certificate table and one-by-one download workflow."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Download, Locator, Page, expect

from automation.portal_utils import ElementNotFoundError, assert_session_alive
from config import (
    DOWNLOAD_READY_TIMEOUT_MS,
    ELEMENT_WAIT_TIMEOUT_MS,
    MAX_REFRESH_ATTEMPTS,
    REFRESH_INTERVAL_SECONDS,
)
from data.models import PortalCertificateRow
from utils.file_utils import temp_download_path
from utils.logger import logger


CHILD_CERT_RE = re.compile(r"^[A-Z0-9]{12,}$")
PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")


def _deduplicate_text(value: str) -> str:
    words = value.split()
    if len(words) % 2 == 0 and words[: len(words) // 2] == words[len(words) // 2 :]:
        words = words[: len(words) // 2]
    return " ".join(words)


class FlutterChildDownload:
    def __init__(self, page: Page, fy: str):
        self.page = page
        self.fy = fy
        self.page_number = 1
        self.selected: PortalCertificateRow | None = None
        self.initiated_at: datetime | None = None

    def _alive(self) -> None:
        if self.page.is_closed():
            raise ElementNotFoundError("Browser closed during Child Certificate download.")
        assert_session_alive(self.page)

    @property
    def table(self) -> Locator:
        candidates = self.page.locator("flt-semantics[role='group']").filter(
            has_text=re.compile(
                r"Child Certificate Number.*Child Certificate Amount", re.I | re.S
            )
        )
        if candidates.count() == 0:
            return candidates
        # The smallest matching group is the table, not the whole page container.
        items = candidates.all()
        return min(items, key=lambda item: len(item.inner_text()))

    def wait_ready(self) -> None:
        expect(self.table).to_have_count(1, timeout=ELEMENT_WAIT_TIMEOUT_MS)
        expect(self.page.get_by_text(
            re.compile(r"\d+\s+of\s+\d+\s+Selected")
        ).first).to_be_visible(
            timeout=ELEMENT_WAIT_TIMEOUT_MS
        )

    def _rows(self) -> list[PortalCertificateRow]:
        leaves = self.table.locator(
            "flt-semantics:not(:has(flt-semantics))"
        ).all_inner_texts()
        values = [_deduplicate_text(text) for text in leaves]
        values = [text for text in values if text and text.lower() != "icon"]

        rows: list[PortalCertificateRow] = []
        for index, value in enumerate(values):
            if not CHILD_CERT_RE.fullmatch(value):
                continue
            fields = values[index : index + 8]
            if len(fields) != 8 or fields[1] != self.fy or not PAN_RE.fullmatch(fields[3]):
                continue
            rows.append(PortalCertificateRow(
                certificate_number=fields[0],
                section_code=fields[2],
                deductee_pan=fields[3],
                valid_from=fields[5],
                valid_to=fields[6],
                remarks=fields[7],
                page_number=self.page_number,
                row_index=len(rows),
            ))
        if not rows:
            raise ElementNotFoundError(
                f"No Child Certificate rows for Tax Year {self.fy} were readable."
            )
        return rows

    def _next_button(self) -> Locator:
        return self.page.get_by_role("button", name="Next", exact=True)

    def _previous_button(self) -> Locator:
        return self.page.get_by_role("button", name="Previous", exact=True)

    def discover(self) -> list[PortalCertificateRow]:
        self.wait_ready()
        found: dict[tuple[str, str], PortalCertificateRow] = {}
        signatures = set()
        self.page_number = 1
        while True:
            rows = self._rows()
            signature = tuple((row.pan, row.certificate_number) for row in rows)
            if signature in signatures:
                raise ElementNotFoundError("Child Certificate pagination repeated a page.")
            signatures.add(signature)
            for row in rows:
                found[(row.pan, row.certificate_number)] = row
            logger.info(
                "Child Certificate page %d: %d rows; %d discovered so far.",
                self.page_number,
                len(rows),
                len(found),
            )

            next_button = self._next_button()
            expect(next_button).to_have_count(1, timeout=ELEMENT_WAIT_TIMEOUT_MS)
            if next_button.is_disabled():
                return list(found.values())
            previous = signature
            next_button.click(force=True)
            for _ in range(100):
                self.page.wait_for_timeout(100)
                current = tuple((row.pan, row.certificate_number) for row in self._rows())
                if current != previous:
                    break
            else:
                raise ElementNotFoundError("Child Certificate page did not advance.")
            self.page_number += 1

    def _go_to_page(self, target_page: int) -> None:
        while self.page_number > target_page:
            previous = tuple(row.certificate_number for row in self._rows())
            button = self._previous_button()
            if button.is_disabled():
                raise ElementNotFoundError("Cannot return to the required Child Certificate page.")
            button.click(force=True)
            self.page.wait_for_timeout(750)
            if tuple(row.certificate_number for row in self._rows()) == previous:
                raise ElementNotFoundError("Child Certificate Previous page did not advance.")
            self.page_number -= 1
        while self.page_number < target_page:
            previous = tuple(row.certificate_number for row in self._rows())
            button = self._next_button()
            if button.is_disabled():
                raise ElementNotFoundError("Required Child Certificate page is unavailable.")
            button.click(force=True)
            self.page.wait_for_timeout(750)
            if tuple(row.certificate_number for row in self._rows()) == previous:
                raise ElementNotFoundError("Child Certificate Next page did not advance.")
            self.page_number += 1

    def select(self, row: PortalCertificateRow) -> None:
        self._alive()
        if self.selected is not None:
            previous = self.selected
            self._go_to_page(previous.page_number)
            self._toggle_row_checkbox(previous)
            self.selected = None
        self._go_to_page(row.page_number)
        self._toggle_row_checkbox(row)
        expect(self.page.get_by_text(
            re.compile(r"1\s+of\s+\d+\s+Selected")
        ).first).to_be_visible(
            timeout=ELEMENT_WAIT_TIMEOUT_MS
        )
        self.selected = row
        logger.info("Selected Child Certificate %s (%s).", row.certificate_number, row.pan)

    def _toggle_row_checkbox(self, row: PortalCertificateRow) -> None:
        """Click the checkbox aligned with a certificate row."""
        cert = self.page.get_by_text(
            re.compile(
                r"^" + re.escape(row.certificate_number)
                + r"(?:\s+" + re.escape(row.certificate_number) + r")?$"
            ),
            exact=False,
        ).last
        expect(cert).to_be_visible(timeout=ELEMENT_WAIT_TIMEOUT_MS)
        cert_box = cert.bounding_box()
        if not cert_box:
            raise ElementNotFoundError(f"Child Certificate row has no bounds: {row.certificate_number}")

        checkboxes = self.table.get_by_role("button", name="icon", exact=True)
        target = None
        target_distance = float("inf")
        cert_y = cert_box["y"] + cert_box["height"] / 2
        for checkbox in checkboxes.all():
            box = checkbox.bounding_box()
            if not box:
                continue
            distance = abs((box["y"] + box["height"] / 2) - cert_y)
            if distance < target_distance:
                target = checkbox
                target_distance = distance
        if target is None or target_distance > 10:
            raise ElementNotFoundError(f"Checkbox not found for {row.certificate_number}")
        target.click(force=True)

    def submit(self) -> None:
        if self.selected is None:
            raise ElementNotFoundError("No Child Certificate selected for initiation.")
        button = self.page.get_by_role(
            "button", name=re.compile(r"Initiate download button", re.I)
        )
        expect(button).to_have_count(1, timeout=ELEMENT_WAIT_TIMEOUT_MS)
        expect(button).to_be_enabled(timeout=ELEMENT_WAIT_TIMEOUT_MS)
        self.initiated_at = datetime.now()
        button.click(force=True)
        self.page.wait_for_timeout(3000)
        logger.info("Initiated Child Certificate %s.", self.selected.certificate_number)

    @property
    def initiated_dialog(self) -> Locator:
        return self.page.get_by_role("dialog")

    def open_initiated_downloads(self) -> None:
        """Open the Flutter 'All Initiated Downloads' modal."""
        name = re.compile(r"View\s+All\s+Initiated\s+Download", re.I)
        controls = self.page.get_by_role("button", name=name)
        if controls.count() == 0:
            controls = self.page.get_by_role("link", name=name)
        if controls.count() == 0:
            controls = self.page.get_by_text(name)
        expect(controls.last).to_be_visible(timeout=ELEMENT_WAIT_TIMEOUT_MS)
        controls.last.click(force=True)
        expect(self.initiated_dialog).to_be_visible(timeout=ELEMENT_WAIT_TIMEOUT_MS)
        expect(
            self.initiated_dialog.get_by_text("All Initiated Downloads", exact=True)
        ).to_be_visible(timeout=ELEMENT_WAIT_TIMEOUT_MS)
        logger.info("Opened All Initiated Downloads.")

    def _matching_modal_card(self) -> Locator | None:
        cards = self.initiated_dialog.locator(
            "flt-semantics[aria-label*='Date & Time of Initiating Download']"
        )
        if cards.count() == 0:
            return None
        if self.initiated_at is None:
            return cards.first

        # The modal can lag behind initiation. Wait for a card whose displayed
        # date/minute matches the current request, then use the first such card.
        pattern = re.compile(
            r"(\d{1,2}/\d{1,2}/\d{4})\s+at\s+(\d{1,2}:\d{2}\s+[AP]M)",
            re.IGNORECASE,
        )
        matching: list[Locator] = []
        for card in cards.all():
            label = " ".join([
                card.get_attribute("aria-label") or "",
                card.inner_text(),
            ])
            match = pattern.search(label)
            if match:
                try:
                    card_time = datetime.strptime(
                        f"{match.group(1)} {match.group(2).upper()}",
                        "%d/%m/%Y %I:%M %p",
                    )
                except ValueError:
                    continue
                delta = abs((card_time - self.initiated_at).total_seconds())
                if delta <= 90:
                    matching.append(card)
        if not matching:
            return None
        # The modal is newest-first. After the one-minute publish delay, the
        # first matching card is the current request. Prefer a card that has
        # the real Download action over expired Re-Initiate entries.
        for card in matching:
            if card.get_by_role("button", name="Download", exact=True).count() == 1:
                return card
        return matching[0]

    def _refresh_initiated_dialog(self) -> None:
        """Refresh page one of the modal without leaving the initiated view."""
        dialog = self.initiated_dialog
        next_buttons = dialog.get_by_role("button", name="Next", exact=True)
        if next_buttons.count() and not next_buttons.last.is_disabled():
            next_buttons.last.click(force=True)
            self.page.wait_for_timeout(750)
            previous = dialog.get_by_role("button", name="Previous", exact=True)
            expect(previous.last).to_be_enabled(timeout=ELEMENT_WAIT_TIMEOUT_MS)
            previous.last.click(force=True)
            self.page.wait_for_timeout(750)
            return

        close = dialog.get_by_role("button", name=re.compile(r"Close", re.I))
        close.last.click(force=True)
        expect(dialog).to_be_hidden(timeout=ELEMENT_WAIT_TIMEOUT_MS)
        self.open_initiated_downloads()

    def _close_initiated_dialog(self) -> None:
        dialog = self.initiated_dialog
        if not dialog.is_visible():
            return
        close = dialog.get_by_role("button", name=re.compile(r"Close", re.I))
        if close.count():
            close.last.click(force=True)
            expect(dialog).to_be_hidden(timeout=ELEMENT_WAIT_TIMEOUT_MS)

    def can_resume(self, initiated_at: str) -> bool:
        """Confirm that the visible ready request matches a tracked initiation minute."""
        try:
            initiated = datetime.fromisoformat(initiated_at)
        except (TypeError, ValueError):
            return False
        cards = self.page.locator("flt-semantics[role='group']").filter(
            has_text=re.compile(r"Date\s*&\s*Time of initiating Download", re.I)
        )
        if cards.count() == 0:
            return False
        label = " ".join([
            cards.first.inner_text(), cards.first.get_attribute("aria-label") or ""
        ])
        match = re.search(
            r"(\d{1,2}/\d{1,2}/\d{4})\s+at\s+(\d{1,2}:\d{2}\s+[AP]M)",
            label,
            re.IGNORECASE,
        )
        if not match:
            return False
        try:
            card_time = datetime.strptime(
                f"{match.group(1)} {match.group(2).upper()}", "%d/%m/%Y %I:%M %p"
            )
        except ValueError:
            return False
        return (
            abs((card_time - initiated).total_seconds()) <= 90
            and cards.first.get_by_role("button", name="Download", exact=True).count() == 1
        )

    def download(self, initiation_time: datetime | None = None) -> Path:
        """Poll and download the timestamp-matched request from the modal."""
        if initiation_time is not None:
            self.initiated_at = initiation_time
        expect(self.initiated_dialog).to_be_visible(timeout=ELEMENT_WAIT_TIMEOUT_MS)
        if self.initiated_at is not None:
            elapsed = (datetime.now() - self.initiated_at).total_seconds()
            # Give TRACES a full minute to publish each newly initiated request.
            # This intentionally favors reliability over batch speed.
            settle_seconds = 60
            if elapsed < settle_seconds:
                logger.info(
                    "Waiting 60 seconds for the Child Certificate request to publish."
                )
                self.page.wait_for_timeout(int((settle_seconds - elapsed) * 1000))
            # Reopen after the portal has had time to publish the new request.
            self._refresh_initiated_dialog()
        for attempt in range(1, MAX_REFRESH_ATTEMPTS + 1):
            self._alive()
            card = self._matching_modal_card()
            if card is None:
                logger.info(
                    "Waiting for the new Child Certificate request to appear in initiated downloads (%d/%d).",
                    attempt,
                    MAX_REFRESH_ATTEMPTS,
                )
                self.page.wait_for_timeout(REFRESH_INTERVAL_SECONDS * 1000)
                self._refresh_initiated_dialog()
                continue
            buttons = card.get_by_role("button", name="Download", exact=True)
            if buttons.count() and buttons.first.is_enabled():
                with self.page.expect_download(timeout=DOWNLOAD_READY_TIMEOUT_MS) as info:
                    buttons.first.click(force=True)
                download: Download = info.value
                name = download.suggested_filename or (
                    f"ChildCertificate_{datetime.now():%Y%m%d%H%M%S}.pdf"
                )
                destination = temp_download_path(name)
                download.save_as(str(destination))
                self._close_initiated_dialog()
                logger.info("Downloaded Child Certificate: %s", destination.name)
                return destination

            logger.info(
                "Waiting for Child Certificate download (%d/%d).", attempt, MAX_REFRESH_ATTEMPTS
            )
            self.page.wait_for_timeout(REFRESH_INTERVAL_SECONDS * 1000)
            self._refresh_initiated_dialog()
        self._close_initiated_dialog()
        raise ElementNotFoundError("Child Certificate download did not become ready.")
