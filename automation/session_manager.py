"""
TRACES Automation — Session Manager

Launches a persistent Chromium context, detects authentication state,
and waits for manual login when the session has expired.

IMPORTANT:
    - Never automates CAPTCHA, OTP, or login credentials.
    - Reuses the same browser profile across runs.
    - Preserves cookies, localStorage, and auth state between runs.
"""

from __future__ import annotations

import time
import re
from typing import Optional

from playwright.sync_api import (
    sync_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
    Error as PlaywrightError,
)

from config import (
    BROWSER_PROFILE_DIR,
    BROWSER_HEADLESS,
    BROWSER_ACCEPT_DOWNLOADS,
    BROWSER_ARGS,
    BROWSER_VIEWPORT,
    TRACES_DOWNLOAD_CERT_URL,
    TRACES_AUTH_URL,
    TRACES_LOGIN_URL,
    PAGE_LOAD_TIMEOUT_MS,
    LOGIN_WAIT_TIMEOUT_MS,
    NAVIGATION_TIMEOUT_MS,
    SELECTORS,
    TEMP_DOWNLOAD_DIR,
)
from utils.logger import logger


class SessionExpiredError(Exception):
    """Raised when the TRACES session has expired and the user did not log in within the timeout."""


class SessionManager:
    """Manages the Playwright persistent browser context for TRACES."""

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def page(self) -> Page:
        if self._page is None or self._page.is_closed():
            raise RuntimeError("Browser page is not available. Call start() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser context is not available. Call start() first.")
        return self._context

    # ── Lifecycle ───────────────────────────────

    def start(self) -> Page:
        """Launch the persistent browser context and return the active page.

        The browser profile is stored in Process_Files/browser_profile/ and
        is reused across runs to preserve authentication state.
        """
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("Launching persistent browser context…")
        logger.info("  Profile dir: %s", BROWSER_PROFILE_DIR)

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=BROWSER_HEADLESS,
            accept_downloads=BROWSER_ACCEPT_DOWNLOADS,
            args=BROWSER_ARGS,
            viewport=BROWSER_VIEWPORT,
            downloads_path=str(TEMP_DOWNLOAD_DIR),
        )

        # Set default timeouts
        self._context.set_default_timeout(PAGE_LOAD_TIMEOUT_MS)
        self._context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)

        # Use the first existing page or create one
        pages = self._context.pages
        self._page = pages[-1] if pages else self._context.new_page()

        logger.info("Browser launched successfully.")
        return self._page

    def stop(self) -> None:
        """Close the browser context gracefully, preserving the profile."""
        try:
            if self._context:
                self._context.close()
                logger.info("Browser context closed.")
        except Exception as exc:
            logger.warning("Error closing browser context: %s", exc)
        finally:
            if self._playwright:
                self._playwright.stop()
            self._context = None
            self._page = None
            self._playwright = None

    # ── Authentication ──────────────────────────

    def ensure_authenticated(self, target_url: Optional[str] = None) -> Page:
        """Navigate to the target URL and ensure the session is authenticated.

        Flow:
            1. Navigate directly to the authenticated page.
            2. Wait for it to load (government portal can be slow).
            3. If authenticated → return immediately.
            4. If redirected to login → tell user to log in manually.
            5. Wait up to LOGIN_WAIT_TIMEOUT_MS for manual login.
            6. After login, navigate back to target URL.
            7. If timeout → raise SessionExpiredError.

        Returns:
            The authenticated Page object.
        """
        url = target_url or TRACES_DOWNLOAD_CERT_URL
        page = self.page

        if (page.url.rstrip('/') == url.rstrip('/') or url == TRACES_AUTH_URL) and self._is_authenticated(page):
            logger.info("Reusing the authenticated target page.")
            return page

        logger.info("Navigating to: %s", url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightError as exc:
            logger.warning("Navigation slow or timed out: %s — will check page state.", exc)

        # Give the portal a moment to settle (redirects, JS rendering)
        page.wait_for_timeout(3000)

        if self._is_authenticated(page):
            logger.info("✓ Session is authenticated. Continuing…")
            return page

        # Session expired — need manual login
        logger.warning("Session expired or not authenticated.")
        logger.info("=" * 60)
        logger.info("  MANUAL LOGIN REQUIRED")
        logger.info("  Please complete login in the browser window.")
        logger.info("  The automation will wait up to %d seconds.",
                     LOGIN_WAIT_TIMEOUT_MS // 1000)
        logger.info("=" * 60)

        # Navigate to login page if not already there
        if page.url.rstrip("/") != TRACES_LOGIN_URL.rstrip("/"):
            try:
                page.goto(TRACES_LOGIN_URL, wait_until="domcontentloaded",
                          timeout=PAGE_LOAD_TIMEOUT_MS)
                page.wait_for_timeout(3000)
            except PlaywrightError:
                pass  # Best-effort — page may already show login

        # Wait for the user to complete login
        authenticated = self._wait_for_authentication(page)
        if not authenticated:
            logger.error("Authentication not completed within timeout.")
            raise SessionExpiredError(
                f"User did not complete login within {LOGIN_WAIT_TIMEOUT_MS // 1000}s. "
                "Please run the automation again after logging in."
            )

        # Login can replace the original tab. Continue with the page where
        # authentication was actually detected.
        page = self.page

        # Post-login: navigate to the target page
        logger.info("✓ Authentication detected. Navigating to target page…")
        try:
            if url != TRACES_AUTH_URL and page.url.rstrip('/') != url.rstrip('/'):
                page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_timeout(3000)
        except PlaywrightError as exc:
            logger.warning("Post-login navigation issue: %s", exc)

        if not self._is_authenticated(page):
            raise SessionExpiredError("Target page did not show an authenticated session after login.")
        return page

    def check_session_alive(self) -> bool:
        """Quick check — is the current page still authenticated?

        Use this mid-run to detect session expiry gracefully.
        """
        try:
            return self._is_authenticated(self.page)
        except Exception:
            return False

    # ── Internal helpers ────────────────────────

    def _is_authenticated(self, page: Page) -> bool:
        """Detect whether the page shows an authenticated TRACES session.

        Checks for:
            1. Logout link/button (primary indicator)
            2. Absence of login form elements
        """
        try:
            if page.get_by_text("GoException", exact=False).count() or page.get_by_text(
                "Page Not Found", exact=True
            ).count():
                return False
            page_title = page.title()
            body_text = page.locator("body").inner_text(timeout=1000)
            semantic_texts = page.locator("flt-semantics").all_inner_texts()
            error_parts = [
                value for value in (page_title, body_text)
                if isinstance(value, str)
            ]
            if isinstance(semantic_texts, list):
                error_parts.extend(
                    value for value in semantic_texts if isinstance(value, str)
                )
            error_text = " ".join(error_parts)
            if "GoException" in error_text or "Page Not Found" in error_text:
                return False
            if self._is_on_login_page(page):
                return False
            if page.url.rstrip('/') == TRACES_AUTH_URL:
                from automation.portal_utils import enable_flutter_semantics
                enable_flutter_semantics(page)
                menu = page.get_by_role("button", name=re.compile(r"Services Menu", re.I))
                return menu.count() > 0 and menu.first.is_visible()
            # Primary: look for logout element
            logout_el = page.locator(SELECTORS["auth_indicator"])
            if logout_el.count() > 0 and logout_el.first.is_visible():
                return True

            # Fallback: text-based logout link
            logout_alt = page.locator(SELECTORS["auth_indicator_alt"])
            if logout_alt.count() > 0 and logout_alt.first.is_visible():
                return True

            # Check URL for dashboard/authenticated patterns
            current_url = page.url.lower()
            if any(kw in current_url for kw in [
                "dashboard", "downloadcert", "downloadchildcertificate",
                "services", "deductor", "viewldcndc",
            ]):
                # URL suggests authenticated page — verify no login form
                if not self._is_on_login_page(page):
                    return True

        except PlaywrightError as exc:
            logger.debug("Auth check failed: %s", exc)

        return False

    def _is_on_login_page(self, page: Page) -> bool:
        """Detect whether the page is showing a login form."""
        try:
            login_el = page.locator(SELECTORS["login_indicator"])
            if login_el.count() > 0:
                return True

            login_alt = page.locator(SELECTORS["login_indicator_alt"])
            if login_alt.count() > 0:
                return True

            # URL-based fallback — match the /login/ path segment specifically
            # to avoid false-positives on authenticated URLs.
            if "/login/" in page.url.lower():
                return True

        except PlaywrightError:
            pass

        return False

    def _wait_for_authentication(self, page: Page) -> bool:
        """Poll for authentication indicators until timeout.

        Returns True if authentication is detected, False on timeout.
        """
        poll_interval_ms = 3000
        elapsed_ms = 0

        while elapsed_ms < LOGIN_WAIT_TIMEOUT_MS:
            time.sleep(poll_interval_ms / 1000)
            elapsed_ms += poll_interval_ms

            open_pages = [candidate for candidate in self.context.pages if not candidate.is_closed()]
            if not open_pages:
                logger.warning("Waiting for the TRACES login page to reopen.")
                continue

            # Login may open or replace a tab. Prefer the newest authenticated
            # page and remember it for the rest of the workflow.
            for candidate in reversed(open_pages):
                if self._is_authenticated(candidate):
                    self._page = candidate
                    return True

            page = open_pages[-1]
            self._page = page

            # Also check if URL has changed away from login
            if not self._is_on_login_page(page) and "traces.tdscpc.gov.in" in page.url:
                # Might have navigated to an authenticated page
                time.sleep(2)
                if self._is_authenticated(page):
                    self._page = page
                    return True

            if elapsed_ms % 30_000 < poll_interval_ms:
                remaining = (LOGIN_WAIT_TIMEOUT_MS - elapsed_ms) // 1000
                logger.info("  Waiting for login… (%ds remaining)", remaining)

        return False
