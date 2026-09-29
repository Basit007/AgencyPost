from pathlib import Path
from utils import logger

def post_to_tiktok(account: dict, video_path: Path, caption: str) -> dict:
    try:
        logger.info(f"[TikTok] Would upload {video_path.name}")
        return {"success": True, "post_id": "TT_PLACEHOLDER"}
    except Exception as e:
        return {"success": False, "error": str(e)}
