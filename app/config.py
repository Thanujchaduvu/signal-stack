import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
BASE = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("DATA_DIR", BASE / "data")); DATA.mkdir(parents=True, exist_ok=True)
UPLOADS = DATA / "uploads"; UPLOADS.mkdir(exist_ok=True)
DB_PATH = DATA / "signalstack.db"
def ua(): return os.getenv("CRAWLER_UA", "SignalStackBot/1.0 (+contact: set CRAWLER_UA)")
def crawl_delay(): return float(os.getenv("CRAWL_DELAY_SECONDS", "2"))
# Ranking weights (sum = 1). Change here; documented in docs/TECHNICAL.md
WEIGHTS = {"relevance": .25, "impact": .20, "urgency": .15, "credibility": .15, "recency": .15, "novelty": .10}
DEFAULT_SETTINGS = {
    "brief_day": "mon", "brief_time": "07:30", "timezone": "Asia/Kolkata",
    "monitor_hours": 24, "source_refresh_hours": 12, "audit_day": 1, "region": "US",
    "brief_window_days": 14,
}
