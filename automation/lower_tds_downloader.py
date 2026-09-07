"""
TRACES Automation — Lower TDS Certificate Downloader

Complete lifecycle:
    1. Open download popup (paginated table of certificates)
    2. Iterate ALL pages dynamically
    3. For each certificate row: check tracker → skip if completed → select → initiate → wait → download
    4. Save temp PDF → parse → validate → rename → move → update tracker + Master Excel
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from playwright.sync_api import Page, Download, Error as PlaywrightError, TimeoutError as PwTimeout

from config import (
    CERT_TYPE_LOWER_TDS,
    SELECTORS,
    LOWER_TDS_DIR,
    MAX_RETRIES,
    REFRESH_INTERVAL_SECONDS,
    MAX_REFRESH_ATTEMPTS,
    ELEMENT_WAIT_TIMEOUT_MS,
    DOWNLOAD_READY_TIMEOUT_MS,
    STATUS_DISCOVERED,
    STATUS_INITIATED,
    STATUS_READY,
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
    detect_total_pages,
    wait_for_element,
    SessionLostError,
    ElementNotFoundError,
    is_flutter_portal,
    enable_flutter_semantics,
)
from automation.navigation import navigate_to_download_page, setup_lower_tds_download
from data.tracker_store import TrackerStore
from data.master_tracker import MasterTracker
from data.process_tracker import ProcessTracker, FailedRecordsTracker
from data.models import PortalCertificateRow, CertificateRecord, DownloadRequest, RunSummary
from extraction.lower_tds_pdf_parser import parse_lower_tds_pdf
from extraction.validators import validate_extracted_data
from utils.naming import build_unique_key, lower_tds_filename, derive_short_certificate_number
from utils.file_utils import ensure_fy_subdirectory, safe_move, file_exists_for_key, temp_download_path
from utils.logger import logger


# ── Column names expected in the popup table rows ──
# These are positional guesses — VERIFY_WITH_INSPECTOR
POPUP_COLUMNS = [
    "checkbox",            # col 0 — checkbox cell
    "certificate_number",  # col 1
    "section_code",        # col 2
    "deductee_pan",        # col 3
    "valid_from",          # col 4
    "valid_to",            # col 5
    "remarks",             # col 6
]


class LowerTDSDownloader:
    """Orchestrates the Lower TDS certificate download workflow."""

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
        self.summary = RunSummary(task="lower-download", financial_year=fy)
        self.fy_dir = ensure_fy_subdirectory(LOWER_TDS_DIR, fy)
        from automation.flutter_lower_download import FlutterLowerDownload
        self.flutter = FlutterLowerDownload(page, fy)

    def run(self) -> RunSummary:
        """Execute the full Lower TDS download workflow.

        Returns:
            RunSummary with aggregated statistics.
        """
        self.summary.run_start = datetime.now()
        logger.info("=" * 60)
        logger.info("  LOWER TDS DOWNLOAD — FY %s", self.fy)
        logger.info("=" * 60)

        try:
            # Step 1: Navigate and open the popup
            navigate_to_download_page(self.page)
            setup_lower_tds_download(self.page, self.fy)

            # Step 2: Wait for the popup/table to appear
            self._wait_for_popup()

            # Step 3: Discover all certificates across all pages
            all_rows = self._discover_all_certificates()
            self.summary.portal_records_discovered = len(all_rows)
            logger.info("Total certificates discovered: %d", len(all_rows))

            # Step 4: Process each certificate
            for row in all_rows:
                if self.page.is_closed():
                    logger.error("Browser closed. Stopping before processing more certificates.")
                    break
                try:
                    assert_session_alive(self.page)
                    self._process_single_certificate(row)
                except SessionLostError:
                    logger.error("Session lost during processing. Stopping gracefully.")
                    break
                except Exception as exc:
                    logger.error("Error processing %s: %s", row.certificate_number, exc)
                    self.summary.failed += 1

        except SessionLostError:
            logger.error("Session expired. Please log in and retry.")
        except Exception as exc:
            self.summary.failed += 1
            logger.error("Lower TDS download failed: %s", exc, exc_info=True)

        self.summary.run_end = datetime.now()
        logger.info(self.summary.print_summary())
        return self.summary

    # ──────────────────────────────────────────

    def _wait_for_popup(self) -> None:
        """Wait for the certificate popup/table or Flutter cards to become visible."""
        if is_flutter_portal(self.page):
            self.flutter.open()
            return

        logger.info("Waiting for certificate popup table…")
        try:
            wait_for_element(self.page, SELECTORS["popup_table"], timeout_ms=ELEMENT_WAIT_TIMEOUT_MS)
        except ElementNotFoundError:
            # Fallback: look for any visible table inside a modal
            wait_for_element(self.page, SELECTORS["popup_modal"], timeout_ms=ELEMENT_WAIT_TIMEOUT_MS)
        logger.info("✓ Certificate popup table visible.")

    def _discover_all_certificates(self) -> List[PortalCertificateRow]:
        """Iterate through ALL pages of the popup table or Flutter cards and collect certificate rows.

        Does NOT hardcode page count — iterates until Next is disabled.
        """
        if is_flutter_portal(self.page):
            return self._discover_flutter_certificates()

        all_rows: List[PortalCertificateRow] = []
        page_num = 1

        # Detect approximate page count for logging (not used for loop control)
        approx_pages = detect_total_pages(self.page)
        logger.info("Approximate total pages: %d (will iterate dynamically)", approx_pages)

        while True:
            logger.info("Parsing page %d…", page_num)
            rows_on_page = self._parse_current_page(page_num)
            all_rows.extend(rows_on_page)
            logger.debug("  Page %d: %d rows extracted.", page_num, len(rows_on_page))

            if not has_next_page(self.page, SELECTORS.get("popup_next_page_btn")):
                logger.info("No more pages. Total rows: %d", len(all_rows))
                break

            if not click_next_page(self.page, SELECTORS.get("popup_next_page_btn")):
                logger.warning("Failed to navigate to next page. Stopping pagination.")
                break

            page_num += 1

        return all_rows

    def _discover_flutter_certificates(self) -> List[PortalCertificateRow]:
        """Read real certificate rows from the paginated Form 128 popup."""
        return self.flutter.discover()

    def _parse_current_page(self, page_num: int) -> List[PortalCertificateRow]:
        """Extract PortalCertificateRow objects from the currently visible table page."""
        rows: List[PortalCertificateRow] = []
        raw_rows = extract_table_rows(
            self.page,
            SELECTORS["popup_table_rows"],
            POPUP_COLUMNS,
        )

        for idx, raw in enumerate(raw_rows):
            cert_no = raw.get("certificate_number", "").strip()
            if not cert_no:
                continue  # Skip empty/header rows

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
        """Process one certificate: check → select → download → parse → rename → update."""
        unique_key = build_unique_key(CERT_TYPE_LOWER_TDS, self.fy, row.pan, row.certificate_number)

        # ── Check if already completed ──
        if self.db.is_completed(unique_key):
            logger.debug("Skipping (completed): %s", unique_key)
            self.summary.already_completed += 1
            self.summary.skipped_duplicates += 1
            return

        tracked = self.db.get_by_key(unique_key)
        if tracked and tracked.get("status") in (
            STATUS_DOWNLOADED, STATUS_EXTRACTED, STATUS_VALIDATED, STATUS_MASTER_UPDATED, STATUS_FAILED
        ):
            saved_path = Path(tracked.get("pdf_path") or "")
            if saved_path.is_file():
                logger.info("Resuming saved PDF for %s.", row.certificate_number)
                self._finish_downloaded_certificate(row, unique_key, saved_path)
                return

        # ── Check if PDF already exists ──
        expected_name = lower_tds_filename(row.pan, "", row.certificate_number, self.fy)
        existing = file_exists_for_key(LOWER_TDS_DIR, self.fy, expected_name)
        if existing:
            db_row = self.db.get_by_key(unique_key)
            if db_row and db_row["status"] in (STATUS_COMPLETED, STATUS_MASTER_UPDATED):
                logger.debug("Skipping (file exists + tracked): %s", unique_key)
                self.summary.already_completed += 1
                return

        # ── Register as discovered ──
        self.db.upsert_discovered(
            unique_key=unique_key,
            certificate_type=CERT_TYPE_LOWER_TDS,
            financial_year=self.fy,
            pan=row.pan,
            certificate_number=row.certificate_number,
            portal_page=row.page_number,
        )
        self.summary.new_records += 1

        # ── Navigate back to the correct page and select the row ──
        try:
            self._navigate_to_page_and_select(row)
        except Exception as exc:
            self._record_failure(unique_key, row, f"Selection failed: {exc}")
            return

        # ── Initiate download ──
        try:
            self._click_popup_initiate_download()
            self.db.update_status(unique_key, STATUS_INITIATED,
                                  initiated_at=datetime.now().isoformat(),
                                  arn_request_number=self.flutter.request_arn if is_flutter_portal(self.page) else "")
            self.summary.downloads_initiated += 1
        except Exception as exc:
            self._record_failure(unique_key, row, f"Initiate failed: {exc}")
            return

        # ── Wait for download to become ready ──
        try:
            self._wait_for_download_ready()
            self.db.update_status(unique_key, STATUS_READY)
        except Exception as exc:
            self._record_failure(unique_key, row, f"Download not ready: {exc}")
            return

        # ── Download the PDF ──
        temp_path: Optional[Path] = None
        try:
            temp_path = self._download_pdf()
            self.db.update_status(
                unique_key, STATUS_DOWNLOADED,
                downloaded_at=datetime.now().isoformat(),
                original_filename=temp_path.name,
                pdf_path=str(temp_path),
            )
        except Exception as exc:
            self._record_failure(unique_key, row, f"Download failed: {exc}")
            return

        self._finish_downloaded_certificate(row, unique_key, temp_path)

    def _finish_downloaded_certificate(self, row, unique_key: str, temp_path: Path) -> None:
        """Validate, rename and track a downloaded PDF, including resumed files."""
        # ── Parse PDF ──
        try:
            cert_record = parse_lower_tds_pdf(temp_path, self.fy)
            cert_record.certificate_type = CERT_TYPE_LOWER_TDS
            self.db.update_status(unique_key, STATUS_EXTRACTED,
                                  extraction_status="SUCCESS")
        except Exception as exc:
            self._record_failure(unique_key, row, f"PDF parse failed: {exc}")
            return

        # ── Validate extracted data against portal row ──
        try:
            is_valid, errors = validate_extracted_data(cert_record, row, self.fy)
            if not is_valid:
                err_msg = "; ".join(errors)
                logger.warning("Validation failed for %s: %s", unique_key, err_msg)
                self.db.update_status(unique_key, STATUS_VALIDATION_FAILED,
                                      error_message=err_msg)
                self.summary.validation_failed += 1
                return
            self.db.update_status(unique_key, STATUS_VALIDATED)
        except Exception as exc:
            self._record_failure(unique_key, row, f"Validation error: {exc}")
            return

        # ── Rename and move PDF ──
        try:
            final_name = lower_tds_filename(
                cert_record.pan,
                cert_record.vendor_name,
                cert_record.certificate_number,
                self.fy,
            )
            final_path = self.fy_dir / final_name

            # Check for collision
            if final_path.exists():
                logger.info("File already exists (same cert): %s — reusing.", final_name)
                if temp_path and temp_path.exists() and temp_path.resolve() != final_path.resolve():
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

        # ── Update Master Tracker ──
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

        # ── Mark COMPLETED ──
        self.db.update_status(unique_key, STATUS_COMPLETED)
        self.summary.downloads_successful += 1
        logger.info("✓ Completed: %s", unique_key)

        # ── Update process tracker Excel ──
        self.process_tracker.update_record(unique_key, {
                    "Certificate_Type": CERT_TYPE_LOWER_TDS,
            "Financial_Year": self.fy,
            "PAN": row.pan,
            "Certificate_Number": row.certificate_number,
            "Status": STATUS_COMPLETED,
            "Final_Filename": cert_record.pdf_path,
        })

        # Re-open the popup for the next certificate
        self._reopen_popup_if_needed()

    # ──────────────────────────────────────────
    # Portal Interaction Helpers
    # ──────────────────────────────────────────

    def _navigate_to_page_and_select(self, row: PortalCertificateRow) -> None:
        """Navigate to the correct popup page and select the certificate row/card.

        Supports both CPCTDS 2.0 and legacy portal.
        """
        if is_flutter_portal(self.page):
            self.flutter.select(row)
            return

        # The popup might have closed after previous download — reopen if needed
        self._reopen_popup_if_needed()

        # Navigate to the correct page
        # First go to page 1 by clicking "First" or page number 1 if available
        self._go_to_first_page()

        # Navigate forward to the target page
        current_page = 1
        while current_page < row.page_number:
            if not click_next_page(self.page, SELECTORS.get("popup_next_page_btn")):
                break
            current_page += 1

        # Find the row by certificate number
        self._select_row_by_cert_number(row.certificate_number)

    def _go_to_first_page(self) -> None:
        """Navigate back to page 1 of the popup table."""
        try:
            first_btn = self.page.locator('.dataTables_paginate a:has-text("First")')
            if first_btn.count() > 0 and not first_btn.first.is_disabled():
                first_btn.first.click()
                self.page.wait_for_timeout(1500)
                return
        except PlaywrightError:
            pass

        try:
            page_one = self.page.locator('.dataTables_paginate a:has-text("1")')
            if page_one.count() > 0:
                page_one.first.click()
                self.page.wait_for_timeout(1500)
        except PlaywrightError:
            pass

    def _select_row_by_cert_number(self, cert_no: str) -> None:
        """Find and select the checkbox for a row matching the certificate number."""
        # First, uncheck all checkboxes
        self._uncheck_all()

        # Then find the row containing this cert number and check its checkbox
        row_locator = self.page.locator(f'{SELECTORS["popup_table"]} tr:has-text("{cert_no}")')
        if row_locator.count() == 0:
            raise ElementNotFoundError(f"Certificate row not found for {cert_no}")

        checkbox = row_locator.locator('input[type="checkbox"]')
        if checkbox.count() == 0:
            raise ElementNotFoundError(f"Checkbox not found in row for {cert_no}")

        checkbox.first.check()
        logger.debug("Selected checkbox for %s.", cert_no)

    def _uncheck_all(self) -> None:
        """Uncheck all checkboxes in the popup table."""
        try:
            checkboxes = self.page.locator(f'{SELECTORS["popup_table"]} input[type="checkbox"]:checked')
            count = checkboxes.count()
            for i in range(count):
                checkboxes.nth(i).uncheck()
        except PlaywrightError:
            pass

    def _count_selected_checkboxes(self) -> int:
        """Count currently checked checkboxes in the popup table."""
        try:
            checked = self.page.locator(f'{SELECTORS["popup_table"]} input[type="checkbox"]:checked')
            return checked.count()
        except PlaywrightError:
            return 0

    def _click_popup_initiate_download(self) -> None:
        """Click the Initiate Download button inside the popup or Flutter card."""
        if is_flutter_portal(self.page):
            self.flutter.submit()
            return

        btn = self.page.locator(SELECTORS["popup_initiate_download_btn"])
        if btn.count() == 0:
            # Fallback: scoped within popup modal
            modal = self.page.locator(SELECTORS["popup_modal"])
            btn = modal.get_by_role("button", name="Initiate Download")
        btn.first.click()
        self.page.wait_for_timeout(3000)
        logger.info("Initiated download request.")

    def _wait_for_download_ready(self) -> None:
        """Poll the Initiated Downloads section until the status becomes ready.

        Raises TimeoutError if not ready within MAX_REFRESH_ATTEMPTS.
        """
        logger.info("Waiting for download to become ready…")

        if is_flutter_portal(self.page):
            self.flutter.wait_ready()
            return

        for attempt in range(1, MAX_REFRESH_ATTEMPTS + 1):
            # Legacy HTML portal
            try:
                download_link = self.page.locator(
                    f'{SELECTORS["initiated_downloads_section"]} {SELECTORS["initiated_download_link"]}'
                )
                if download_link.count() > 0 and download_link.first.is_visible():
                    logger.info("✓ Download ready (attempt %d).", attempt)
                    return
            except PlaywrightError:
                pass

            # Click Refresh (scoped to initiated downloads section)
            try:
                section = self.page.locator(SELECTORS["initiated_downloads_section"])
                if section.count() > 0:
                    refresh_btn = section.locator(SELECTORS["initiated_refresh_btn"])
                    if refresh_btn.count() > 0:
                        refresh_btn.first.click()
                else:
                    # Fallback: any refresh button scoped by text
                    self.page.get_by_role("button", name="Refresh").first.click()
            except PlaywrightError:
                pass

            time.sleep(REFRESH_INTERVAL_SECONDS)

            if attempt % 5 == 0:
                logger.info("  Still waiting… (attempt %d/%d)", attempt, MAX_REFRESH_ATTEMPTS)

        raise TimeoutError(
            f"Download not ready after {MAX_REFRESH_ATTEMPTS} refresh attempts "
            f"({MAX_REFRESH_ATTEMPTS * REFRESH_INTERVAL_SECONDS}s)"
        )

    def _download_pdf(self) -> Path:
        """Click the Download link/button and save the PDF to a temp file.

        Uses Playwright's expect_download() to capture the browser download.
        Returns the path to the temp file.
        """
        logger.info("Triggering PDF download…")

        if is_flutter_portal(self.page):
            download_btn = self.flutter.download_button()
            with self.page.expect_download(timeout=DOWNLOAD_READY_TIMEOUT_MS) as download_info:
                download_btn.click()
            download = download_info.value
            original_name = download.suggested_filename or f"cert_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
            # Portal filenames mask PAN/certificate characters and can collide.
            temp_file = temp_download_path(f"lower_{self.flutter.selected.certificate_number}_{uuid4().hex}.pdf")
            download.save_as(str(temp_file))
            logger.info("Downloaded: %s (%d bytes)", temp_file.name, temp_file.stat().st_size)
            return temp_file

        with self.page.expect_download(timeout=DOWNLOAD_READY_TIMEOUT_MS) as download_info:
            link = self.page.locator(
                f'{SELECTORS["initiated_downloads_section"]} {SELECTORS["initiated_download_link"]}'
            )
            link.first.click()

        download = download_info.value
        original_name = download.suggested_filename or f"cert_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        temp_file = temp_download_path(original_name)
        download.save_as(str(temp_file))

        logger.info("Downloaded: %s (%d bytes)", temp_file.name, temp_file.stat().st_size)
        return temp_file

    def _reopen_popup_if_needed(self) -> None:
        """Re-open the download popup if it was closed after a download."""
        if is_flutter_portal(self.page):
            return

        try:
            table = self.page.locator(SELECTORS["popup_table"])
            if table.count() > 0 and table.first.is_visible():
                return  # Popup is still open
        except PlaywrightError:
            pass

        # Popup appears closed — re-trigger it
        logger.debug("Re-opening download popup…")
        try:
            setup_lower_tds_download(self.page, self.fy)
            self._wait_for_popup()
        except Exception as exc:
            logger.warning("Could not reopen popup: %s", exc)

    # ──────────────────────────────────────────
    # Failure Recording
    # ──────────────────────────────────────────

    def _record_failure(
        self,
        unique_key: str,
        row: PortalCertificateRow,
        error_msg: str,
    ) -> None:
        """Record a processing failure in DB, process tracker, and failed records."""
        logger.error("FAILED [%s]: %s", unique_key, error_msg)
        self.db.mark_failed(unique_key, error_msg)
        self.db.increment_retry(unique_key, error_msg)
        self.summary.failed += 1

        self.failed_tracker.add_failure({
            "Unique_Key": unique_key,
            "Certificate_Type": CERT_TYPE_LOWER_TDS,
            "Financial_Year": self.fy,
            "PAN": row.pan,
            "Certificate_Number": row.certificate_number,
            "Status": STATUS_FAILED,
            "Error_Message": error_msg,
            "Retry_Count": str(self.db.get_by_key(unique_key).get("retry_count", 0)
                               if self.db.get_by_key(unique_key) else 0),
        })
