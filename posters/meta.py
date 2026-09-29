from pathlib import Path
from utils import logger

def post_to_facebook(account: dict, video_path: Path, caption: str) -> dict:
    try:
        logger.info(f"[Facebook] Would upload {video_path.name}")
        return {"success": True, "post_id": "FB_PLACEHOLDER"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def post_to_instagram(account: dict, video_path: Path, caption: str) -> dict:
    try:
        logger.info(f"[Instagram] Would upload Reels {video_path.name}")
        return {"success": True, "post_id": "IG_PLACEHOLDER"}
    except Exception as e:
        return {"success": False, "error": str(e)}
