"""
TRACES Automation — Portal Utilities

Shared helpers for interacting with the TRACES portal:
    - Wait-for-element with fallbacks
    - Session-alive guard
    - Table row extraction
    - Page count detection
    - DOM inspection helpers
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from playwright.sync_api import Page, Locator, Error as PlaywrightError, TimeoutError as PwTimeout

from config import (
    ELEMENT_WAIT_TIMEOUT_MS,
    SELECTORS,
    PAN_REGEX,
)
from utils.logger import logger


class PortalError(Exception):
    """Base exception for portal interaction errors."""


class SessionLostError(PortalError):
    """Raised when the session appears to have expired mid-run."""


class ElementNotFoundError(PortalError):
    """Raised when an expected portal element cannot be found."""


# ──────────────────────────────────────────────
# Flutter Web Support
# ──────────────────────────────────────────────

def is_flutter_portal(page: Page) -> bool:
    """Check if the current page is rendered via Flutter Web (CPCTDS 2.0)."""
    try:
        return (
            page.locator("flutter-view").count() > 0
            or page.locator("flt-semantics-placeholder").count() > 0
            or page.locator("flt-glass-pane").count() > 0
        )
    except PlaywrightError:
        return False


def enable_flutter_semantics(page: Page) -> bool:
    """Activate Flutter's accessibility/semantic DOM tree if not already active."""
    try:
        placeholder = page.locator("flt-semantics-placeholder")
        if placeholder.count() > 0:
            placeholder.evaluate("el => el.click()")
            page.wait_for_timeout(1500)
            logger.debug("Activated Flutter accessibility semantics.")
            return True
        return False
    except PlaywrightError as exc:
        logger.debug("Flutter semantics activation skipped: %s", exc)
        return False


# ──────────────────────────────────────────────
# Waiting / Element Location
# ──────────────────────────────────────────────

def wait_for_element(
    page: Page,
    selector: str,
    timeout_ms: int = ELEMENT_WAIT_TIMEOUT_MS,
    state: str = "visible",
) -> Locator:
    """Wait for a single element matching *selector* to reach *state*.

    Raises ElementNotFoundError if the element is not found within timeout.
    """
    try:
        locator = page.locator(selector)
        locator.first.wait_for(state=state, timeout=timeout_ms)
        return locator
    except (PwTimeout, PlaywrightError) as exc:
        raise ElementNotFoundError(
            f"Element not found: '{selector}' (timeout={timeout_ms}ms)"
        ) from exc


def wait_for_any(
    page: Page,
    selectors: List[str],
    timeout_ms: int = ELEMENT_WAIT_TIMEOUT_MS,
) -> Optional[str]:
    """Wait until any one of the selectors becomes visible.

    Returns the first matching selector, or None on timeout.
    """
    poll_interval = 500
    elapsed = 0
    while elapsed < timeout_ms:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return sel
            except PlaywrightError:
                continue
        page.wait_for_timeout(poll_interval)
        elapsed += poll_interval
    return None


# ──────────────────────────────────────────────
# Session Guard
# ──────────────────────────────────────────────

def assert_session_alive(page: Page) -> None:
    """Check that the session is still active; raise if login page detected.

    Call this periodically during long-running operations.
    """
    try:
        # If we see a login form, session is dead
        login_loc = page.locator(SELECTORS["login_indicator"])
        if login_loc.count() > 0 and login_loc.first.is_visible():
            raise SessionLostError("Session expired — login page detected.")

        login_alt = page.locator(SELECTORS["login_indicator_alt"])
        if login_alt.count() > 0 and login_alt.first.is_visible():
            raise SessionLostError("Session expired — login form detected.")

        if "login" in page.url.lower():
            raise SessionLostError(f"Session expired — redirected to login: {page.url}")

    except SessionLostError:
        raise
    except PlaywrightError:
        pass  # Transient DOM issue — don't raise


# ──────────────────────────────────────────────
# Table Parsing
# ──────────────────────────────────────────────

