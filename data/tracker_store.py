"""
TRACES Automation — Excel-based Tracker Store

Replaces SQLite with a pure-Excel tracking approach.
Uses automation_tracker.xlsx as the single source of truth for
certificate processing state, resumability, and deduplication.

Thread-safe via file-locking pattern (load → modify → save).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.worksheet import Worksheet

from config import AUTOMATION_TRACKER_FILE, STATUS_COMPLETED
from utils.excel_save import save_workbook
from utils.logger import logger

# ──────────────────────────────────────────────
# Tracker Column Definitions
# ──────────────────────────────────────────────
TRACKER_COLUMNS = [
    "Unique_Key",
    "Certificate_Type",
    "Financial_Year",
    "PAN",
    "Certificate_Number",
    "Portal_Page",
    "Status",
    "ARN_Request_Number",
    "Initiated_At",
    "Original_Filename",
    "Final_Filename",
    "PDF_Path",
    "Downloaded_At",
    "Extraction_Status",
    "Master_Update_Status",
    "Services_Update_Status",
    "Retry_Count",
    "Last_Attempt_At",
    "Error_Message",
    "Created_At",
    "Updated_At",
]

SHEET_NAME = "Tracker"


_CANONICAL_MAP = {c.lower().replace("_", ""): c for c in TRACKER_COLUMNS}


class CaseInsensitiveDict(dict):
    """Dictionary that allows key lookups ignoring case and underscores."""

    def __getitem__(self, key: Any) -> Any:
        try:
            return super().__getitem__(key)
        except KeyError:
            norm_key = str(key).lower().replace("_", "")
            for k, v in self.items():
                if str(k).lower().replace("_", "") == norm_key:
                    return v
            raise KeyError(key)

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


def _canonical_col(col_name: str) -> Optional[str]:
    """Map any column name variation (e.g. arn_request_number) to canonical column."""
    if col_name in TRACKER_COLUMNS:
        return col_name
    norm = str(col_name).lower().replace("_", "")
    return _CANONICAL_MAP.get(norm)


class TrackerStore:
    """Excel-based certificate processing tracker.

    All operations load the file, modify in-memory, and save back.
    This is safe for single-process use (which this automation is).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or AUTOMATION_TRACKER_FILE
        self._ensure_workbook()
        # In-memory cache for faster lookups (key → row_data dict)
        self._cache: Dict[str, CaseInsensitiveDict] = {}
        self._cache_loaded = False

    # ── Initialization ──────────────────────────

    def _ensure_workbook(self) -> None:
        """Create the workbook if it doesn't exist."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            return

        wb = Workbook()
        ws: Worksheet = wb.active  # type: ignore
        ws.title = SHEET_NAME

        header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=10)

        for col_idx, col_name in enumerate(TRACKER_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.column_dimensions[cell.column_letter].width = max(len(col_name) + 2, 14)

        ws.freeze_panes = "A2"
        save_workbook(wb, self.path)
        logger.debug("Created tracker workbook: %s", self.path)

    def _col_index(self, col_name: str) -> int:
        """Return 1-based column index."""
        canon = _canonical_col(col_name)
        if canon and canon in TRACKER_COLUMNS:
            return TRACKER_COLUMNS.index(canon) + 1
        return TRACKER_COLUMNS.index(col_name) + 1

    # ── Cache Management ────────────────────────

    def _load_cache(self) -> None:
        """Load all rows into memory for fast lookups."""
        self._cache.clear()
        wb = load_workbook(str(self.path))
        ws = wb[SHEET_NAME]

        for row_num in range(2, ws.max_row + 1):
            key = str(ws.cell(row=row_num, column=self._col_index("Unique_Key")).value or "")
            if not key:
                continue
            row_data = CaseInsensitiveDict({"_row_num": row_num})
            for col_name in TRACKER_COLUMNS:
                col_idx = self._col_index(col_name)
                row_data[col_name] = ws.cell(row=row_num, column=col_idx).value or ""
            self._cache[key] = row_data

        self._cache_loaded = True
        wb.close()

    def _ensure_cache(self) -> None:
        """Load cache if not already loaded."""
        if not self._cache_loaded:
            self._load_cache()

    def refresh_cache(self) -> None:
        """Force reload the cache from the Excel file."""
        self._cache_loaded = False
        self._load_cache()

    # ── Read Operations ─────────────────────────

    def get_by_key(self, unique_key: str) -> Optional[Dict[str, Any]]:
        """Return row data for a unique key, or None."""
        self._ensure_cache()
        return self._cache.get(unique_key)

    def is_completed(self, unique_key: str) -> bool:
        """Check whether a certificate has been fully processed."""
        row = self.get_by_key(unique_key)
        return row is not None and row.get("Status") == STATUS_COMPLETED

    def get_all_by_status(
        self, status: str, fy: Optional[str] = None, cert_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return all rows matching a given status."""
        self._ensure_cache()
        results = []
        for row in self._cache.values():
            if row.get("Status") != status:
                continue
            if fy and row.get("Financial_Year") != fy:
                continue
            if cert_type and row.get("Certificate_Type") != cert_type:
                continue
            results.append(row)
        return results

    def get_all_for_fy(self, fy: str, cert_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all rows for a financial year."""
        self._ensure_cache()
        results = []
        for row in self._cache.values():
            if row.get("Financial_Year") != fy:
                continue
            if cert_type and row.get("Certificate_Type") != cert_type:
                continue
            results.append(row)
        return results

    def count_by_status(self, fy: str, cert_type: Optional[str] = None) -> Dict[str, int]:
        """Return {status: count} for a given FY."""
        self._ensure_cache()
        counts: Dict[str, int] = {}
        for row in self._cache.values():
            if row.get("Financial_Year") != fy:
                continue
            if cert_type and row.get("Certificate_Type") != cert_type:
                continue
            status = row.get("Status", "UNKNOWN")
            counts[status] = counts.get(status, 0) + 1
        return counts

    # ── Write Operations ────────────────────────

    def upsert_discovered(
        self,
        unique_key: str,
        certificate_type: str,
        financial_year: str,
        pan: str,
        certificate_number: str,
        portal_page: int = 0,
    ) -> bool:
        """Insert a DISCOVERED record if it doesn't already exist.

        Returns True if new, False if already exists.
        """
        self._ensure_cache()
        if unique_key in self._cache:
            return False

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_data = CaseInsensitiveDict({
            "Unique_Key": unique_key,
            "Certificate_Type": certificate_type,
            "Financial_Year": financial_year,
            "PAN": pan,
            "Certificate_Number": certificate_number,
            "Portal_Page": str(portal_page),
            "Status": "DISCOVERED",
            "Retry_Count": "0",
            "Created_At": now,
            "Updated_At": now,
        })

        wb = load_workbook(str(self.path))
        ws = wb[SHEET_NAME]
        new_row = ws.max_row + 1

        for col_name in TRACKER_COLUMNS:
            col_idx = self._col_index(col_name)
            ws.cell(row=new_row, column=col_idx, value=row_data.get(col_name, ""))

        save_workbook(wb, self.path)
        wb.close()

        # Update cache
        row_data["_row_num"] = new_row
        self._cache[unique_key] = row_data
        return True

    def update_status(
        self,
        unique_key: str,
        status: str,
        **extra_fields: str,
    ) -> None:
        """Update the status and any extra columns for a record."""
        self._ensure_cache()
        row = self._cache.get(unique_key)
        if row is None:
            logger.warning("Cannot update non-existent key: %s", unique_key)
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        excel_row = row["_row_num"]

        wb = load_workbook(str(self.path))
        ws = wb[SHEET_NAME]

        ws.cell(row=excel_row, column=self._col_index("Status"), value=status)
        ws.cell(row=excel_row, column=self._col_index("Updated_At"), value=now)

        for col_name, val in extra_fields.items():
            canon = _canonical_col(col_name)
            if canon:
                ws.cell(row=excel_row, column=self._col_index(canon), value=val)
                row[canon] = val

        save_workbook(wb, self.path)
        wb.close()

        # Update cache
        row["Status"] = status
        row["Updated_At"] = now

    def increment_retry(self, unique_key: str, error_message: str = "") -> int:
        """Bump retry count and store error. Returns new count."""
        self._ensure_cache()
        row = self._cache.get(unique_key)
        if row is None:
            return 0

        current = int(row.get("Retry_Count", 0) or 0)
        new_count = current + 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.update_status(
            unique_key,
            row.get("Status", "FAILED"),
            Retry_Count=str(new_count),
            Last_Attempt_At=now,
            Error_Message=error_message,
        )
        return new_count

    def mark_failed(self, unique_key: str, error: str) -> None:
        """Mark a record as FAILED with error details."""
        self.update_status(
            unique_key,
            "FAILED",
            Error_Message=error,
            Last_Attempt_At=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def reset_failed_to_discovered(self, fy: str, cert_type: Optional[str] = None) -> int:
        """Reset all FAILED/VALIDATION_FAILED records back to DISCOVERED.

        Returns count of reset records.
        """
        self._ensure_cache()
        count = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        wb = load_workbook(str(self.path))
        ws = wb[SHEET_NAME]

        for key, row in self._cache.items():
            if row.get("Financial_Year") != fy:
                continue
            if cert_type and row.get("Certificate_Type") != cert_type:
                continue
            if row.get("Status") in ("FAILED", "VALIDATION_FAILED"):
                excel_row = row["_row_num"]
                ws.cell(row=excel_row, column=self._col_index("Status"), value="DISCOVERED")
                ws.cell(row=excel_row, column=self._col_index("Updated_At"), value=now)
                row["Status"] = "DISCOVERED"
                row["Updated_At"] = now
                count += 1

        if count > 0:
            save_workbook(wb, self.path)
        wb.close()

        logger.info("Reset %d failed records to DISCOVERED for FY %s", count, fy)
        return count
