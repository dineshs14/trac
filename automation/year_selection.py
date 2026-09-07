"""Verified year selection for the Flutter accessibility controls."""

import re

from playwright.sync_api import Page, Locator, Error as PlaywrightError, expect

from automation.portal_utils import ElementNotFoundError
from config import ELEMENT_WAIT_TIMEOUT_MS
from utils.logger import logger


def _click_flutter_surface(page: Page, control: Locator) -> None:
    """Route a click through Flutter's inert semantic overlay to its canvas.

    CPCTDS's year dropdown ignores semantic taps. Use its measured bounds and
    temporarily make only the accessibility overlay transparent to pointer input.
    """
    control.scroll_into_view_if_needed()
    box = control.bounding_box()
    if not box:
        raise ElementNotFoundError("Year dropdown has no visible bounds")
    point = {"x": box["x"] + box["width"] / 2,
             "y": box["y"] + box["height"] / 2}
    style = page.add_style_tag(content=(
        "flt-semantics-host, flt-semantics-host * "
        "{ pointer-events: none !important; }"
    ))
    try:
        on_flutter = page.evaluate("""pt => {
            const el = document.elementFromPoint(pt.x, pt.y);
            return !!el && (el.matches('flutter-view, flt-glass-pane, canvas') ||
                !!el.closest('flutter-view, flt-glass-pane'));
        }""", point)
        if not on_flutter:
            raise ElementNotFoundError("Year dropdown is covered by a non-Flutter element")
        page.mouse.click(**point)
    finally:
        style.evaluate("el => el.remove()")


def select_flutter_year(page: Page, fy: str) -> None:
    """Select the filter radio and year; never infer selection from result cards."""
    if not re.fullmatch(r"\d{4}-\d{2}", fy):
        raise ValueError(f"Expected financial year YYYY-YY, got {fy!r}")
    timeout = ELEMENT_WAIT_TIMEOUT_MS
    try:
        # Captured portal DOM puts the label on a group, not on its radio.
        radio = page.get_by_role("radio", name="Tax/Financial Year", exact=True).or_(
            page.locator('flt-semantics[aria-label="Tax/Financial Year"] [role="radio"]')
        )
        expect(radio).to_have_count(1, timeout=timeout)
        if radio.get_attribute("aria-checked") != "true":
            radio.click(timeout=timeout)
        expect(radio).to_have_attribute("aria-checked", "true", timeout=timeout)

        # Scope to year controls: the page also has language/pagination dropdowns.
        year_name = re.compile(r"(?:Tax|Financial)\s*Year", re.I)
        combo = page.get_by_role("combobox", name=year_name).or_(
            page.get_by_role("button", name=year_name)
        )
        expect(combo).to_have_count(1, timeout=timeout)
        selected_year = re.compile(r"(?<!\d)" + re.escape(fy) + r"(?!\d)")

        def is_selected() -> bool:
            return bool(selected_year.search(" ".join([
                combo.inner_text(), combo.get_attribute("aria-label") or "",
                combo.get_attribute("aria-valuetext") or "",
            ])))

        if not is_selected():
            combo.click(timeout=timeout)
            # Live Flutter options include selection state and item position.
            option_name = re.compile(
                r"^" + re.escape(fy) + r"(?:\s+(?:not selected|selected)\s+\d+\s+of\s+\d+)?$"
            )
            option = page.get_by_role("option", name=fy, exact=True).or_(
                page.get_by_role("menuitem", name=fy, exact=True)
            ).or_(page.get_by_role("button", name=option_name))
            try:
                expect(option).to_have_count(1, timeout=min(timeout, 1000))
            except AssertionError:
                # The closed control disappears from semantics when the menu opens.
                other_options = page.get_by_role("option").or_(
                    page.get_by_role("menuitem")
                ).or_(page.get_by_role("button", name=re.compile(
                    r"^\d{4}-\d{2}(?:\s+(?:not selected|selected)\s+\d+\s+of\s+\d+)?$"
                )))
                if (other_options.count() == 0 and combo.count() == 1
                        and "collapsed" in combo.inner_text()):
                    logger.info("Opening Tax Year through the Flutter surface.")
                    _click_flutter_surface(page, combo)
            expect(option).to_have_count(1, timeout=timeout)
            option.click(timeout=timeout)
            # Poll the control itself because Flutter rebuilds the semantic nodes.
            elapsed = 0
            while not is_selected() and elapsed < timeout:
                page.wait_for_timeout(100)
                elapsed += 100
            if not is_selected():
                raise ElementNotFoundError(f"Year control did not confirm {fy} after selection")
        logger.info("Confirmed Tax/Financial Year selection: %s", fy)
    except (PlaywrightError, AssertionError) as exc:
        raise ElementNotFoundError(
            f"Could not select Tax/Financial Year {fy}. "
            "Stopped to avoid processing certificates for the wrong year. "
            "Inspect the year radio, dropdown and option accessibility labels."
        ) from exc


