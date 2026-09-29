from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

# Main folders
CLIENTS_DIR = BASE_DIR / "clients"
DATA_DIR = BASE_DIR / "data"
TOKENS_DIR = BASE_DIR / "tokens"
LOGS_DIR = BASE_DIR / "logs"

DB_PATH = DATA_DIR / "agency.db"

# Create folders
for d in [CLIENTS_DIR, DATA_DIR, TOKENS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Logging
LOG_FILE = LOGS_DIR / "posting.log"

# How often the scheduler checks for due posts (seconds)
SCHEDULER_INTERVAL = 30

# Platforms we support
PLATFORMS = ["youtube", "facebook", "instagram", "tiktok"]
