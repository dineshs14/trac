"""
TRACES Automation — GUI Application

Yellow + White themed Tkinter dashboard for manager use.
Features:
    - Task buttons (Lower TDS, Child, Services, Retry Failed, All)
    - Financial Year selector
    - Live progress bar
    - Certificate table view
    - Scrollable log viewer
    - Status count cards
    - No command-line knowledge required
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    CERT_TYPE_LOWER_TDS,
    CERT_TYPE_CHILD,
    TRACES_AUTH_URL,
    TRACES_CHILD_CERT_URL,
    TRACES_DOWNLOAD_CERT_URL,
    TRACES_DASHBOARD_URL,
)
from utils.logger import setup_logger
from utils.file_utils import ensure_directories
from data.tracker_store import TrackerStore
from data.master_tracker import MasterTracker
from data.process_tracker import ProcessTracker, FailedRecordsTracker
from data.models import RunSummary


# ──────────────────────────────────────────────
# Theme Colors
# ──────────────────────────────────────────────
YELLOW = "#F5C518"
YELLOW_DARK = "#D4A817"
YELLOW_LIGHT = "#FFF9E0"
WHITE = "#FFFFFF"
BG_COLOR = "#FEFDF5"
TEXT_COLOR = "#333333"
TEXT_MUTED = "#777777"
SUCCESS_GREEN = "#28A745"
FAIL_RED = "#DC3545"
INFO_BLUE = "#17A2B8"
CARD_SHADOW = "#E8E4D4"
HEADER_BG = "#F5C518"
BUTTON_FG = "#1A1A1A"
FONT_FAMILY = "Segoe UI"


class TextHandler(logging.Handler):
    """Logging handler that writes to a Tkinter ScrolledText widget."""

    def __init__(self, text_widget: scrolledtext.ScrolledText) -> None:
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        try:
            self.text_widget.after(0, self._append, msg, record.levelno)
        except Exception:
            pass

    def _append(self, msg: str, level: int) -> None:
        self.text_widget.configure(state="normal")
        tag = "info"
        if level >= logging.ERROR:
            tag = "error"
        elif level >= logging.WARNING:
            tag = "warning"
        elif level <= logging.DEBUG:
            tag = "debug"
        self.text_widget.insert(tk.END, msg, tag)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")


class TracesAutomationGUI:
    """Main GUI application window."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("TRACES Certificate Automation")
        self.root.geometry("1280x800")
        self.root.minsize(1000, 700)
        self.root.configure(bg=BG_COLOR)

        # Set icon if available
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        # State
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._session_manager = None

        # Initialize infrastructure
        ensure_directories()
        self.tracker = TrackerStore()
        self.master = MasterTracker()
        self.process_tracker = ProcessTracker()
        self.failed_tracker = FailedRecordsTracker()

        self._build_ui()
        self._setup_logging()
        self._update_status_cards()

    # ──────────────────────────────────────────
    # UI Construction
    # ──────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build the complete UI layout."""
        # ── Header Bar ──
        header = tk.Frame(self.root, bg=YELLOW, height=70)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        title_label = tk.Label(
            header,
            text="🏛️  TRACES Certificate Automation",
            font=(FONT_FAMILY, 18, "bold"),
            bg=YELLOW,
            fg=BUTTON_FG,
        )
        title_label.pack(side=tk.LEFT, padx=20, pady=15)

        subtitle = tk.Label(
            header,
            text="Lower/Nil TDS Certificate Management",
            font=(FONT_FAMILY, 10),
            bg=YELLOW,
            fg="#555555",
        )
        subtitle.pack(side=tk.LEFT, padx=10, pady=15)

        # Status indicator
        self._status_label = tk.Label(
            header,
            text="● Ready",
            font=(FONT_FAMILY, 11, "bold"),
            bg=YELLOW,
            fg=SUCCESS_GREEN,
        )
        self._status_label.pack(side=tk.RIGHT, padx=20, pady=15)

        # ── Main Content ──
        main_frame = tk.Frame(self.root, bg=BG_COLOR)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        # Left panel: Controls + Status Cards
        left_panel = tk.Frame(main_frame, bg=BG_COLOR, width=320)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)

        # Right panel: Table + Logs
        right_panel = tk.Frame(main_frame, bg=BG_COLOR)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Left Panel: Controls ──
        self._build_controls(left_panel)
        self._build_status_cards(left_panel)

        # ── Right Panel: Table + Logs ──
        self._build_table(right_panel)
        self._build_log_viewer(right_panel)

        # ── Bottom: Progress Bar ──
        self._build_progress_bar()

    def _build_controls(self, parent: tk.Frame) -> None:
        """Build the control panel with FY selector and task buttons."""
        # Control Card
        card = tk.LabelFrame(
            parent,
            text="  Controls  ",
            font=(FONT_FAMILY, 11, "bold"),
            bg=WHITE,
            fg=TEXT_COLOR,
            bd=1,
            relief=tk.GROOVE,
            padx=15,
            pady=10,
        )
        card.pack(fill=tk.X, pady=(0, 10))

        # Financial Year
        fy_frame = tk.Frame(card, bg=WHITE)
        fy_frame.pack(fill=tk.X, pady=(5, 10))

        tk.Label(
            fy_frame,
            text="Financial Year:",
            font=(FONT_FAMILY, 10, "bold"),
            bg=WHITE,
            fg=TEXT_COLOR,
        ).pack(side=tk.LEFT)

        self._fy_var = tk.StringVar(value="2026-27")
        fy_combo = ttk.Combobox(
            fy_frame,
            textvariable=self._fy_var,
            values=["2024-25", "2025-26", "2026-27", "2027-28"],
            width=12,
            state="readonly",
            font=(FONT_FAMILY, 10),
        )
        fy_combo.pack(side=tk.RIGHT)

        # Task Buttons
        buttons = [
            ("📥  Lower TDS Download", "lower-download", YELLOW),
            ("📥  Child Cert Download", "child-download", YELLOW),
            ("🔄  Services Update", "services-update", YELLOW),
            ("▶️  Run All Tasks", "all", YELLOW_DARK),
            ("🔁  Retry Failed", "retry-failed", "#E8A317"),
        ]

        for text, task, color in buttons:
            btn = tk.Button(
                card,
                text=text,
                command=lambda t=task: self._start_task(t),
                font=(FONT_FAMILY, 10, "bold"),
                bg=color,
                fg=BUTTON_FG,
                activebackground=YELLOW_DARK,
                relief=tk.FLAT,
                cursor="hand2",
                height=1,
                padx=10,
            )
            btn.pack(fill=tk.X, pady=3)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=YELLOW_DARK))
            btn.bind("<Leave>", lambda e, b=btn, c=color: b.configure(bg=c))

        # Separator
        ttk.Separator(card, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Utility Buttons
        util_frame = tk.Frame(card, bg=WHITE)
        util_frame.pack(fill=tk.X)

        stop_btn = tk.Button(
            util_frame,
            text="⏹ Stop",
            command=self._stop_task,
            font=(FONT_FAMILY, 9),
            bg=FAIL_RED,
            fg=WHITE,
            relief=tk.FLAT,
            cursor="hand2",
            width=8,
        )
        stop_btn.pack(side=tk.LEFT, padx=(0, 5))

        refresh_btn = tk.Button(
            util_frame,
            text="🔄 Refresh",
            command=self._refresh_all,
            font=(FONT_FAMILY, 9),
            bg=INFO_BLUE,
            fg=WHITE,
            relief=tk.FLAT,
            cursor="hand2",
            width=8,
        )
        refresh_btn.pack(side=tk.LEFT, padx=5)

        inspect_btn = tk.Button(
            util_frame,
            text="🔍 Inspect",
            command=lambda: self._start_task("inspect"),
            font=(FONT_FAMILY, 9),
            bg="#6C757D",
            fg=WHITE,
            relief=tk.FLAT,
            cursor="hand2",
            width=8,
        )
        inspect_btn.pack(side=tk.LEFT, padx=5)

    def _build_status_cards(self, parent: tk.Frame) -> None:
        """Build status count cards."""
        card = tk.LabelFrame(
            parent,
            text="  Status Summary  ",
            font=(FONT_FAMILY, 11, "bold"),
            bg=WHITE,
            fg=TEXT_COLOR,
            bd=1,
            relief=tk.GROOVE,
            padx=15,
            pady=10,
        )
        card.pack(fill=tk.X, pady=(0, 10))

        self._status_vars = {}
        statuses = [
            ("Discovered", INFO_BLUE),
            ("Completed", SUCCESS_GREEN),
            ("Downloaded", "#6F42C1"),
            ("Failed", FAIL_RED),
            ("Validation Failed", "#FD7E14"),
            ("Total", TEXT_COLOR),
        ]

        for label, color in statuses:
            row = tk.Frame(card, bg=WHITE)
            row.pack(fill=tk.X, pady=2)

            tk.Label(
                row,
                text=f"● {label}:",
                font=(FONT_FAMILY, 9),
                bg=WHITE,
                fg=color,
                anchor="w",
            ).pack(side=tk.LEFT)

            var = tk.StringVar(value="0")
            self._status_vars[label] = var
            tk.Label(
                row,
                textvariable=var,
                font=(FONT_FAMILY, 10, "bold"),
                bg=WHITE,
                fg=color,
                anchor="e",
            ).pack(side=tk.RIGHT)

    def _build_table(self, parent: tk.Frame) -> None:
        """Build the certificate table view."""
        table_frame = tk.LabelFrame(
            parent,
            text="  Certificate Records  ",
            font=(FONT_FAMILY, 11, "bold"),
            bg=WHITE,
            fg=TEXT_COLOR,
            bd=1,
            relief=tk.GROOVE,
        )
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Treeview with scrollbar
        columns = ("Type", "PAN", "Certificate_No", "FY", "Status", "PDF_Path")
        self._tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            height=10,
        )

        # Configure columns
        col_widths = {"Type": 90, "PAN": 110, "Certificate_No": 150,
                      "FY": 70, "Status": 100, "PDF_Path": 300}
        for col in columns:
            self._tree.heading(col, text=col.replace("_", " "))
            self._tree.column(col, width=col_widths.get(col, 100), minwidth=60)

        # Scrollbars
        v_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self._tree.yview)
        h_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X, padx=5)

        # Style the treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                         background=WHITE,
                         foreground=TEXT_COLOR,
                         fieldbackground=WHITE,
                         font=(FONT_FAMILY, 9))
        style.configure("Treeview.Heading",
                         background=YELLOW,
                         foreground=BUTTON_FG,
                         font=(FONT_FAMILY, 9, "bold"))
        style.map("Treeview", background=[("selected", YELLOW_LIGHT)])

    def _build_log_viewer(self, parent: tk.Frame) -> None:
        """Build the scrollable log viewer."""
        log_frame = tk.LabelFrame(
            parent,
            text="  Activity Log  ",
            font=(FONT_FAMILY, 11, "bold"),
            bg=WHITE,
            fg=TEXT_COLOR,
            bd=1,
            relief=tk.GROOVE,
        )
        log_frame.pack(fill=tk.BOTH, expand=True)

        self._log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            state="disabled",
            font=("Consolas", 9),
            bg="#FAFAFA",
            fg=TEXT_COLOR,
            height=8,
            bd=0,
            padx=10,
            pady=5,
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure log tags
        self._log_text.tag_config("info", foreground=TEXT_COLOR)
        self._log_text.tag_config("warning", foreground="#FD7E14")
        self._log_text.tag_config("error", foreground=FAIL_RED, font=("Consolas", 9, "bold"))
        self._log_text.tag_config("debug", foreground=TEXT_MUTED)

    def _build_progress_bar(self) -> None:
        """Build the bottom progress bar."""
        progress_frame = tk.Frame(self.root, bg=WHITE, height=40)
        progress_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=15, pady=(0, 10))

        self._progress_label = tk.Label(
            progress_frame,
            text="Ready",
            font=(FONT_FAMILY, 9),
            bg=WHITE,
            fg=TEXT_MUTED,
        )
        self._progress_label.pack(side=tk.LEFT, padx=10)

        style = ttk.Style()
        style.configure("Yellow.Horizontal.TProgressbar",
                         troughcolor="#E8E4D4",
                         background=YELLOW,
                         thickness=20)

        self._progress = ttk.Progressbar(
            progress_frame,
            style="Yellow.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
        )
        self._progress.pack(fill=tk.X, expand=True, padx=10, pady=8)

        self._progress_pct = tk.Label(
            progress_frame,
            text="0%",
            font=(FONT_FAMILY, 9, "bold"),
            bg=WHITE,
            fg=TEXT_COLOR,
        )
        self._progress_pct.pack(side=tk.RIGHT, padx=10)

    # ──────────────────────────────────────────
    # Logging Integration
    # ──────────────────────────────────────────

    def _setup_logging(self) -> None:
        """Add GUI text handler to the logger."""
        logger = setup_logger()
        handler = TextHandler(self._log_text)
        handler.setLevel(logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        self._logger = logger

    # ──────────────────────────────────────────
    # Task Execution
    # ──────────────────────────────────────────

    def _start_task(self, task: str) -> None:
        """Start a task in a background thread."""
        if self._running:
            messagebox.showwarning("Busy", "A task is already running. Please wait.")
            return

        fy = self._fy_var.get()
        if not fy:
            messagebox.showerror("Error", "Please select a Financial Year.")
            return

        self._running = True
        self._set_status("Running", YELLOW_DARK)
        self._progress["value"] = 0
        self._progress_pct.configure(text="0%")
        self._progress_label.configure(text=f"Running: {task} (FY {fy})")

        self._worker_thread = threading.Thread(
            target=self._run_task_thread,
            args=(task, fy),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_task_thread(self, task: str, fy: str) -> None:
        """Execute the task in a background thread."""
        task_failed = False
        try:
            self._logger.info("Starting task: %s for FY %s", task, fy)

            if task == "retry-failed":
                count = self.tracker.reset_failed_to_discovered(fy)
                self._logger.info("Reset %d failed records. Re-run the download task.", count)
                self._update_progress(100, "Retry reset complete")
                return

            # Import here to avoid circular imports and slow startup
            from automation.session_manager import SessionManager, SessionExpiredError

            self._session_manager = SessionManager()
            page = self._session_manager.start()

            if task == "inspect":
                from automation.portal_utils import print_page_selectors
                self._session_manager.ensure_authenticated()
                result = print_page_selectors(page)
                self._logger.info("Found %d buttons, %d dropdowns, %d links",
                                  len(result.get("buttons", [])),
                                  len(result.get("dropdowns", [])),
                                  len(result.get("links", [])))
                for btn in result.get("buttons", []):
                    self._logger.info("  Button: id='%s' text='%s'", btn["id"], btn["text"])
                self._logger.info("Browser is open for manual inspection. Close when done.")
                # Keep open until stop is clicked
                while self._running:
                    import time
                    time.sleep(1)
                return

            target_url = (
                TRACES_AUTH_URL if task == "services-update"
                else TRACES_CHILD_CERT_URL if task == "child-download"
                else TRACES_DOWNLOAD_CERT_URL
            )
            self._session_manager.ensure_authenticated(target_url)

            summaries = []

            if task in ("lower-download", "all"):
                from automation.lower_tds_downloader import LowerTDSDownloader
                downloader = LowerTDSDownloader(
                    page=self._session_manager.page, fy=fy,
                    db=self.tracker, master=self.master,
                    process_tracker=self.process_tracker,
                    failed_tracker=self.failed_tracker,
                )
                downloader.summary_callback = self._update_progress_from_summary
                summaries.append(downloader.run())
                self._update_progress(50 if task == "all" else 100, "Lower TDS complete")

            if task in ("child-download", "all"):
                self._session_manager.ensure_authenticated(TRACES_CHILD_CERT_URL)
                from automation.child_certificate_downloader import ChildCertificateDownloader
                downloader = ChildCertificateDownloader(
                    page=self._session_manager.page, fy=fy,
                    db=self.tracker, master=self.master,
                    process_tracker=self.process_tracker,
                    failed_tracker=self.failed_tracker,
                )
                summaries.append(downloader.run())
                self._update_progress(75 if task == "all" else 100, "Child certs complete")

            if task in ("services-update", "all"):
                self._session_manager.ensure_authenticated(TRACES_DASHBOARD_URL)
                from automation.services_updater import ServicesUpdater
                updater = ServicesUpdater(
                    page=self._session_manager.page, fy=fy,
                    db=self.tracker, master=self.master,
                )
                summaries.append(updater.run())
                self._update_progress(100, "Services update complete")

            # Print combined summary
            for s in summaries:
                self._logger.info(s.print_summary())
                task_failed = task_failed or bool(s.failed or s.validation_failed)

        except Exception as exc:
            task_failed = True
            self._logger.error("Task failed: %s", exc, exc_info=True)
        finally:
            if self._session_manager:
                try:
                    self._session_manager.stop()
                except Exception:
                    pass
                self._session_manager = None
            self._running = False
            self.root.after(0, self._task_finished, task_failed)

    def _stop_task(self) -> None:
        """Stop the running task."""
        if not self._running:
            return
        self._running = False
        self._logger.info("Stop requested. Task will finish current operation and stop.")
        if self._session_manager:
            try:
                self._session_manager.stop()
            except Exception:
                pass
        self._set_status("Stopped", FAIL_RED)

    def _task_finished(self, failed: bool = False) -> None:
        """Called when a background task completes."""
        self._set_status("Failed" if failed else "Ready", FAIL_RED if failed else SUCCESS_GREEN)
        self._progress_label.configure(text="Task failed - see Activity Log" if failed else "Task completed")
        self._update_status_cards()
        self._refresh_table()

    # ──────────────────────────────────────────
    # UI Updates (thread-safe)
    # ──────────────────────────────────────────

    def _set_status(self, text: str, color: str) -> None:
        """Update the status indicator."""
        self.root.after(0, lambda: self._status_label.configure(
            text=f"● {text}", fg=color
        ))

    def _update_progress(self, value: int, label: str = "") -> None:
        """Update the progress bar (thread-safe)."""
        def _update():
            self._progress["value"] = value
            self._progress_pct.configure(text=f"{value}%")
            if label:
                self._progress_label.configure(text=label)
        self.root.after(0, _update)

    def _update_progress_from_summary(self, current: int, total: int) -> None:
        """Callback for downloaders to update progress."""
        if total > 0:
            pct = int((current / total) * 100)
            self._update_progress(pct, f"Processing {current}/{total}")

    def _update_status_cards(self) -> None:
        """Update the status count cards from the tracker."""
        fy = self._fy_var.get()
        try:
            counts = self.tracker.count_by_status(fy)
            self._status_vars["Discovered"].set(str(counts.get("DISCOVERED", 0)))
            self._status_vars["Completed"].set(str(counts.get("COMPLETED", 0)))
            self._status_vars["Downloaded"].set(str(counts.get("DOWNLOADED", 0)))
            self._status_vars["Failed"].set(str(counts.get("FAILED", 0)))
            self._status_vars["Validation Failed"].set(str(counts.get("VALIDATION_FAILED", 0)))
            total = sum(counts.values())
            self._status_vars["Total"].set(str(total))
        except Exception:
            pass

    def _refresh_table(self) -> None:
        """Refresh the certificate table from the tracker."""
        fy = self._fy_var.get()
        try:
            # Clear existing
            for item in self._tree.get_children():
                self._tree.delete(item)

            rows = self.tracker.get_all_for_fy(fy)
            for row in rows:
                self._tree.insert("", tk.END, values=(
                    row.get("Certificate_Type", ""),
                    row.get("PAN", ""),
                    row.get("Certificate_Number", ""),
                    row.get("Financial_Year", ""),
                    row.get("Status", ""),
                    row.get("PDF_Path", ""),
                ))
        except Exception:
            pass

    def _refresh_all(self) -> None:
        """Refresh all UI elements."""
        self.tracker.refresh_cache()
        self._update_status_cards()
        self._refresh_table()
        self._logger.info("UI refreshed for FY %s", self._fy_var.get())

    # ──────────────────────────────────────────
    # Run
    # ──────────────────────────────────────────

    def run(self) -> None:
        """Start the Tkinter main loop."""
        self._refresh_table()
        self.root.mainloop()


def main():
    """Launch the GUI."""
    app = TracesAutomationGUI()
    app.run()


if __name__ == "__main__":
    main()
