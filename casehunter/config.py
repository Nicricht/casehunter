from pathlib import Path
from datetime import date
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CASE_HUNTER_DATA_DIR", BASE_DIR / "data"))
DATABASE_PATH = Path(os.getenv("CASE_HUNTER_DB", DATA_DIR / "case_hunter.db"))
# Optional persistent backend. SQLite remains the zero-cost default.
DATABASE_URL = (os.getenv("CASE_HUNTER_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
DEFAULT_LEY_LOBBY_URL = os.getenv(
    "CASE_HUNTER_LEY_LOBBY_URL",
    "https://www.leylobby.gob.cl/instituciones/AM002/cargos-pasivos/642196/audiencias",
)

AUTH_USERNAME = os.getenv("CASE_HUNTER_USERNAME", "").strip()
AUTH_PASSWORD = os.getenv("CASE_HUNTER_PASSWORD", "").strip()

AUTO_YEAR = int(os.getenv("CASE_HUNTER_AUTO_YEAR", str(date.today().year)))
DEFAULT_AUTO_SOURCES = ",".join([
    f"https://www.leylobby.gob.cl/instituciones/AM010/audiencias/{AUTO_YEAR}",
    f"https://www.leylobby.gob.cl/instituciones/AM007/audiencias/{AUTO_YEAR}",
])
AUTO_SOURCE_URLS = [
    item.strip() for item in os.getenv("CASE_HUNTER_AUTO_SOURCE_URLS", DEFAULT_AUTO_SOURCES).split(",") if item.strip()
]
AUTO_INTERVAL_MINUTES = max(60, int(os.getenv("CASE_HUNTER_AUTO_INTERVAL_MINUTES", "360")))
AUTO_MIN_PRIORITY = max(0, min(100, int(os.getenv("CASE_HUNTER_AUTO_MIN_PRIORITY", "20"))))
AUTO_MAX_PAGES = max(1, min(50, int(os.getenv("CASE_HUNTER_AUTO_MAX_PAGES", "10"))))
AUTO_ENRICH_LIMIT = max(0, min(100, int(os.getenv("CASE_HUNTER_AUTO_ENRICH_LIMIT", "25"))))
AUTO_SUBJECTS_PER_CYCLE = max(1, min(100, int(os.getenv("CASE_HUNTER_AUTO_SUBJECTS_PER_CYCLE", "20"))))
AUTO_INDEX_PAGES = max(1, min(10, int(os.getenv("CASE_HUNTER_AUTO_INDEX_PAGES", "4"))))
AUTO_CASES_PER_CYCLE = max(1, min(100, int(os.getenv("CASE_HUNTER_AUTO_CASES_PER_CYCLE", "8"))))
AUTO_CONTACT_DISCOVERY = os.getenv("CASE_HUNTER_AUTO_CONTACT_DISCOVERY", "1").strip().lower() not in {"0", "false", "no"}
AUTO_SEND_APPROVED = os.getenv("CASE_HUNTER_AUTO_SEND_APPROVED", "0").strip().lower() in {"1", "true", "yes"}
AUTO_POLICY_SEND = os.getenv("CASE_HUNTER_AUTO_POLICY_SEND", "0").strip().lower() in {"1", "true", "yes"}
AUTO_SEND_MIN_PRIORITY = max(0, min(100, int(os.getenv("CASE_HUNTER_AUTO_SEND_MIN_PRIORITY", "70"))))
AUTO_MAX_FIRST_CONTACTS_PER_DAY = max(1, min(100, int(os.getenv("CASE_HUNTER_AUTO_MAX_FIRST_CONTACTS_PER_DAY", "10"))))
AUTO_MONITOR_REPLIES = os.getenv("CASE_HUNTER_AUTO_MONITOR_REPLIES", "1").strip().lower() not in {"0", "false", "no"}
AUTO_SEND_FOLLOWUPS = os.getenv("CASE_HUNTER_AUTO_SEND_FOLLOWUPS", "0").strip().lower() in {"1", "true", "yes"}
AUTO_FOLLOWUP_DAYS = max(1, min(30, int(os.getenv("CASE_HUNTER_AUTO_FOLLOWUP_DAYS", "5"))))
STORE_REPLY_CONTENT = os.getenv("CASE_HUNTER_STORE_REPLY_CONTENT", "0").strip().lower() in {"1", "true", "yes"}
CONTACT_DISCOVERY_TIMEOUT = max(2, min(30, int(os.getenv("CASE_HUNTER_CONTACT_TIMEOUT", "8"))))
CONTACT_DISCOVERY_MAX_SITES = max(1, min(5, int(os.getenv("CASE_HUNTER_CONTACT_MAX_SITES", "2"))))

SMTP_HOST = os.getenv("CASE_HUNTER_SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("CASE_HUNTER_SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("CASE_HUNTER_SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("CASE_HUNTER_SMTP_PASSWORD", "").strip()
SMTP_FROM_NAME = os.getenv("CASE_HUNTER_SMTP_FROM_NAME", "Nicolás Vega").strip()

IMAP_HOST = os.getenv("CASE_HUNTER_IMAP_HOST", "imap.gmail.com").strip()
IMAP_PORT = int(os.getenv("CASE_HUNTER_IMAP_PORT", "993"))
IMAP_USERNAME = os.getenv("CASE_HUNTER_IMAP_USERNAME", SMTP_USERNAME).strip()
IMAP_PASSWORD = os.getenv("CASE_HUNTER_IMAP_PASSWORD", SMTP_PASSWORD).strip()
