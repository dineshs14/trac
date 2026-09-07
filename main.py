#!/usr/bin/env python3
"""
TRACES Automation — Main Entry Point

Usage:
    python main.py --task lower-download --fy 2026-27
    python main.py --task child-download  --fy 2026-27
    python main.py --task services-update --fy 2026-27
    python main.py --task all             --fy 2026-27
    python main.py --task retry-failed    --fy 2026-27
    python main.py --task inspect         --fy 2026-27   # Print DOM selectors for verification
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from config import CERT_TYPE_LOWER_TDS, CERT_TYPE_CHILD
from utils.logger import logger
from utils.file_utils import ensure_directories
from data.tracker_store import TrackerStore
from data.master_tracker import MasterTracker
from data.process_tracker import ProcessTracker, FailedRecordsTracker
from data.models import RunSummary
from automation.session_manager import SessionManager, SessionExpiredError


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="TRACES Lower/Nil TDS Certificate Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Tasks:
  lower-download   Download Lower TDS certificates
  child-download   Download Child certificates under Rule 213(9)
  services-update  Update certificate details from Services page
  all              Run lower-download + child-download + services-update
  retry-failed     Reset FAILED/VALIDATION_FAILED records and retry
  inspect          Print page DOM structure for selector verification
        """,
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the interactive GUI dashboard",
    )
    parser.add_argument(
        "--task",
        required=False,
        choices=[
            "lower-download",
            "child-download",
            "services-update",
            "all",
            "retry-failed",
            "inspect",
        ],
        help="Task to execute",
    )
    parser.add_argument(
        "--fy",
        required=False,
        default="2026-27",
        help="Financial Year (e.g. 2026-27, default: 2026-27)",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # If --gui or no task is specified, launch GUI dashboard
    if args.gui or not args.task:
        from gui import TracesAutomationGUI
        app = TracesAutomationGUI()
        app.run()
        return

    task = args.task
    fy = args.fy

    logger.info("=" * 60)
    logger.info("  TRACES AUTOMATION STARTED")
    logger.info("  Task: %s | FY: %s", task, fy)
    logger.info("  Time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    # ── Phase 1: Initialize ──
    ensure_directories()
    tracker = TrackerStore()
    master = MasterTracker()
    process_tracker = ProcessTracker()
    failed_tracker = FailedRecordsTracker()

    # ── Handle retry-failed (no browser needed for the reset) ──
    if task == "retry-failed":
        count = tracker.reset_failed_to_discovered(fy)
        logger.info("Reset %d failed records to DISCOVERED. Re-run the download task.", count)
        return

    # ── Launch browser ──
    session = SessionManager()
    try:
        session.start()

        if task == "inspect":
            _run_inspect(session, fy)
            return

        # Ensure authentication
        from config import (
            TRACES_CHILD_CERT_URL,
            TRACES_DOWNLOAD_CERT_URL,
            TRACES_DASHBOARD_URL,
        )

        target_url = (
            TRACES_DASHBOARD_URL
            if task == "services-update"
            else TRACES_CHILD_CERT_URL
            if task == "child-download"
            else TRACES_DOWNLOAD_CERT_URL
        )
        session.ensure_authenticated(target_url)

        # ── Execute tasks ──
        summaries: list[RunSummary] = []

        if task in ("lower-download", "all"):
            from automation.lower_tds_downloader import LowerTDSDownloader

            downloader = LowerTDSDownloader(
                page=session.page,
                fy=fy,
                db=tracker,
                master=master,
                process_tracker=process_tracker,
                failed_tracker=failed_tracker,
            )
            summaries.append(downloader.run())

        if task in ("child-download", "all"):
            from automation.child_certificate_downloader import ChildCertificateDownloader

            # Re-authenticate if needed for child download
            session.ensure_authenticated(TRACES_CHILD_CERT_URL)

            downloader = ChildCertificateDownloader(
                page=session.page,
                fy=fy,
                db=tracker,
                master=master,
                process_tracker=process_tracker,
                failed_tracker=failed_tracker,
            )
            summaries.append(downloader.run())

        if task in ("services-update", "all"):
            from automation.services_updater import ServicesUpdater

            # Re-authenticate for services page
            session.ensure_authenticated(TRACES_DASHBOARD_URL)

            updater = ServicesUpdater(
                page=session.page,
                fy=fy,
                db=tracker,
                master=master,
            )
            summaries.append(updater.run())

        # ── Print combined summary ──
        if len(summaries) > 1:
            combined = _combine_summaries(summaries, task, fy)
            logger.info(combined.print_summary())

        if any(s.failed or s.validation_failed for s in summaries):
            sys.exit(1)

    except SessionExpiredError as exc:
        logger.error("Authentication failed: %s", exc)
        logger.info("Please log in to TRACES manually and run again.")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user. State preserved — safe to resume.")
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        session.stop()
        logger.info("Browser closed. Automation finished.")


def _run_inspect(session: SessionManager, fy: str) -> None:
    """Inspect mode: print DOM structure for selector verification."""
    from automation.portal_utils import print_page_selectors, print_accessible_tree

    page = session.page
    session.ensure_authenticated()

    logger.info("=" * 60)
    logger.info("  DOM INSPECTION MODE")
    logger.info("=" * 60)

    result = print_page_selectors(page)
    logger.info("Buttons found: %d", len(result.get("buttons", [])))
    for btn in result.get("buttons", []):
        logger.info("  Button: id=%s text='%s' visible=%s",
                     btn["id"], btn["text"], btn["visible"])

    logger.info("Dropdowns found: %d", len(result.get("dropdowns", [])))
    for sel in result.get("dropdowns", []):
        logger.info("  Dropdown: id=%s name=%s visible=%s",
                     sel["id"], sel["name"], sel["visible"])

    logger.info("Links found: %d", len(result.get("links", [])))
    for lnk in result.get("links", [])[:20]:
        logger.info("  Link: text='%s' href='%s'", lnk["text"], lnk["href"])

    # Keep browser open for manual inspection
    logger.info("\nBrowser is open for manual inspection.")
    logger.info("Press Ctrl+C to close.")
    try:
        while True:
            page.wait_for_timeout(5000)
    except KeyboardInterrupt:
        pass


def _combine_summaries(summaries: list, task: str, fy: str) -> RunSummary:
    """Combine multiple RunSummary objects into one."""
    combined = RunSummary(task=task, financial_year=fy)
    combined.run_start = summaries[0].run_start
    combined.run_end = summaries[-1].run_end

    for s in summaries:
        combined.portal_records_discovered += s.portal_records_discovered
        combined.already_completed += s.already_completed
        combined.new_records += s.new_records
        combined.downloads_initiated += s.downloads_initiated
        combined.downloads_successful += s.downloads_successful
        combined.master_rows_added += s.master_rows_added
        combined.master_rows_updated += s.master_rows_updated
        combined.services_records_updated += s.services_records_updated
        combined.failed += s.failed
        combined.validation_failed += s.validation_failed
        combined.skipped_duplicates += s.skipped_duplicates

    return combined


if __name__ == "__main__":
    main()