def extract_table_rows(
    page: Page,
    row_selector: str,
    column_names: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Extract text content from each row of a table.

    Args:
        page:          The Playwright page.
        row_selector:  CSS selector for <tr> elements.
        column_names:  Optional list of column names (matched positionally).
                       If None, columns are named col_0, col_1, etc.

    Returns:
        List of dicts, one per row.
    """
    rows: List[Dict[str, str]] = []
    row_locators = page.locator(row_selector)
    count = row_locators.count()

    for i in range(count):
        row_loc = row_locators.nth(i)
        cells = row_loc.locator("td")
        cell_count = cells.count()
        row_data: Dict[str, str] = {}

        for j in range(cell_count):
            text = (cells.nth(j).inner_text() or "").strip()
            col_key = column_names[j] if column_names and j < len(column_names) else f"col_{j}"
            row_data[col_key] = text

        rows.append(row_data)

    return rows


# ──────────────────────────────────────────────
# Pagination
# ──────────────────────────────────────────────

def detect_total_pages(page: Page, info_selector: Optional[str] = None) -> int:
    """Attempt to detect the total number of pages from pagination info text.

    Looks for patterns like:
        'Showing 1 to 5 of 376 entries'
        'Page 1 of 76'

    Returns 1 if detection fails (safe fallback — iterate until Next is disabled).
    """
    sel = info_selector or SELECTORS.get("popup_page_info", "")
    try:
        info_loc = page.locator(sel)
        if info_loc.count() > 0:
            text = info_loc.first.inner_text().strip()
            # Pattern: "Showing X to Y of Z entries"
            match = re.search(r"of\s+(\d[\d,]*)\s+entries", text, re.IGNORECASE)
            if match:
                total_entries = int(match.group(1).replace(",", ""))
                # Try to determine page size
                page_match = re.search(r"Showing\s+\d+\s+to\s+(\d+)", text)
                page_size = int(page_match.group(1)) if page_match else 5
                total_pages = (total_entries + page_size - 1) // page_size
                logger.info("Detected %d entries across ~%d pages", total_entries, total_pages)
                return total_pages
    except (PlaywrightError, ValueError) as exc:
        logger.debug("Page count detection failed: %s", exc)

    return 1  # Safe fallback


def has_next_page(page: Page, next_btn_selector: Optional[str] = None) -> bool:
    """Check whether the Next page button exists and is enabled."""
    sel = next_btn_selector or SELECTORS.get("popup_next_page_btn", "")
    try:
        next_loc = page.locator(sel)
        if next_loc.count() == 0:
            return False
        # Check for disabled state (DataTables uses class "disabled" on parent)
        parent = next_loc.first.locator("..")
        parent_classes = parent.get_attribute("class") or ""
        if "disabled" in parent_classes.lower():
            return False
        # Also check the element itself
        if next_loc.first.is_disabled():
            return False
        return True
    except PlaywrightError:
        return False


def click_next_page(page: Page, next_btn_selector: Optional[str] = None) -> bool:
    """Click the Next page button. Returns True if clicked, False if not available."""
    if not has_next_page(page, next_btn_selector):
        return False
    sel = next_btn_selector or SELECTORS.get("popup_next_page_btn", "")
    try:
        page.locator(sel).first.click()
        page.wait_for_timeout(1500)  # Allow table to re-render
        return True
    except PlaywrightError as exc:
        logger.warning("Failed to click Next: %s", exc)
        return False


# ──────────────────────────────────────────────
# Dropdown Selection
# ──────────────────────────────────────────────

def select_dropdown_by_label(
    page: Page,
    dropdown_selector: str,
    label_text: str,
    timeout_ms: int = ELEMENT_WAIT_TIMEOUT_MS,
) -> None:
    """Select a dropdown option by its visible label text."""
    try:
        dropdown = page.locator(dropdown_selector)
        dropdown.first.wait_for(state="visible", timeout=timeout_ms)
        dropdown.first.select_option(label=label_text)
        page.wait_for_timeout(1000)
        logger.debug("Selected '%s' in %s", label_text, dropdown_selector)
    except PlaywrightError as exc:
        raise ElementNotFoundError(
            f"Cannot select '{label_text}' in '{dropdown_selector}': {exc}"
        ) from exc


def select_dropdown_by_value(
    page: Page,
    dropdown_selector: str,
    value: str,
    timeout_ms: int = ELEMENT_WAIT_TIMEOUT_MS,
) -> None:
    """Select a dropdown option by its value attribute."""
    try:
        dropdown = page.locator(dropdown_selector)
        dropdown.first.wait_for(state="visible", timeout=timeout_ms)
        dropdown.first.select_option(value=value)
        page.wait_for_timeout(1000)
        logger.debug("Selected value '%s' in %s", value, dropdown_selector)
    except PlaywrightError as exc:
        raise ElementNotFoundError(
            f"Cannot select value '{value}' in '{dropdown_selector}': {exc}"
        ) from exc


# ──────────────────────────────────────────────
# DOM Inspection Helpers
# ──────────────────────────────────────────────

def print_accessible_tree(page: Page, selector: str = "body") -> str:
    """Print the accessible tree for a section of the page.

    Useful for verifying selectors with Playwright Inspector.
    Returns the snapshot string.
    """
    try:
        snapshot = page.locator(selector).first.evaluate(
            """(el) => {
                const walk = (node, depth) => {
                    let result = '  '.repeat(depth);
                    result += node.tagName?.toLowerCase() || '#text';
                    if (node.id) result += ' #' + node.id;
                    if (node.className && typeof node.className === 'string')
                        result += ' .' + node.className.split(' ').join('.');
                    if (node.getAttribute?.('role'))
                        result += ' [role=' + node.getAttribute('role') + ']';
                    if (node.tagName === 'INPUT' || node.tagName === 'SELECT')
                        result += ' [type=' + (node.type || 'text') + ']';
                    result += '\\n';
                    for (const child of (node.children || []))
                        result += walk(child, depth + 1);
                    return result;
                };
                return walk(el, 0);
            }"""
        )
        logger.debug("Accessible tree for '%s':\n%s", selector, snapshot)
        return snapshot
    except PlaywrightError as exc:
        msg = f"Could not get accessible tree: {exc}"
        logger.debug(msg)
        return msg


def print_page_selectors(page: Page) -> Dict[str, Any]:
    """Dump key interactive elements on the page for selector verification.

    Returns a dict of element categories.
    """
    result: Dict[str, Any] = {}
    try:
        # Buttons
        buttons = page.locator("button, input[type='button'], input[type='submit']")
        btn_list = []
        for i in range(min(buttons.count(), 50)):
            btn = buttons.nth(i)
            btn_list.append({
                "text": (btn.inner_text() or "").strip()[:80],
                "id": btn.get_attribute("id") or "",
                "type": btn.get_attribute("type") or "",
                "visible": btn.is_visible(),
            })
        result["buttons"] = btn_list

        # Dropdowns
        selects = page.locator("select")
        sel_list = []
        for i in range(min(selects.count(), 20)):
            sel = selects.nth(i)
            sel_list.append({
                "id": sel.get_attribute("id") or "",
                "name": sel.get_attribute("name") or "",
                "visible": sel.is_visible(),
            })
        result["dropdowns"] = sel_list

        # Links
        links = page.locator("a[href]")
        link_list = []
        for i in range(min(links.count(), 50)):
            lnk = links.nth(i)
            link_list.append({
                "text": (lnk.inner_text() or "").strip()[:60],
                "href": (lnk.get_attribute("href") or "")[:100],
                "visible": lnk.is_visible(),
            })
        result["links"] = link_list

    except PlaywrightError as exc:
        logger.debug("Selector dump failed: %s", exc)

    return result
