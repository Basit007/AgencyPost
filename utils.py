import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from config import LOG_FILE, CLIENTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AgencyPost")

def load_captions(client_folder: Path) -> dict:
    captions_file = client_folder / "captions.json"
    if captions_file.exists():
        try:
            return json.loads(captions_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load captions.json: {e}")
    return {}

def get_schedule(video_path: Path) -> str | None:
    """Look for a .schedule sidecar file. Content should be ISO datetime (UTC)."""
    schedule_file = video_path.with_suffix(".schedule")
    if schedule_file.exists():
        try:
            content = schedule_file.read_text(encoding="utf-8").strip()
            # basic validation
            datetime.fromisoformat(content.replace("Z", "+00:00"))
            return content
        except Exception as e:
            logger.warning(f"Invalid schedule file {schedule_file}: {e}")
    return None

def move_video(video_path: Path, target_folder: Path):
    target_folder.mkdir(parents=True, exist_ok=True)
    dest = target_folder / video_path.name
    shutil.move(str(video_path), str(dest))
    # also move schedule file if exists
    schedule_file = video_path.with_suffix(".schedule")
    if schedule_file.exists():
        shutil.move(str(schedule_file), str(target_folder / schedule_file.name))
    return dest
