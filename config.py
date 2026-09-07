"""
TRACES Automation — Central Configuration

All paths, timeouts, selectors, column definitions, and constants.
Portal selectors are provisional and marked with VERIFY_WITH_INSPECTOR.
"""

from pathlib import Path

# ──────────────────────────────────────────────
# Project Root
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent

# ──────────────────────────────────────────────
# Directory Layout
# ──────────────────────────────────────────────
LOWER_TDS_DIR = PROJECT_ROOT / "Lower_TDS_Certificates"
CHILD_CERT_DIR = PROJECT_ROOT / "Child_Certificates"
MASTER_TRACKER_DIR = PROJECT_ROOT / "Master_Tracker"
PROCESS_FILES_DIR = PROJECT_ROOT / "Process_Files"
LOGS_DIR = PROCESS_FILES_DIR / "logs"
BROWSER_PROFILE_DIR = PROCESS_FILES_DIR / "browser_profile"
TEMP_DOWNLOAD_DIR = PROCESS_FILES_DIR / "temp_downloads"

# ──────────────────────────────────────────────
# File Paths
# ──────────────────────────────────────────────
MASTER_TRACKER_FILE = MASTER_TRACKER_DIR / "Lower_Nil_TDS_Master_Tracker.xlsx"
AUTOMATION_TRACKER_FILE = PROCESS_FILES_DIR / "automation_tracker.xlsx"
FAILED_RECORDS_FILE = PROCESS_FILES_DIR / "failed_records.xlsx"
PROCESS_TRACKER_FILE = PROCESS_FILES_DIR / "automation_tracker.xlsx"

# ──────────────────────────────────────────────
# Portal URLs
# ──────────────────────────────────────────────
TRACES_BASE_URL = "https://traces.tdscpc.gov.in"
TRACES_AUTH_URL = f"{TRACES_BASE_URL}/auth"
# The current Flutter portal does not expose the old /auth/loginscreen route.
# Open the public shell and let the user use its current Login entry point.
TRACES_LOGIN_URL = f"{TRACES_BASE_URL}/auth/login/loginScreen"
TRACES_DOWNLOAD_CERT_URL = (
    f"{TRACES_BASE_URL}/auth/deductorDownloadCert/deductorDownloadCertificateScreen"
)
TRACES_CHILD_CERT_URL = (
    f"{TRACES_BASE_URL}/auth/childCertificateTraces/downloadChildCertificate"
)
TRACES_SERVICES_VIEW_CERT_URL = (
    f"{TRACES_BASE_URL}/auth/viewLDCNDC/viewCertificateFormScreen"
)
TRACES_DASHBOARD_URL = TRACES_AUTH_URL

# ──────────────────────────────────────────────
# Timeouts (milliseconds)
# ──────────────────────────────────────────────
PAGE_LOAD_TIMEOUT_MS = 120_000          # Government portals can be slow
NAVIGATION_TIMEOUT_MS = 90_000
LOGIN_WAIT_TIMEOUT_MS = 300_000         # 5 minutes for manual login
ELEMENT_WAIT_TIMEOUT_MS = 60_000
DOWNLOAD_READY_TIMEOUT_MS = 300_000     # 5 minutes for download to become ready
POPUP_WAIT_TIMEOUT_MS = 30_000

# ──────────────────────────────────────────────
# Retry Configuration
# ──────────────────────────────────────────────
MAX_RETRIES = 5
REFRESH_INTERVAL_SECONDS = 10
RETRY_BACKOFF_FACTOR = 1.5
MAX_REFRESH_ATTEMPTS = 30               # For download-ready polling

# ──────────────────────────────────────────────
# Certificate Types
# ──────────────────────────────────────────────
CERT_TYPE_LOWER_TDS = "LOWER_TDS"
CERT_TYPE_CHILD = "CHILD"

# ──────────────────────────────────────────────
# Processing Statuses
# ──────────────────────────────────────────────
STATUS_DISCOVERED = "DISCOVERED"
STATUS_INITIATED = "INITIATED"
STATUS_READY = "READY"
STATUS_DOWNLOADED = "DOWNLOADED"
STATUS_EXTRACTED = "EXTRACTED"
STATUS_VALIDATED = "VALIDATED"
STATUS_MASTER_UPDATED = "MASTER_UPDATED"
STATUS_SERVICES_UPDATED = "SERVICES_UPDATED"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_VALIDATION_FAILED = "VALIDATION_FAILED"

# ──────────────────────────────────────────────
# Master Tracker Column Names (in order)
# ──────────────────────────────────────────────
MASTER_COLUMNS = [
    "SL_No",
    "Certificate_Type",
    "PAN",
    "Vendor_Name",
    "Count",
    "Certificate_Number",
    "Certificate_Short_Number",
    "Financial_Year",
    "TDS_Rate",
    "Nature_of_Payment",
    "Section",
    "Section_Code",
    "Certificate_Limit",
    "Valid_From",
    "Valid_To",
    "Certificate_Name",
    "Date_Received",
    "Date_of_Issue",
    "Application_Form_No",
    "Applicable_Income_Tax_Act",
    "Q1_Amount_Consumed",
    "Q2_Amount_Consumed",
    "Q3_Amount_Consumed",
    "Q4_Amount_Consumed",
    "Total_Amount_Consumed",
    "Available_Amount",
    "Date_of_Cancellation",
    "Notes",
    "PDF_Path",
    "Processing_Status",
    "Last_Updated",
]

