"""
TRACES Automation — File Utilities

Directory creation, temp file management, safe file move/copy.
"""

from pathlib import Path
from typing import Optional

from config import (
    LOWER_TDS_DIR,
    CHILD_CERT_DIR,
    MASTER_TRACKER_DIR,
    PROCESS_FILES_DIR,
    LOGS_DIR,
    BROWSER_PROFILE_DIR,
    TEMP_DOWNLOAD_DIR,
)
from utils.logger import logger


def ensure_directories() -> None:
    """Create all project directories if they do not exist."""
    dirs = [
        LOWER_TDS_DIR,
        CHILD_CERT_DIR,
        MASTER_TRACKER_DIR,
        PROCESS_FILES_DIR,
        LOGS_DIR,
        BROWSER_PROFILE_DIR,
        TEMP_DOWNLOAD_DIR,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured directory: %s", d)


def ensure_fy_subdirectory(base_dir: Path, fy: str) -> Path:
    """Create and return the FY subfolder, e.g. Lower_TDS_Certificates/FY2026-27/."""
    fy_folder = base_dir / f"FY{fy}"
    fy_folder.mkdir(parents=True, exist_ok=True)
    return fy_folder


def safe_move(src: Path, dst: Path, overwrite: bool = False) -> Path:
    """Move a file from *src* to *dst*.

    If *overwrite* is False and *dst* exists, raises FileExistsError.
    Returns the final destination path.
    """
    if dst.exists() and not overwrite:
        raise FileExistsError(f"Destination already exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    logger.debug("Moved %s → %s", src, dst)
    return dst


def temp_download_path(filename: str) -> Path:
    """Return a path inside the temp download folder."""
    TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DOWNLOAD_DIR / filename


def cleanup_temp_downloads() -> int:
    """Delete all files in the temp download folder. Returns count deleted."""
    if not TEMP_DOWNLOAD_DIR.exists():
        return 0
    count = 0
    for f in TEMP_DOWNLOAD_DIR.iterdir():
        if f.is_file():
            f.unlink()
            count += 1
    logger.debug("Cleaned up %d temp files", count)
    return count


def file_exists_for_key(
    target_dir: Path, fy: str, expected_name: str
) -> Optional[Path]:
    """Check whether a named PDF already exists in the FY subdirectory."""
    fy_folder = target_dir / f"FY{fy}"
    if not fy_folder.exists():
        return None
    candidate = fy_folder / expected_name
    return candidate if candidate.exists() else None
