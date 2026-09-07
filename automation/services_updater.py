"""
TRACES Automation — Services Updater

Module 3: Navigate to Services → View Lower/No Deduction Certificate(s)
For each certificate:
    1. Click certificate details
    2. Extract certificate metadata
    3. Expand and extract Consumption Details
    4. Aggregate Q1–Q4
    5. Calculate Total Consumed and Available Amount
    6. Update the existing Master Tracker row
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from playwright.sync_api import Page, Error as PlaywrightError

from config import (
    SELECTORS,
    ELEMENT_WAIT_TIMEOUT_MS,
    STATUS_SERVICES_UPDATED,
    STATUS_COMPLETED,
)
from automation.portal_utils import (
    assert_session_alive,
    wait_for_element,
    has_next_page,
    click_next_page,
    extract_table_rows,
    SessionLostError,
    ElementNotFoundError,
    is_flutter_portal,
)
from automation.navigation import navigate_to_services_page
from data.tracker_store import TrackerStore
from data.master_tracker import MasterTracker
from data.models import ConsumptionEntry, RunSummary
from utils.logger import logger


class ServicesUpdater:
    """Extracts certificate details and consumption data from the Services page."""

    def __init__(
        self,
        page: Page,
        fy: str,
        db: TrackerStore,
        master: MasterTracker,
    ) -> None:
        self.page = page
        self.fy = fy
        self.db = db
        self.master = master
        self.summary = RunSummary(task="services-update", financial_year=fy)

    def run(self) -> RunSummary:
        """Execute the services update workflow."""
        self.summary.run_start = datetime.now()
        logger.info("=" * 60)
        logger.info("  SERVICES UPDATE — FY %s", self.fy)
        logger.info("=" * 60)

        try:
            navigate_to_services_page(self.page, self.fy)

            # Process all certificate entries across pages
            page_num = 1
            while True:
                logger.info("Processing services page %d…", page_num)
                assert_session_alive(self.page)

                entries = self._extract_page_entries()
                if not entries:
                    raise ElementNotFoundError(
                        "Services certificate rows could not be read. "
                        "The current page/Flutter selectors need verification; no updates were made."
                    )
                self.summary.portal_records_discovered += len(entries)

                for entry in entries:
                    try:
                        assert_session_alive(self.page)
                        if self.master.find_row_by_pan_cert_fy(
                            entry.get("pan", ""),
                            entry.get("certificate_number", ""),
                            entry.get("financial_year", self.fy),
                        ) is None:
                            continue
                        self._process_entry(entry)
                    except SessionLostError:
                        raise
                    except Exception as exc:
                        logger.error("Error processing services entry %s: %s",
                                     entry.get("certificate_number", "?"), exc)
                        self.summary.failed += 1

                # Check for more pages
                if is_flutter_portal(self.page):
                    next_btn = self.page.get_by_role(
                        "button", name="Next", exact=True
                    )
                    if next_btn.count() == 0 or next_btn.last.is_disabled():
                        break
                    self._click_flutter_control(next_btn.last)
                    self.page.wait_for_timeout(1500)
                else:
                    next_sel = SELECTORS.get("services_next_page_btn")
                    if not has_next_page(self.page, next_sel):
                        break
                    if not click_next_page(self.page, next_sel):
                        break
                page_num += 1

        except SessionLostError:
            self.summary.failed += 1
            logger.error("Session expired during services update.")
        except Exception as exc:
            self.summary.failed += 1
            logger.error("Services update failed: %s", exc, exc_info=True)

        self.summary.run_end = datetime.now()
        logger.info(self.summary.print_summary())
        return self.summary

    # ──────────────────────────────────────────

    def _extract_page_entries(self) -> List[Dict[str, str]]:
        """Extract certificate list entries from the current services page.

        Each entry should have PAN, Certificate Number, FY, and a way to
        click into its details.
        """
        entries: List[Dict[str, str]] = []

        if is_flutter_portal(self.page):
            leaf_texts = []
            for item in self.page.locator("flt-semantics").all():
                if item.locator(":scope > flt-semantics").count() == 0:
                    text = (item.inner_text() or "").strip()
                    if text:
                        leaf_texts.append(text)

            current: Dict[str, str] = {}
            expected = ""
            for text in leaf_texts:
                if text in {"PAN", "Tax/Financial Year", "Certificate Number"}:
                    expected = text
                    continue
                if text == "Certificate details":
                    if all(current.get(key) for key in (
                        "pan", "financial_year", "certificate_number"
                    )):
                        current["row_index"] = str(len(entries))
                        entries.append(current)
                    current = {}
                    expected = ""
                    continue
                if expected == "PAN" and re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", text):
                    current["pan"] = text
                    expected = ""
                elif expected == "Tax/Financial Year" and re.fullmatch(r"\d{4}-\d{2}", text):
                    current["financial_year"] = text
                    expected = ""
                elif expected == "Certificate Number" and re.fullmatch(r"[A-Z0-9]{8,}", text):
                    current["certificate_number"] = text
                    expected = ""
            return entries

        try:
            cert_list = self.page.locator(SELECTORS["services_cert_list"])
            if cert_list.count() == 0:
                # Fallback: look for a table or list structure
                cert_list = self.page.locator("table tbody")

            rows = cert_list.locator("tr")
            count = rows.count()

            for i in range(count):
                row = rows.nth(i)
                cells = row.locator("td")
                cell_count = cells.count()

                if cell_count < 3:
                    continue

                # Extract text from each cell
                entry: Dict[str, str] = {"row_index": str(i)}
                cell_texts = []
                for j in range(cell_count):
                    cell_texts.append((cells.nth(j).inner_text() or "").strip())

                # Try to identify PAN (5 alpha + 4 digit + 1 alpha pattern)
                for text in cell_texts:
                    pan_match = re.search(r"[A-Z]{5}\d{4}[A-Z]", text)
                    if pan_match:
                        entry["pan"] = pan_match.group()
                        break

                # Try to identify certificate number (alphanumeric pattern)
                for text in cell_texts:
                    if re.match(r"\d+[A-Z]+\d+", text) or "NA" in text.upper():
                        if len(text) > 5:
                            entry["certificate_number"] = text
                            break

                # Financial year
                for text in cell_texts:
                    fy_match = re.search(r"\d{4}-\d{2}", text)
                    if fy_match:
                        entry["financial_year"] = fy_match.group()
                        break

                if "certificate_number" in entry:
                    entries.append(entry)

        except PlaywrightError as exc:
            logger.warning("Could not parse services entries: %s", exc)

        return entries

    def _process_entry(self, entry: Dict[str, str]) -> None:
        """Process a single services certificate entry.

        Steps:
            1. Click Certificate details
            2. Extract metadata
            3. Expand Consumption Details
            4. Extract and aggregate consumption by quarter
            5. Update Master Tracker
        """
        pan = entry.get("pan", "")
        cert_no = entry.get("certificate_number", "")
        fy = entry.get("financial_year", self.fy)

        if not cert_no:
            return

        logger.info("Processing services detail: PAN=%s, Cert=%s", pan, cert_no)

        # Click Certificate details for this entry
        try:
            self._click_certificate_details(entry)
        except Exception as exc:
            logger.warning("Could not open cert details for %s: %s", cert_no, exc)
            self.summary.failed += 1
            return

        # Extract certificate detail fields
        details = self._extract_certificate_details()

        # Expand and extract Consumption Details
        consumption_entries = self._extract_consumption_details()

        # Aggregate by quarter
        q_totals = self._aggregate_by_quarter(consumption_entries)

        # Calculate totals
        total_consumed = sum(q_totals.values())
        cert_limit = details.get("certificate_limit")
        cert_limit_val = self._parse_amount(cert_limit) if cert_limit else None

        portal_total = self._parse_amount(details.get("total_amount_consumed", ""))

        available = None
        if cert_limit_val is not None:
            available = cert_limit_val - total_consumed

        # Cross-check portal total vs calculated total
        notes = ""
        if portal_total is not None and abs(portal_total - total_consumed) > 0.01:
            notes = f"CONSUMPTION_MISMATCH: portal_total={portal_total}, calculated={total_consumed}"
            logger.warning("Consumption mismatch for %s: portal=%s, calculated=%s",
                           cert_no, portal_total, total_consumed)

        # Build update dict
        updates: Dict[str, any] = {
            "Date_of_Issue": details.get("date_of_issue", ""),
            "Application_Form_No": details.get("application_form_no", ""),
            "Applicable_Income_Tax_Act": details.get("applicable_income_tax_act", ""),
            "Section": details.get("section", ""),
            "Section_Code": details.get("section_code", ""),
            "Nature_of_Payment": details.get("nature_of_payment", ""),
            "TDS_Rate": details.get("rate_as_per_certificate", ""),
            "Certificate_Limit": cert_limit_val,
            "Q1_Amount_Consumed": q_totals.get("Q1", 0),
            "Q2_Amount_Consumed": q_totals.get("Q2", 0),
            "Q3_Amount_Consumed": q_totals.get("Q3", 0),
            "Q4_Amount_Consumed": q_totals.get("Q4", 0),
            "Total_Amount_Consumed": portal_total if portal_total is not None else total_consumed,
            "Available_Amount": available,
            "Date_of_Cancellation": details.get("date_of_cancellation", ""),
            "Processing_Status": STATUS_SERVICES_UPDATED,
        }

        if notes:
            updates["Notes"] = notes

        # Clean empty values
        updates = {k: v for k, v in updates.items() if v is not None and v != ""}

        # Update Master Tracker
        updated = self.master.update_services_data(pan, cert_no, fy, updates)

        if updated:
            self.summary.services_records_updated += 1
            # Also update DB tracker if record exists
            for cert_type in ["LOWER_TDS", "CHILD"]:
                unique_key = f"{cert_type}|{fy}|{pan}|{cert_no}"
                db_row = self.db.get_by_key(unique_key)
                if db_row:
                    self.db.update_status(unique_key, db_row["status"],
                                          services_update_status="SUCCESS")
                    break
            logger.info("✓ Services data updated for %s", cert_no)
        else:
            logger.warning("No matching Master row for PAN=%s, Cert=%s, FY=%s",
                           pan, cert_no, fy)
            self.summary.failed += 1

        # Navigate back to the list
        self._go_back_to_list()

    # ──────────────────────────────────────────
    # Portal Interaction
    # ──────────────────────────────────────────

    def _click_certificate_details(self, entry: Dict[str, str]) -> None:
        """Click the Certificate details link/button for a specific entry."""
        row_idx = int(entry.get("row_index", 0))

        if is_flutter_portal(self.page):
            buttons = self.page.get_by_role(
                "button", name="Certificate details", exact=True
            )
            if row_idx >= buttons.count():
                raise ElementNotFoundError(
                    f"Cannot find certificate details for row {row_idx}"
                )
            button = buttons.nth(row_idx)
            box = button.bounding_box()
            if not box:
                raise ElementNotFoundError(
                    f"Certificate details row {row_idx} has no visible bounds"
                )
            self._click_flutter_control(
                button, x=box["x"] + box["width"] - 100
            )
            self.page.wait_for_timeout(3000)
            return

        # Try finding the detail link in the specific row
        try:
            cert_list = self.page.locator(SELECTORS["services_cert_list"])
            if cert_list.count() == 0:
                cert_list = self.page.locator("table tbody")

            rows = cert_list.locator("tr")
            if row_idx < rows.count():
                row_el = rows.nth(row_idx)
                # Look for details link/button
                detail_link = row_el.locator('a:has-text("Certificate details")')
                if detail_link.count() == 0:
                    detail_link = row_el.locator('a:has-text("Details")')
                if detail_link.count() == 0:
                    detail_link = row_el.locator('button:has-text("Details")')
                if detail_link.count() == 0:
                    # Fallback: any link in the row
                    detail_link = row_el.locator("a").first

                detail_link.click()
                self.page.wait_for_timeout(3000)
                return

        except PlaywrightError:
            pass

        # Fallback: use the global cert details link
        detail_btn = self.page.locator(SELECTORS["services_cert_detail_btn"])
        if detail_btn.count() > row_idx:
            detail_btn.nth(row_idx).click()
            self.page.wait_for_timeout(3000)
        else:
            raise ElementNotFoundError(
                f"Cannot find certificate details for row {row_idx}"
            )

    def _extract_certificate_details(self) -> Dict[str, str]:
        """Extract certificate detail fields from the detail view.

        Expected fields (text labels on the page):
            - Certificate Number
            - PAN
            - Tax/Financial Year
            - Application Form No
            - Applicable Income-tax Act
            - Date of Issue
            - Certificate Validity
            - Section under which certificate is issued
            - Section Code
            - Nature of Payment
            - Certificate Limit
            - Rate as per Certificate
            - Total Amount Consumed
            - Date of Cancellation
        """
        details: Dict[str, str] = {}

        field_mappings = {
            "certificate_number": ["Certificate Number", "Certificate No"],
            "pan": ["PAN"],
            "financial_year": ["Tax/Financial Year", "Financial Year", "Tax Year"],
            "application_form_no": ["Application Form No", "Application Form Number"],
            "applicable_income_tax_act": ["Applicable Income-tax Act", "Applicable Income Tax Act"],
            "date_of_issue": ["Date of Issue", "Date Of Issue"],
            "certificate_validity": ["Certificate Validity"],
            "section": ["Section under which certificate is issued", "Section"],
            "section_code": ["Section Code"],
            "nature_of_payment": ["Nature of Payment", "Nature Of Payment"],
            "certificate_limit": ["Certificate Limit"],
            "rate_as_per_certificate": ["Rate as per Certificate", "Rate As Per Certificate"],
            "total_amount_consumed": ["Total Amount Consumed"],
            "date_of_cancellation": ["Date of Cancellation", "Date Of Cancellation"],
        }

        for key, labels in field_mappings.items():
            for label in labels:
                value = self._extract_field_value(label)
                if value:
                    details[key] = value
                    break

        # Handle "Not Cancelled" specifically
        if details.get("date_of_cancellation", "").strip().lower() == "not cancelled":
            details["date_of_cancellation"] = "Not Cancelled"

        logger.debug("Extracted certificate details: %s", details)
        return details

    def _extract_field_value(self, label: str) -> str:
        """Extract the value following a label on the page.

        Tries multiple strategies:
            1. Look for a label-value pair in table rows (th/td or dt/dd)
            2. Look for text followed by a colon
            3. Look for adjacent elements
        """
        try:
            if is_flutter_portal(self.page):
                leaves = self.page.locator("flt-semantics").all()
                for index, item in enumerate(leaves):
                    if item.locator(":scope > flt-semantics").count() > 0:
                        continue
                    text = (item.inner_text() or "").strip()
                    if text != label:
                        continue
                    for candidate in leaves[index + 1:]:
                        if candidate.locator(":scope > flt-semantics").count() > 0:
                            continue
                        value = (candidate.inner_text() or "").strip()
                        if value:
                            return value
                    return ""

            # Strategy 1: Find label in a table cell, get the next cell
            label_loc = self.page.get_by_text(label, exact=False)
            if label_loc.count() > 0:
                # Try getting the sibling/next cell
                parent_row = label_loc.first.locator("xpath=ancestor::tr[1]")
                if parent_row.count() > 0:
                    cells = parent_row.locator("td")
                    if cells.count() >= 2:
                        # The value is typically in the second td
                        value_cell_text = cells.nth(1).inner_text().strip()
                        if value_cell_text and value_cell_text != label:
                            return value_cell_text

                # Strategy 2: dd after dt
                parent_dl = label_loc.first.locator("xpath=ancestor::dl[1]")
                if parent_dl.count() > 0:
                    dd = label_loc.first.locator("xpath=following-sibling::dd[1]")
                    if dd.count() > 0:
                        return dd.first.inner_text().strip()

                # Strategy 3: span/div adjacent
                parent = label_loc.first.locator("xpath=..")
                if parent.count() > 0:
                    spans = parent.locator("span")
                    for i in range(spans.count()):
                        text = spans.nth(i).inner_text().strip()
                        if text and text != label and ":" not in text:
                            return text

        except PlaywrightError:
            pass

        return ""

    def _extract_consumption_details(self) -> List[ConsumptionEntry]:
        """Expand and extract the Consumption Details table."""
        entries: List[ConsumptionEntry] = []

        if is_flutter_portal(self.page):
            control = self.page.get_by_role(
                "button", name="Consumption Details", exact=True
            )
            if control.count() > 0:
                box = control.bounding_box()
                if box:
                    self._click_flutter_control(
                        control, x=box["x"] + box["width"] + 20
                    )
                    self.page.wait_for_timeout(1500)
            row_pattern = re.compile(
                r"^(\S+)\s+(\d{4}-\d{2})\s+(Q[1-4])\s+(\S+)\s+"
                r"([\d,]+(?:\.\d+)?)$"
            )
            for item in self.page.locator("flt-semantics").all():
                if item.locator(":scope > flt-semantics").count() > 0:
                    continue
                match = row_pattern.match((item.inner_text() or "").strip())
                if not match:
                    continue
                entries.append(ConsumptionEntry(
                    token_acknowledgement_number=match.group(1),
                    financial_year=match.group(2),
                    quarter=match.group(3),
                    form_type=match.group(4),
                    consumed_amount=self._parse_amount(match.group(5)) or 0.0,
                ))
            return entries

        # Click to expand Consumption Details
        try:
            expand_btn = self.page.locator(SELECTORS["services_consumption_expand"])
            if expand_btn.count() > 0:
                expand_btn.first.click()
                self.page.wait_for_timeout(2000)
        except PlaywrightError:
            logger.debug("Could not expand consumption details — may already be visible")

        # Extract table rows
        try:
            table = self.page.locator(SELECTORS["services_consumption_table"])
            if table.count() == 0:
                # Fallback: look for any table after "Consumption Details" text
                table = self.page.locator("table").last

            rows = table.locator("tbody tr")
            count = rows.count()

            for i in range(count):
                cells = rows.nth(i).locator("td")
                cell_count = cells.count()

                if cell_count < 4:
                    continue

                # Expected columns (positional — VERIFY_WITH_INSPECTOR):
                # Token/Acknowledgement Number | Financial Year | Quarter | Form Type | Consumed Amount
                entry = ConsumptionEntry()

                cell_texts = []
                for j in range(cell_count):
                    cell_texts.append((cells.nth(j).inner_text() or "").strip())

                if cell_count >= 5:
                    entry.token_acknowledgement_number = cell_texts[0]
                    entry.financial_year = cell_texts[1]
                    entry.quarter = self._normalize_quarter(cell_texts[2])
                    entry.form_type = cell_texts[3]
                    entry.consumed_amount = self._parse_amount(cell_texts[4]) or 0.0
                elif cell_count >= 4:
                    entry.token_acknowledgement_number = cell_texts[0]
                    entry.quarter = self._normalize_quarter(cell_texts[1])
                    entry.form_type = cell_texts[2]
                    entry.consumed_amount = self._parse_amount(cell_texts[3]) or 0.0

                if entry.quarter:
                    entries.append(entry)

        except PlaywrightError as exc:
            logger.warning("Error extracting consumption details: %s", exc)

        logger.debug("Extracted %d consumption entries", len(entries))
        return entries

    def _aggregate_by_quarter(self, entries: List[ConsumptionEntry]) -> Dict[str, float]:
        """Aggregate consumed amounts by quarter.

        If multiple rows exist for the same quarter, SUM the amounts.
        """
        totals: Dict[str, float] = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}

        for entry in entries:
            q = entry.quarter.upper()
            if q in totals:
                totals[q] += entry.consumed_amount

        logger.debug("Quarter aggregation: %s", totals)
        return totals

    def _go_back_to_list(self) -> None:
        """Navigate back to the certificate list from the detail view."""
        try:
            if is_flutter_portal(self.page):
                back = self.page.get_by_role("button", name="Back", exact=True)
                if back.count() == 0:
                    raise ElementNotFoundError("Services Back button was not found")
                self._click_flutter_control(back.last)
                self.page.wait_for_timeout(2000)
                return
            # Try browser back
            self.page.go_back(wait_until="domcontentloaded", timeout=30000)
            self.page.wait_for_timeout(2000)
        except PlaywrightError:
            # Fallback: navigate to the services page again
            navigate_to_services_page(self.page, self.fy)

    def _click_flutter_control(self, control, x: Optional[float] = None) -> None:
        """Click the Flutter canvas beneath an accessibility semantic node."""
        control.scroll_into_view_if_needed()
        box = control.bounding_box()
        if not box:
            raise ElementNotFoundError("Flutter control has no visible bounds")
        style = self.page.add_style_tag(content=(
            "flt-semantics-host, flt-semantics-host * "
            "{ pointer-events: none !important; }"
        ))
        try:
            self.page.mouse.click(
                x if x is not None else box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
            )
        finally:
            style.evaluate("el => el.remove()")

    # ──────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────

    @staticmethod
    def _normalize_quarter(text: str) -> str:
        """Normalize quarter text to Q1/Q2/Q3/Q4."""
        text = text.strip().upper()
        if "Q1" in text or "1" == text:
            return "Q1"
        if "Q2" in text or "2" == text:
            return "Q2"
        if "Q3" in text or "3" == text:
            return "Q3"
        if "Q4" in text or "4" == text:
            return "Q4"
        # Try month-based mapping
        if "APR" in text or "MAY" in text or "JUN" in text:
            return "Q1"
        if "JUL" in text or "AUG" in text or "SEP" in text:
            return "Q2"
        if "OCT" in text or "NOV" in text or "DEC" in text:
            return "Q3"
        if "JAN" in text or "FEB" in text or "MAR" in text:
            return "Q4"
        return text

    @staticmethod
    def _parse_amount(text: str) -> Optional[float]:
        """Parse a monetary amount from text, handling commas and currency symbols."""
        if not text:
            return None
        # Remove currency symbols, commas, spaces
        cleaned = re.sub(r"[₹$,\s]", "", text.strip())
        try:
            return float(cleaned)
        except ValueError:
            return None
