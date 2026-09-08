"""Tests for saving workbooks while Excel has the target file open."""

from pathlib import Path

import pytest

from utils import excel_save
from utils.excel_save import ExcelFileLockedError, save_workbook


class FakeWorkbook:
    def __init__(self, locked_path: Path) -> None:
        self.locked_path = locked_path
        self.saved_paths = []

    def save(self, path: str) -> None:
        save_path = Path(path)
        self.saved_paths.append(save_path)
        if save_path == self.locked_path:
            raise PermissionError("file is open")
        save_path.write_bytes(b"pending workbook")


def test_locked_workbook_is_saved_into_open_excel(tmp_path, monkeypatch):
    target = tmp_path / "tracker.xlsx"
    workbook = FakeWorkbook(target)
    monkeypatch.setattr(excel_save, "_save_into_open_excel", lambda pending, path: True)

    save_workbook(workbook, target)

    pending = tmp_path / "tracker.pending.xlsx"
    assert workbook.saved_paths == [target, pending]
    assert not pending.exists()


def test_locked_workbook_keeps_pending_update_when_excel_unavailable(
    tmp_path, monkeypatch
):
    target = tmp_path / "tracker.xlsx"
    workbook = FakeWorkbook(target)
    monkeypatch.setattr(excel_save, "_save_into_open_excel", lambda pending, path: False)

    with pytest.raises(ExcelFileLockedError, match="tracker.pending.xlsx"):
        save_workbook(workbook, target)

    assert (tmp_path / "tracker.pending.xlsx").exists()