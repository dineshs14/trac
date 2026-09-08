"""
TRACES Automation — Navigation

Navigate to specific TRACES portal pages:
    - Downloads → Lower/No Deduction Certificate(s)
    - Downloads → Child Certificate(s)
    - Services  → View Lower/No Deduction Certificate(s)
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, Error as PlaywrightError

from config import (
    TRACES_DOWNLOAD_CERT_URL,
    TRACES_CHILD_CERT_URL,
    TRACES_SERVICES_VIEW_CERT_URL,
    SELECTORS,
    PAGE_LOAD_TIMEOUT_MS,
    ELEMENT_WAIT_TIMEOUT_MS,
    CERT_TYPE_LOWER_TDS,
    CERT_TYPE_CHILD,
)
from automation.portal_utils import (
    wait_for_element,
    select_dropdown_by_label,
    select_dropdown_by_value,
    assert_session_alive,
    ElementNotFoundError,
    is_flutter_portal,
    enable_flutter_semantics,
)
from utils.logger import logger


def navigate_to_download_page(page: Page) -> None:
    """Navigate to the Download Certificate screen."""
    logger.info("Navigating to Download Certificate page…")
    page.goto(TRACES_DOWNLOAD_CERT_URL, wait_until="domcontentloaded",
              timeout=PAGE_LOAD_TIMEOUT_MS)
    page.wait_for_timeout(3000)
    assert_session_alive(page)
    logger.info("✓ On Download Certificate page.")


def setup_lower_tds_download(page: Page, fy: str) -> None:
    """Configure the download page for Lower TDS certificates.

    Supports both:
      1. CPCTDS 2.0 (Flutter Web): Enables semantics, switches to 'User is Recipient'
         tab, ensures 'Tax/Financial Year' radio is selected, and loads certificates.
      2. Legacy TRACES HTML portal: Selects certificate type dropdown, user type, and FY.
    """
    logger.info("Setting up Lower TDS download for FY %s…", fy)

    if is_flutter_portal(page):
        logger.info("Detected CPCTDS 2.0 (Flutter Web). Configuring Recipient view…")
        enable_flutter_semantics(page)

        # 1. Select 'User is Recipient' tab (Deductee Form 128 / Form 197 certificates)
        recipient_tab = page.locator("flt-semantics:has-text('User is Recipient')").last
        if recipient_tab.count() > 0:
            logger.info("Selecting 'User is Recipient' tab…")
            recipient_tab.click(force=True)
            page.wait_for_timeout(2000)

        _select_financial_year(page, fy)
        logger.info("Selected Recipient certificates year %s.", fy)
        return

    # Legacy HTML Portal Fallback:
    # Certificate Type
    try:
        select_dropdown_by_label(
            page,
            SELECTORS["download_cert_type_dropdown"],
            SELECTORS["download_cert_type_lower"],
            timeout_ms=5000,
        )
    except ElementNotFoundError:
        logger.debug("Trying fallback: select by visible text via option scanning")
        _select_option_by_text(page, SELECTORS["download_cert_type_dropdown"],
                               "Lower/No Deduction")

    # User Type
    try:
        select_dropdown_by_label(
            page,
            SELECTORS["download_user_type_dropdown"],
            SELECTORS["download_user_type_recipient"],
            timeout_ms=5000,
        )
    except ElementNotFoundError:
        _select_option_by_text(page, SELECTORS["download_user_type_dropdown"],
                               "Recipient")

    # Financial Year
    _select_financial_year(page, fy)

    # Click Initiate Download button
    logger.info("Clicking Initiate Download…")
    btn = page.locator(SELECTORS["download_initiate_btn"])
    if btn.count() == 0:
        btn = page.get_by_role("button", name="Initiate Download")
    btn.first.click()
    page.wait_for_timeout(3000)

    logger.info("✓ Lower TDS download popup should now be visible.")


def setup_child_certificate_download(page: Page, fy: str) -> None:
    """Configure the download page for Child certificates.

    Supports CPCTDS 2.0 and legacy portal.
    """
    logger.info("Setting up Child Certificate download for FY %s…", fy)

    if is_flutter_portal(page):
        logger.info("Detected CPCTDS 2.0 (Flutter Web). Opening Child Certificate URL…")
        if "downloadChildCertificate" not in page.url:
            page.goto(
                TRACES_CHILD_CERT_URL,
                wait_until="domcontentloaded",
                timeout=PAGE_LOAD_TIMEOUT_MS,
            )
            assert_session_alive(page)
            page.wait_for_timeout(3000)
        enable_flutter_semantics(page)
        from automation.year_selection import select_flutter_child_year
        select_flutter_child_year(page, fy)
        logger.info("Selected Child Certificate year %s.", fy)

        search = page.get_by_role("button", name=re.compile(r"^Search$", re.I))
        if search.count() == 0:
            search = page.locator("flt-semantics[role='button']").filter(
                has_text=re.compile(r"^Search$", re.I)
            )
        if search.count() == 0:
            raise ElementNotFoundError(
                "Child Certificate page opened, but its Search button was not found."
            )
        search.last.click(force=True)
        page.wait_for_timeout(3000)
        enable_flutter_semantics(page)
        return

    # Legacy HTML Portal Fallback
    try:
        select_dropdown_by_label(
            page,
            SELECTORS["download_cert_type_dropdown"],
            SELECTORS["download_cert_type_child"],
            timeout_ms=5000,
        )
    except ElementNotFoundError:
        _select_option_by_text(page, SELECTORS["download_cert_type_dropdown"],
                               "Child Certificate")

    # Tax Year
    _select_financial_year(page, fy, is_tax_year=True)

    # Click Search
    logger.info("Clicking Search…")
    btn = page.locator(SELECTORS["download_search_btn"])
    if btn.count() == 0:
        btn = page.get_by_role("button", name="Search")
    btn.first.click()
    page.wait_for_timeout(3000)

    logger.info("✓ Child certificate table should now be visible.")


def navigate_to_services_page(page: Page, fy: str) -> None:
    """Navigate to Services → View Lower/No Deduction Certificate(s)."""
    logger.info("Navigating to Services View Certificate page…")

    if is_flutter_portal(page):
        # Use the Services menu on the authenticated certificate page.
        # Reloading /auth can send an otherwise valid session to login.
        enable_flutter_semantics(page)
        services_menu = page.get_by_role("button", name=re.compile(r"Services Menu", re.I)).first
        if services_menu.count() > 0:
            services_menu.click(force=True)
            page.wait_for_timeout(1500)
            view_opt = page.get_by_text(re.compile(r"View Lower\s*/", re.I)).last
            if view_opt.count() > 0:
                view_opt.click(force=True)
                page.wait_for_timeout(2000)
                from automation.year_selection import select_flutter_services_year
                select_flutter_services_year(page, fy)
                proceed = page.get_by_role(
                    "button", name=re.compile(r"^Proceed$", re.I)
                )
                if proceed.count() == 0:
                    raise ElementNotFoundError(
                        "Services Proceed button was not found."
                    )
                proceed.last.click(force=True)
                page.wait_for_timeout(3000)
                enable_flutter_semantics(page)
                logger.info("✓ Navigated via Services Menu.")
                return
        raise ElementNotFoundError("Services > View Lower/No Deduction menu item was not found on the authenticated page.")

    page.goto(TRACES_SERVICES_VIEW_CERT_URL, wait_until="domcontentloaded",
              timeout=PAGE_LOAD_TIMEOUT_MS)
    page.wait_for_timeout(3000)
    assert_session_alive(page)

    # Financial Year
    _select_financial_year(page, fy)

    # Click Proceed
    logger.info("Clicking Proceed…")
    btn = page.locator(SELECTORS["services_proceed_btn"])
    if btn.count() == 0:
        btn = page.get_by_role("button", name="Proceed")
    btn.first.click()
    page.wait_for_timeout(3000)

    logger.info("✓ Services certificate list should now be visible.")


# ──────────────────────────────────────────────
# Internal Helpers
# ──────────────────────────────────────────────

def _select_financial_year(page: Page, fy: str, is_tax_year: bool = False) -> None:
    """Select the financial/tax year dropdown.

    Tries multiple strategies:
        1. By label text (e.g. "2026-27")
        2. By value attribute
        3. By option text scanning
    """
    if is_flutter_portal(page):
        if "downloadChildCertificate" in page.url:
            from automation.year_selection import select_flutter_child_year
            select_flutter_child_year(page, fy)
        else:
            from automation.year_selection import select_flutter_year
            select_flutter_year(page, fy)
        return

    selector = SELECTORS["download_tax_year_dropdown"] if is_tax_year else SELECTORS["download_fy_dropdown"]

    try:
        select_dropdown_by_label(page, selector, fy)
        return
    except ElementNotFoundError:
        pass

    try:
        select_dropdown_by_value(page, selector, fy)
        return
    except ElementNotFoundError:
        pass

    # Fallback: scan option text
    _select_option_by_text(page, selector, fy)


def _select_option_by_text(page: Page, dropdown_selector: str, partial_text: str) -> None:
    """Select a dropdown option by scanning option text for a partial match.

    This is a last-resort fallback when select_option(label=...) doesn't work.
    """
    try:
        options = page.locator(f"{dropdown_selector} option")
        count = options.count()
        for i in range(count):
            opt = options.nth(i)
            text = (opt.inner_text() or "").strip()
            if partial_text.lower() in text.lower():
                value = opt.get_attribute("value") or ""
                page.locator(dropdown_selector).first.select_option(value=value)
                page.wait_for_timeout(500)
                logger.debug("Fallback selected '%s' (value='%s')", text, value)
                return
        raise ElementNotFoundError(
            f"No option containing '{partial_text}' in '{dropdown_selector}'"
        )
    except PlaywrightError as exc:
        raise ElementNotFoundError(str(exc)) from exc
