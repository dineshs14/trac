"""
TRACES Automation — Child Certificate Downloader

Workflow:
    1. Navigate to Downloads → Child Certificate(s) issued under Rule No. 213(9)
    2. Select Tax Year and click Search
    3. Parse the child certificate table (paginated, dynamic)
    4. For each new certificate: select → initiate → identify correct download → download
    5. Parse PDF → validate → rename → move → update trackers
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import Page, Download, Error as PlaywrightError

from config import (
    CERT_TYPE_CHILD,
    SELECTORS,
    CHILD_CERT_DIR,
    MAX_REFRESH_ATTEMPTS,
    REFRESH_INTERVAL_SECONDS,
    ELEMENT_WAIT_TIMEOUT_MS,
    DOWNLOAD_READY_TIMEOUT_MS,
    STATUS_DISCOVERED,
    STATUS_INITIATED,
    STATUS_DOWNLOADED,
    STATUS_EXTRACTED,
    STATUS_VALIDATED,
    STATUS_MASTER_UPDATED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_VALIDATION_FAILED,
)
from automation.portal_utils import (
    assert_session_alive,
    extract_table_rows,
    has_next_page,
    click_next_page,
    wait_for_element,
    SessionLostError,
    ElementNotFoundError,
    is_flutter_portal,
)
from automation.navigation import navigate_to_download_page, setup_child_certificate_download
from data.tracker_store import TrackerStore
from data.master_tracker import MasterTracker
from data.process_tracker import ProcessTracker, FailedRecordsTracker
from data.models import PortalCertificateRow, CertificateRecord, RunSummary
from extraction.child_pdf_parser import parse_child_pdf
from extraction.validators import validate_extracted_data
from utils.naming import build_unique_key, child_cert_filename, derive_short_certificate_number
from utils.file_utils import ensure_fy_subdirectory, safe_move, temp_download_path
from utils.logger import logger


# Column names for child certificate table — VERIFY_WITH_INSPECTOR
CHILD_TABLE_COLUMNS = [
    "checkbox",
    "child_certificate_number",
    "tax_year",
    "section_code",
    "deductee_pan",
    "child_certificate_amount",
    "valid_from",
    "valid_to",
    "remarks",
]


class ChildCertificateDownloader:
    """Orchestrates the Child Certificate download workflow."""

    def __init__(
        self,
        page: Page,
        fy: str,
        db: TrackerStore,
        master: MasterTracker,
        process_tracker: ProcessTracker,
        failed_tracker: FailedRecordsTracker,
    ) -> None:
        self.page = page
        self.fy = fy
        self.db = db
        self.master = master
        self.process_tracker = process_tracker
        self.failed_tracker = failed_tracker
        self.summary = RunSummary(task="child-download", financial_year=fy)
        self.fy_dir = ensure_fy_subdirectory(CHILD_CERT_DIR, fy)
        from automation.flutter_child_download import FlutterChildDownload
        self.flutter = FlutterChildDownload(page, fy)

    def run(self) -> RunSummary:
        """Execute the full Child Certificate download workflow."""
        self.summary.run_start = datetime.now()
        logger.info("=" * 60)
        logger.info("  CHILD CERTIFICATE DOWNLOAD — FY %s", self.fy)
        logger.info("=" * 60)

        try:
            if not is_flutter_portal(self.page):
                navigate_to_download_page(self.page)
            setup_child_certificate_download(self.page, self.fy)

            # Wait for child certificate table
            self._wait_for_table()

            # Discover all child certificates across all pages
            all_rows = self._discover_all_certificates()
            self.summary.portal_records_discovered = len(all_rows)
            logger.info("Total child certificates discovered: %d", len(all_rows))

            # Process each certificate
            for row in all_rows:
                if self.page.is_closed():
                    logger.error("Browser closed. Stopping before processing more Child Certificates.")
                    break
                try:
                    assert_session_alive(self.page)
                    self._process_single_certificate(row)
                except SessionLostError:
                    logger.error("Session lost. Stopping gracefully.")
                    break
                except Exception as exc:
                    logger.error("Error processing child cert %s: %s",
                                 row.certificate_number, exc)
                    self.summary.failed += 1

        except SessionLostError:
            logger.error("Session expired before processing could begin.")
            self.summary.failed += 1
        except Exception as exc:
            logger.error("Child certificate download failed: %s", exc, exc_info=True)
            self.summary.failed += 1

        self.summary.run_end = datetime.now()
        logger.info(self.summary.print_summary())
        return self.summary

    # ──────────────────────────────────────────

    def _wait_for_table(self) -> None:
        """Wait for the child certificate result table to appear."""
        if is_flutter_portal(self.page):
            logger.info("Flutter CPCTDS 2.0 detected — waiting for Child Certificate table…")
            self.flutter.wait_ready()
            return

        logger.info("Waiting for child certificate table…")
        try:
            wait_for_element(self.page, SELECTORS["child_cert_table"],
                             timeout_ms=ELEMENT_WAIT_TIMEOUT_MS)
        except ElementNotFoundError:
            # Fallback: look for any table
            wait_for_element(self.page, "table", timeout_ms=ELEMENT_WAIT_TIMEOUT_MS)
        logger.info("✓ Child certificate table visible.")

    def _discover_all_certificates(self) -> List[PortalCertificateRow]:
        """Iterate through all pages and collect child certificate rows."""
        if is_flutter_portal(self.page):
            return self.flutter.discover()

        all_rows: List[PortalCertificateRow] = []
        page_num = 1

        while True:
            logger.info("Parsing child cert page %d…", page_num)
            rows_on_page = self._parse_current_page(page_num)
            all_rows.extend(rows_on_page)

            # Use generic next-page detection
            next_sel = SELECTORS.get("popup_next_page_btn")
            if not has_next_page(self.page, next_sel):
                break
            if not click_next_page(self.page, next_sel):
                break
            page_num += 1

        return all_rows

    def _parse_current_page(self, page_num: int) -> List[PortalCertificateRow]:
        """Extract rows from the currently visible child certificate table page."""
        rows: List[PortalCertificateRow] = []
        raw_rows = extract_table_rows(
            self.page,
            SELECTORS["child_cert_table_rows"],
            CHILD_TABLE_COLUMNS,
        )

        for idx, raw in enumerate(raw_rows):
            cert_no = raw.get("child_certificate_number", "").strip()
            if not cert_no:
                continue

            rows.append(PortalCertificateRow(
                certificate_number=cert_no,
                section_code=raw.get("section_code", "").strip(),
                deductee_pan=raw.get("deductee_pan", "").strip(),
                valid_from=raw.get("valid_from", "").strip(),
                valid_to=raw.get("valid_to", "").strip(),
                remarks=raw.get("remarks", "").strip(),
                page_number=page_num,
                row_index=idx,
            ))

        return rows

    def _process_single_certificate(self, row: PortalCertificateRow) -> None:
        """Process a single child certificate through the full lifecycle."""
        unique_key = build_unique_key(CERT_TYPE_CHILD, self.fy, row.pan, row.certificate_number)

        # Check if already completed
        if self.db.is_completed(unique_key):
            logger.debug("Skipping (completed): %s", unique_key)
            self.summary.already_completed += 1
            self.summary.skipped_duplicates += 1
            return

        # Register as discovered
        inserted = self.db.upsert_discovered(
            unique_key=unique_key,
            certificate_type=CERT_TYPE_CHILD,
            financial_year=self.fy,
            pan=row.pan,
            certificate_number=row.certificate_number,
            portal_page=row.page_number,
        )
        if inserted:
            self.summary.new_records += 1

        initiation_time = datetime.now()
        tracker_row = self.db.get_by_key(unique_key) or {}
        resume_ready = (
            is_flutter_portal(self.page)
            and bool(tracker_row.get("Initiated_At"))
            and self.flutter.can_resume(str(tracker_row.get("Initiated_At")))
        )

        if resume_ready:
            try:
                initiation_time = datetime.fromisoformat(str(tracker_row["Initiated_At"]))
            except (TypeError, ValueError, KeyError):
                initiation_time = datetime.now()
            logger.info("Resuming ready Child Certificate request: %s", row.certificate_number)
        else:
            # Select the specific certificate row
            try:
                self._select_child_cert_row(row)
            except Exception as exc:
                self._record_failure(unique_key, row, f"Selection failed: {exc}")
                return

            # Initiate download
            try:
                self._initiate_child_download()
                if is_flutter_portal(self.page) and self.flutter.initiated_at:
                    initiation_time = self.flutter.initiated_at
                self.db.update_status(unique_key, STATUS_INITIATED,
                                      initiated_at=initiation_time.isoformat())
                self.summary.downloads_initiated += 1
            except Exception as exc:
                self._record_failure(unique_key, row, f"Initiate failed: {exc}")
                return

        # Both new and resumed requests are downloaded from the initiated view.
        try:
            self._open_initiated_downloads()
        except Exception as exc:
            self._record_failure(unique_key, row, f"Cannot view initiated downloads: {exc}")
            return

        # Wait and download the correct PDF
        temp_path: Optional[Path] = None
        try:
            temp_path = self._wait_and_download_correct(initiation_time)
            self.db.update_status(
                unique_key, STATUS_DOWNLOADED,
                downloaded_at=datetime.now().isoformat(),
                original_filename=temp_path.name,
            )
        except Exception as exc:
            self._record_failure(unique_key, row, f"Download failed: {exc}")
            return

        # Parse PDF
        try:
            cert_record = parse_child_pdf(temp_path, self.fy)
            cert_record.certificate_type = CERT_TYPE_CHILD
            self.db.update_status(unique_key, STATUS_EXTRACTED,
                                  extraction_status="SUCCESS")
        except Exception as exc:
            self._record_failure(unique_key, row, f"PDF parse failed: {exc}")
            return

        # Validate
        try:
            is_valid, errors = validate_extracted_data(cert_record, row, self.fy)
            if not is_valid:
                err_msg = "; ".join(errors)
                self.db.update_status(unique_key, STATUS_VALIDATION_FAILED,
                                      error_message=err_msg)
                self.summary.validation_failed += 1
                return
            self.db.update_status(unique_key, STATUS_VALIDATED)
        except Exception as exc:
            self._record_failure(unique_key, row, f"Validation error: {exc}")
            return

        # Rename and move
        try:
            final_name = child_cert_filename(
                cert_record.pan,
                cert_record.vendor_name,
                cert_record.certificate_number,
            )
            final_path = self.fy_dir / final_name

            if final_path.exists():
                logger.info("File exists (same cert): %s — reusing.", final_name)
                if temp_path and temp_path.exists():
                    temp_path.unlink()
            else:
                safe_move(temp_path, final_path)

            cert_record.pdf_path = str(final_path)
            cert_record.certificate_short_number = derive_short_certificate_number(
                cert_record.certificate_number
            )
            self.db.update_status(unique_key, STATUS_VALIDATED,
                                  final_filename=final_name, pdf_path=str(final_path))
        except Exception as exc:
            self._record_failure(unique_key, row, f"Rename/move failed: {exc}")
            return

        # Update Master Tracker
        try:
            cert_record.processing_status = STATUS_COMPLETED
            cert_record.financial_year = self.fy
            cert_record.date_received = datetime.now().strftime("%Y-%m-%d")
            action = self.master.upsert_record(cert_record)
            self.db.update_status(unique_key, STATUS_MASTER_UPDATED,
                                  master_update_status="SUCCESS")
            if action == "ADDED":
                self.summary.master_rows_added += 1
            else:
                self.summary.master_rows_updated += 1
        except Exception as exc:
            self._record_failure(unique_key, row, f"Master update failed: {exc}")
            return

        # Mark COMPLETED
        self.db.update_status(unique_key, STATUS_COMPLETED)
        self.summary.downloads_successful += 1
        logger.info("✓ Completed child cert: %s", unique_key)

        self.process_tracker.update_record(unique_key, {
            "Certificate_Type": CERT_TYPE_CHILD,
            "Financial_Year": self.fy,
            "PAN": row.pan,
            "Certificate_Number": row.certificate_number,
            "Status": STATUS_COMPLETED,
        })

    # ──────────────────────────────────────────
    # Portal Interaction Helpers
    # ──────────────────────────────────────────

    def _select_child_cert_row(self, row: PortalCertificateRow) -> None:
        """Find and select the checkbox for a child certificate row."""
        cert_no = row.certificate_number
        if is_flutter_portal(self.page):
            self.flutter.select(row)
            return

        rows = self.page.locator(SELECTORS["child_cert_table_rows"])
        count = rows.count()

        # Uncheck all first
        try:
            checked = self.page.locator(
                f'{SELECTORS["child_cert_table"]} input[type="checkbox"]:checked'
            )
            for i in range(checked.count()):
                checked.nth(i).uncheck()
        except PlaywrightError:
            pass

        for i in range(count):
            row_el = rows.nth(i)
            row_text = row_el.inner_text()
            if cert_no in row_text:
                checkbox = row_el.locator('input[type="checkbox"]')
                if checkbox.count() > 0:
                    checkbox.first.check()
                    self.page.wait_for_timeout(500)
                    logger.debug("Selected child cert row: %s", cert_no)
                    return

        raise ElementNotFoundError(f"Child certificate row not found: {cert_no}")

    def _initiate_child_download(self) -> None:
        """Click Initiate Download for the selected child certificate."""
        if is_flutter_portal(self.page):
            self.flutter.submit()
            return

        btn = self.page.locator(SELECTORS["download_initiate_btn"])
        if btn.count() == 0:
            btn = self.page.get_by_role("button", name="Initiate Download")
        btn.first.click()
        self.page.wait_for_timeout(3000)
        logger.info("Child download initiated.")

    def _open_initiated_downloads(self) -> None:
        """Click 'View All Initiated Downloads' to see the download queue."""
        if is_flutter_portal(self.page):
            self.flutter.open_initiated_downloads()
            return

        btn = self.page.locator(SELECTORS["child_view_downloads_btn"])
        if btn.count() == 0:
            btn = self.page.get_by_role("button", name="View All Initiated Downloads")
        if btn.count() == 0:
            btn = self.page.get_by_text("View All Initiated Downloads")
        btn.first.click()
        self.page.wait_for_timeout(3000)
        logger.info("Opened initiated downloads view.")

    def _wait_and_download_correct(self, initiation_time: datetime) -> Path:
        """Wait for the correct download to become ready and download it.

        Identifies the correct initiated request by:
            1. Initiation time proximity
            2. Most recent entry
            3. Available metadata matching

        IMPORTANT: Does NOT click the first Download button blindly.
        """
        logger.info("Waiting for child cert download to become ready…")
        if is_flutter_portal(self.page):
            return self.flutter.download(initiation_time)

        for attempt in range(1, MAX_REFRESH_ATTEMPTS + 1):
            try:
                # Look for download links in the initiated downloads table
                download_links = self.page.locator(
                    f'{SELECTORS["initiated_downloads_section"]} {SELECTORS["initiated_download_link"]}'
                )

                if download_links.count() > 0:
                    # Find the most recent download link
                    # Strategy: the latest initiated download should be at top or bottom
                    # Check each row for time proximity to our initiation time
                    best_link = self._find_matching_download_link(
                        download_links, initiation_time
                    )
                    if best_link is not None:
                        # Download the PDF
                        with self.page.expect_download(
                            timeout=DOWNLOAD_READY_TIMEOUT_MS
                        ) as download_info:
                            best_link.click()

                        download: Download = download_info.value
                        original_name = download.suggested_filename or \
                            f"child_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
                        temp_file = temp_download_path(original_name)
                        download.save_as(str(temp_file))
                        logger.info("Downloaded child cert: %s", temp_file.name)
                        return temp_file

            except PlaywrightError:
                pass

            # Click Refresh
            try:
                refresh_btn = self.page.locator(SELECTORS["initiated_refresh_btn"])
                if refresh_btn.count() > 0:
                    refresh_btn.first.click()
            except PlaywrightError:
                pass

            time.sleep(REFRESH_INTERVAL_SECONDS)

            if attempt % 5 == 0:
                logger.info("  Still waiting for child cert… (attempt %d/%d)",
                             attempt, MAX_REFRESH_ATTEMPTS)

        raise TimeoutError("Child certificate download not ready within timeout")

    def _find_matching_download_link(
        self, download_links, initiation_time: datetime
    ):
        """Identify the correct download link from potentially many historical entries.

        Strategy:
            - Scan the initiated downloads table rows
            - Look for the row whose initiation time is closest to our recorded time
            - Fall back to the most recent (first/last) available download link
        """
        section = self.page.locator(SELECTORS["initiated_downloads_section"])
        if section.count() == 0:
            # Fallback: just use the first visible download link
            if download_links.count() > 0:
                return download_links.first
            return None

        # Try to find rows in the initiated downloads table
        rows = section.locator("tr")
        row_count = rows.count()

        # Look for a row containing our approximate initiation time
        init_date_str = initiation_time.strftime("%d/%m/%Y")
        init_date_str_alt = initiation_time.strftime("%d-%m-%Y")

        for i in range(row_count):
            row_el = rows.nth(i)
            row_text = row_el.inner_text()

            # Check if this row contains today's date and has a download link
            if (init_date_str in row_text or init_date_str_alt in row_text):
                link = row_el.locator('a:has-text("Download")')
                if link.count() > 0 and link.first.is_visible():
                    logger.debug("Found matching download by date in row %d", i)
                    return link.first

        # Fallback: use the first available download link
        if download_links.count() > 0:
            logger.debug("Using first available download link (fallback)")
            return download_links.first

        return None

    def _record_failure(
        self,
        unique_key: str,
        row: PortalCertificateRow,
        error_msg: str,
    ) -> None:
        """Record a processing failure."""
        logger.error("FAILED [%s]: %s", unique_key, error_msg)
        self.db.mark_failed(unique_key, error_msg)
        self.db.increment_retry(unique_key, error_msg)
        self.summary.failed += 1

        self.failed_tracker.add_failure({
            "Unique_Key": unique_key,
            "Certificate_Type": CERT_TYPE_CHILD,
            "Financial_Year": self.fy,
            "PAN": row.pan,
            "Certificate_Number": row.certificate_number,
            "Status": STATUS_FAILED,
            "Error_Message": error_msg,
        })
