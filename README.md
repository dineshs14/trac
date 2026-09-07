# TRACES Lower/Nil TDS Certificate Automation

Production-ready Python automation for managing Lower/Nil TDS certificates from the Indian TRACES portal.

## Features

- **Manager GUI Dashboard** — Clean Yellow + White themed Tkinter dashboard with live progress, real-time log viewer, and certificate table
- **Persistent browser session** — Log in once, reuse across runs
- **Lower TDS Certificate download** — Dynamic pagination, no hardcoded counts
- **Child Certificate download** — Separate workflow, correct download identification
- **Services detail update** — Quarterly consumption aggregation, Available Amount calculation
- **PDF parsing** — Text-based extraction using pdfplumber (no OCR)
- **Master Excel tracker** — Single workbook, deduplication by PAN + Certificate Number
- **Pure Excel tracking (no SQLite)** — Fully resumable, Excel-based process store (`automation_tracker.xlsx`)
- **Detailed logging** — Dated log files + GUI log stream + console output + run summaries

## Security & Compliance

> ⚠️ **This tool does NOT automate CAPTCHA, OTP, or login credentials.**
> The user logs in manually when required. The automation only operates within an already-authenticated session.

## Setup

### Prerequisites

- Python 3.11+
- Windows OS
- Network access to [traces.tdscpc.gov.in](https://traces.tdscpc.gov.in)

### Installation

```bash
cd TRACES_AUTOMATION
pip install -r requirements.txt
playwright install chromium
```

### Launching the Application

#### Option A: GUI Dashboard (Recommended for Managers)

Simply run:
```bash
python main.py
```
or
```bash
python gui.py
```
This opens the Yellow & White GUI dashboard with:
- Task buttons: **Download Lower TDS**, **Download Child**, **Update Services**, **Retry Failed**, **Run All**
- Financial Year dropdown selector
- Real-time progress bar and status indicator
- Live certificates table view
- Live scrolling log console

#### Option B: Command Line Interface (CLI)

```bash
# Lower TDS download
python main.py --task lower-download --fy 2026-27

# Child Certificate download
python main.py --task child-download --fy 2026-27

# Services update (Quarterly consumption & balance)
python main.py --task services-update --fy 2026-27

# Run all workflows sequentially
python main.py --task all --fy 2026-27

# Retry failed certificates
python main.py --task retry-failed --fy 2026-27

# Inspect DOM selectors on TRACES portal
python main.py --task inspect --fy 2026-27
```

## Project Structure

```
TRACES_AUTOMATION/
├── config.py                       # Central configuration & portal URLs
├── main.py                         # CLI & GUI launcher entry point
├── gui.py                          # Yellow & White Tkinter GUI Dashboard
├── requirements.txt
├── pytest.ini
├── README.md
│
├── automation/
│   ├── session_manager.py          # Playwright persistent context & login detection
│   ├── navigation.py               # Portal navigation & setup
│   ├── portal_utils.py             # Table extraction, pagination, selectors
│   ├── lower_tds_downloader.py     # Lower TDS workflow orchestrator
│   ├── child_certificate_downloader.py # Child cert workflow orchestrator
│   └── services_updater.py         # Services page updater
│
├── extraction/
│   ├── lower_tds_pdf_parser.py     # Lower TDS PDF extraction
│   ├── child_pdf_parser.py         # Child cert PDF extraction
│   └── validators.py               # PAN, cert, FY validation
│
├── data/
│   ├── models.py                   # Dataclasses
│   ├── tracker_store.py            # Excel-based Tracker Store (automation_tracker.xlsx)
│   ├── master_tracker.py           # Master Excel manager
│   └── process_tracker.py          # Process/failed Excel trackers
│
├── utils/
│   ├── logger.py                   # Dated log files + console
│   ├── file_utils.py               # Directory + file management
│   ├── naming.py                   # Filename conventions
│   └── retry.py                    # Retry decorator
│
├── Lower_TDS_Certificates/FY2026-27/
├── Child_Certificates/FY2026-27/
├── Master_Tracker/Lower_Nil_TDS_Master_Tracker.xlsx
├── Process_Files/
│   ├── browser_profile/            # Persistent Chromium profile
│   ├── automation_tracker.xlsx     # Excel tracker store
│   ├── failed_records.xlsx
│   └── logs/
└── tests/
```

## Configuration

All configuration is centralized in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `PAGE_LOAD_TIMEOUT_MS` | 120,000 | Page load timeout (ms) |
| `LOGIN_WAIT_TIMEOUT_MS` | 300,000 | Manual login wait (ms) |
| `DOWNLOAD_READY_TIMEOUT_MS` | 300,000 | Download readiness timeout (ms) |
| `MAX_RETRIES` | 5 | Maximum retry attempts |
| `REFRESH_INTERVAL_SECONDS` | 10 | Seconds between refresh clicks |
| `MAX_REFRESH_ATTEMPTS` | 30 | Maximum refresh cycles |

## Portal Selectors

All portal selectors are centralized in `config.py` under the `SELECTORS` dictionary and marked with `# VERIFY_WITH_INSPECTOR`.

### Verifying Selectors

1. Run in inspect mode:
   ```bash
   python main.py --task inspect --fy 2026-27
   ```
2. Or use Playwright Inspector:
   ```bash
   set PWDEBUG=1
   python main.py --task lower-download --fy 2026-27
   ```
3. Update selectors in `config.py` as needed.

## Resume After Crash

The automation is fully resumable. If it stops mid-run:

1. The SQLite tracker preserves the state of every certificate
2. On restart, completed certificates are automatically skipped
3. Only NEW and unfinished certificates are processed

Example: If 300 of 800 certificates were downloaded before a crash:
```bash
# Simply re-run — 300 completed are skipped, remaining 500 are processed
python main.py --task lower-download --fy 2026-27
```

## Run Summary

At the end of each run, a summary is printed:

```
==================================================
  RUN SUMMARY
==================================================
  Task:                      lower-download
  Financial Year:            2026-27
  Portal records discovered: 376
  Already completed:         300
  New:                       76
  Downloaded:                74
  Master rows added:         74
  Master rows updated:       0
  Failed:                    2
  Validation failed:         0
  Run duration:              0h 45m 12s
==================================================
```

## Testing

```bash
cd TRACES_AUTOMATION
pytest tests/ -v
```

## Troubleshooting

After a code update, close the existing dashboard and restart Python. The open
dashboard retains imported code between runs.

For CPCTDS Lower TDS downloads, run:

```powershell
python main.py --task lower-download --fy 2026-27
```

The program selects the year, opens the Form 128 certificate popup, and scans
every page before downloading. Logs show `Certificate popup page ...` during
discovery; leave the browser open while this runs. It then selects one actual
certificate row at a time and waits for that PAN/ARN's exact Download button.
Completed certificates are skipped, and saved PDFs can resume processing without
another download. PDFs with multiple detail rows are left for review rather than
silently reducing them to a single rate/limit.

| Issue | Solution |
|-------|----------|
| Session expired mid-run | Re-run. The browser will prompt for login. |
| Selector not found | Run `--task inspect` and update `config.py` SELECTORS |
| Excel file locked | Close Excel and re-run |
| Download stuck on "Refresh" | Increase `MAX_REFRESH_ATTEMPTS` in config |
| PDF parsing failure | Check `Process_Files/logs/` for details |

## License

Internal use only. Not for distribution.
