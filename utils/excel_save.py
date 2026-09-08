"""Reliable workbook saving for files that may be open in Microsoft Excel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.logger import logger


class ExcelFileLockedError(RuntimeError):
    """Raised when an open Excel workbook cannot be updated automatically."""


def save_workbook(workbook: Any, path: Path) -> None:
    """Save a workbook, updating live Excel when the file is locked."""
    try:
        workbook.save(str(path))
        return
    except PermissionError:
        logger.warning("Workbook is open or locked: %s", path)

    pending_path = path.with_name(f"{path.stem}.pending{path.suffix}")
    workbook.save(str(pending_path))

    if _save_into_open_excel(pending_path, path):
        pending_path.unlink(missing_ok=True)
        logger.info("Updated and saved the open Excel workbook: %s", path)
        return

    raise ExcelFileLockedError(
        f"Cannot save {path.name} because it is open in Excel. "
        f"The update was preserved at {pending_path.name}; close the workbook "
        "and retry the operation."
    )


def _save_into_open_excel(pending_path: Path, target_path: Path) -> bool:
    """Copy pending cell values into an already-open Excel workbook."""
    try:
        import win32com.client as win32

        excel = win32.GetActiveObject("Excel.Application")
    except (ImportError, OSError):
        return False

    target_book = None
    pending_book = None
    target_resolved = target_path.resolve()
    try:
        for book in excel.Workbooks:
            if Path(str(book.FullName)).resolve() == target_resolved:
                target_book = book
                break
        if target_book is None:
            return False

        pending_book = excel.Workbooks.Open(
            str(pending_path.resolve()),
            ReadOnly=True,
            UpdateLinks=0,
        )
        for source_sheet in pending_book.Worksheets:
            try:
                target_sheet = target_book.Worksheets(source_sheet.Name)
            except Exception:
                target_sheet = target_book.Worksheets.Add()
                target_sheet.Name = source_sheet.Name

            used_range = source_sheet.UsedRange
            target_sheet.Range(used_range.Address).Value = used_range.Value

        target_book.Save()
        return True
    except Exception as exc:
        logger.exception(
            "Could not save through the open Excel instance: %s", exc
        )
        return False
    finally:
        if pending_book is not None:
            pending_book.Close(SaveChanges=False)