def select_flutter_child_year(page: Page, fy: str) -> None:
    """Select Tax Year on the dedicated Child Certificate page."""
    if not re.fullmatch(r"\d{4}-\d{2}", fy):
        raise ValueError(f"Expected financial year YYYY-YY, got {fy!r}")
    timeout = ELEMENT_WAIT_TIMEOUT_MS
    try:
        combo = page.locator(
            'flt-semantics[aria-label="Tax year dropdown"] [role="button"]'
        )
        expect(combo).to_have_count(1, timeout=timeout)
        selected_year = re.compile(r"(?<!\d)" + re.escape(fy) + r"(?!\d)")

        def is_selected() -> bool:
            return bool(selected_year.search(" ".join([
                combo.inner_text(),
                combo.get_attribute("aria-label") or "",
                combo.get_attribute("aria-valuetext") or "",
            ])))

        if not is_selected():
            _click_flutter_surface(page, combo)
            option_name = re.compile(
                r"^" + re.escape(fy)
                + r"(?:\s+(?:not selected|selected)\s+\d+\s+of\s+\d+)?$"
            )
            option = page.get_by_role("option", name=fy, exact=True).or_(
                page.get_by_role("menuitem", name=fy, exact=True)
            ).or_(page.get_by_role("button", name=option_name))
            expect(option).to_have_count(1, timeout=timeout)
            option.click(force=True)

            elapsed = 0
            while not is_selected() and elapsed < timeout:
                page.wait_for_timeout(100)
                elapsed += 100
            if not is_selected():
                raise ElementNotFoundError(
                    f"Child Certificate Tax Year did not confirm {fy}."
                )
        logger.info("Confirmed Child Certificate Tax Year: %s", fy)
    except (PlaywrightError, AssertionError) as exc:
        raise ElementNotFoundError(
            f"Could not select Child Certificate Tax Year {fy}."
        ) from exc


def select_flutter_services_year(page: Page, fy: str) -> None:
    """Select the Services form's Tax/Financial Year dropdown."""
    if not re.fullmatch(r"\d{4}-\d{2}", fy):
        raise ValueError(f"Expected financial year YYYY-YY, got {fy!r}")
    timeout = ELEMENT_WAIT_TIMEOUT_MS
    try:
        year_name = re.compile(r"Tax.*Financial Year", re.I)
        combo = page.get_by_role("combobox", name=year_name).or_(
            page.get_by_role("button", name=year_name)
        )
        expect(combo).to_have_count(1, timeout=timeout)
        selected_year = re.compile(r"(?<!\d)" + re.escape(fy) + r"(?!\d)")

        def is_selected() -> bool:
            return bool(selected_year.search(" ".join([
                combo.inner_text(), combo.get_attribute("aria-label") or "",
                combo.get_attribute("aria-valuetext") or "",
            ])))

        if not is_selected():
            _click_flutter_surface(page, combo)
            option_name = re.compile(
                r"^" + re.escape(fy)
                + r"(?:\s+(?:not selected|selected)\s+\d+\s+of\s+\d+)?$"
            )
            option = page.get_by_role("option", name=fy, exact=True).or_(
                page.get_by_role("menuitem", name=fy, exact=True)
            ).or_(page.get_by_role("button", name=option_name))
            expect(option).to_have_count(1, timeout=timeout)
            option.click(force=True)

            elapsed = 0
            while not is_selected() and elapsed < timeout:
                page.wait_for_timeout(100)
                elapsed += 100
            if not is_selected():
                raise ElementNotFoundError(
                    f"Services Tax/Financial Year did not confirm {fy}."
                )
        logger.info("Confirmed Services Tax/Financial Year: %s", fy)
    except (PlaywrightError, AssertionError) as exc:
        raise ElementNotFoundError(
            f"Could not select Services Tax/Financial Year {fy}."
        ) from exc