MASTER_SHEET_NAME = "Certificate_Data"

# ──────────────────────────────────────────────
# Browser Launch Options
# ──────────────────────────────────────────────
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
]
BROWSER_HEADLESS = False
BROWSER_ACCEPT_DOWNLOADS = True
BROWSER_VIEWPORT = {"width": 1920, "height": 1080}

# ──────────────────────────────────────────────
# Invalid Filename Characters (Windows)
# ──────────────────────────────────────────────
INVALID_FILENAME_CHARS = '<>:"/\\|?*'

# ──────────────────────────────────────────────
# PAN Regex
# ──────────────────────────────────────────────
PAN_REGEX = r"[A-Z]{5}[0-9]{4}[A-Z]"

# ──────────────────────────────────────────────
# Portal Selectors — PROVISIONAL
# All selectors marked VERIFY_WITH_INSPECTOR must be verified
# against the live TRACES DOM using Playwright Inspector (PWDEBUG=1).
# ──────────────────────────────────────────────
SELECTORS = {
    # ── Authentication Detection ──
    # Element present on authenticated pages
    "auth_indicator": "#logoutLink",                          # VERIFY_WITH_INSPECTOR
    "auth_indicator_alt": 'a:has-text("Logout")',             # VERIFY_WITH_INSPECTOR
    # Login page indicators
    "login_indicator": "#loginForm",                          # VERIFY_WITH_INSPECTOR
    "login_indicator_alt": 'input[name="userId"]',            # VERIFY_WITH_INSPECTOR

    # ── Download Certificate Page ──
    "download_cert_type_dropdown": "#certificateType",        # VERIFY_WITH_INSPECTOR
    "download_cert_type_lower": "Lower/No Deduction/Collection Certificate(s)",
    "download_cert_type_child": "Child Certificate(s) issued under Rule No. 213(9)",
    "download_user_type_dropdown": "#userType",               # VERIFY_WITH_INSPECTOR
    "download_user_type_recipient": "User is Recipient",
    "download_fy_dropdown": "#financialYear",                 # VERIFY_WITH_INSPECTOR
    "download_tax_year_dropdown": "#taxYear",                 # VERIFY_WITH_INSPECTOR
    "download_initiate_btn": 'button:has-text("Initiate Download")',  # VERIFY_WITH_INSPECTOR
    "download_search_btn": 'button:has-text("Search")',       # VERIFY_WITH_INSPECTOR

    # ── Lower TDS Download Popup ──
    "popup_modal": ".modal-content",                          # VERIFY_WITH_INSPECTOR
    "popup_table": "#certificateTable",                       # VERIFY_WITH_INSPECTOR
    "popup_table_rows": "#certificateTable tbody tr",         # VERIFY_WITH_INSPECTOR
    "popup_next_page_btn": 'a:has-text("Next")',              # VERIFY_WITH_INSPECTOR
    "popup_page_info": ".dataTables_info",                    # VERIFY_WITH_INSPECTOR
    "popup_pagination": ".dataTables_paginate",               # VERIFY_WITH_INSPECTOR
    "popup_row_checkbox": 'input[type="checkbox"]',           # VERIFY_WITH_INSPECTOR
    "popup_initiate_download_btn": '#initiateDownloadBtn',    # VERIFY_WITH_INSPECTOR

    # ── Initiated Downloads Section ──
    "initiated_downloads_section": "#initiatedDownloads",     # VERIFY_WITH_INSPECTOR
    "initiated_downloads_table": "#initiatedDownloadsTable",  # VERIFY_WITH_INSPECTOR
    "initiated_refresh_btn": 'button:has-text("Refresh")',    # VERIFY_WITH_INSPECTOR
    "initiated_download_link": 'a:has-text("Download")',      # VERIFY_WITH_INSPECTOR
    "initiated_status_col": ".downloadStatus",                # VERIFY_WITH_INSPECTOR

    # ── Child Certificate Table ──
    "child_cert_table": "#childCertificateTable",             # VERIFY_WITH_INSPECTOR
    "child_cert_table_rows": "#childCertificateTable tbody tr",  # VERIFY_WITH_INSPECTOR
    "child_view_downloads_btn": 'button:has-text("View All Initiated Downloads")',  # VERIFY_WITH_INSPECTOR

    # ── Services Page ──
    "services_fy_dropdown": "#financialYear",                 # VERIFY_WITH_INSPECTOR
    "services_proceed_btn": 'button:has-text("Proceed")',     # VERIFY_WITH_INSPECTOR
    "services_cert_list": "#certificateList",                 # VERIFY_WITH_INSPECTOR
    "services_cert_detail_btn": 'a:has-text("Certificate details")',  # VERIFY_WITH_INSPECTOR
    "services_consumption_expand": 'a:has-text("Consumption Details")',  # VERIFY_WITH_INSPECTOR
    "services_consumption_table": "#consumptionDetailsTable", # VERIFY_WITH_INSPECTOR
    "services_next_page_btn": 'a:has-text("Next")',           # VERIFY_WITH_INSPECTOR
}
