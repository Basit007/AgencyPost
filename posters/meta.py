"""
Meta (Facebook + Instagram) uploader.

Facebook: uses Page access token + /page_id/videos.
Instagram: uses Instagram Graph API (Business/Creator account).
            Most reliable path is a publicly reachable video_url
            or the resumable upload flow.

account dict expected:
  - access_token (Page or long-lived token)
  - account_id   (Facebook Page ID or Instagram Business Account ID)
"""

from pathlib import Path
import time
import httpx
from utils import logger

GRAPH = "https://graph.facebook.com/v21.0"


def post_to_facebook(account: dict, video_path: Path, caption: str) -> dict:
    try:
        page_id = account.get("account_id")
        token = account.get("access_token")
        if not page_id or not token:
            return {"success": False, "error": "Missing account_id (Page ID) or access_token"}

        public_url = None
        if account.get("extra_data"):
            import json
            try:
                extra = json.loads(account["extra_data"]) if isinstance(account["extra_data"], str) else account["extra_data"]
                public_url = extra.get("public_video_url")
            except Exception:
                pass

        if public_url:
            with httpx.Client(timeout=120) as client:
                r = client.post(
                    f"https://graph-video.facebook.com/v21.0/{page_id}/videos",
                    data={
                        "file_url": public_url,
                        "description": caption or "",
                        "access_token": token,
                    },
                )
                data = r.json()
                if r.status_code >= 400 or "error" in data:
                    return {"success": False, "error": str(data.get("error", data))}
                video_id = data.get("id")
                logger.info(f"[Facebook] Posted video id={video_id}")
                return {"success": True, "post_id": video_id}

        logger.warning(
            "[Facebook] Local file upload requires a public URL or resumable upload. "
            "Store public_video_url in account.extra_data for now."
        )
        return {
            "success": False,
            "error": "Local Facebook video upload needs a public URL. "
                     "Put the URL in account.extra_data['public_video_url'] or implement resumable upload."
        }

    except Exception as e:
        logger.exception(f"[Facebook] Error: {e}")
        return {"success": False, "error": str(e)}


def post_to_instagram(account: dict, video_path: Path, caption: str) -> dict:
    """
    Publish an Instagram Reel.
    Flow: create container (REELS + video_url) → poll → media_publish.
    video_url must be publicly reachable by Meta.
    """
    try:
        ig_user_id = account.get("account_id")
        token = account.get("access_token")
        if not ig_user_id or not token:
            return {"success": False, "error": "Missing account_id (IG user id) or access_token"}

        public_url = None
        if account.get("extra_data"):
            import json
            try:
                extra = json.loads(account["extra_data"]) if isinstance(account["extra_data"], str) else account["extra_data"]
                public_url = extra.get("public_video_url")
            except Exception:
                pass

        if not public_url:
            return {
                "success": False,
                "error": "Instagram Reels require a publicly reachable video_url. "
                         "Upload the file somewhere public (S3/R2/etc) and store the URL "
                         "in account.extra_data['public_video_url']."
            }

        with httpx.Client(timeout=60) as client:
            r = client.post(
                f"{GRAPH}/{ig_user_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": public_url,
                    "caption": caption or "",
                    "access_token": token,
                },
            )
            data = r.json()
            if "id" not in data:
                return {"success": False, "error": f"Container creation failed: {data}"}
            container_id = data["id"]
            logger.info(f"[Instagram] Container created: {container_id}")

            for _ in range(30):
                time.sleep(10)
                s = client.get(
                    f"{GRAPH}/{container_id}",
                    params={"fields": "status_code", "access_token": token},
                ).json()
                status = s.get("status_code")
                logger.info(f"[Instagram] Container status: {status}")
                if status == "FINISHED":
                    break
                if status in ("ERROR", "EXPIRED"):
                    return {"success": False, "error": f"Container failed: {s}"}
            else:
                return {"success": False, "error": "Timeout waiting for Instagram container"}

            p = client.post(
                f"{GRAPH}/{ig_user_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
            )
            pub = p.json()
            if "id" not in pub:
                return {"success": False, "error": f"Publish failed: {pub}"}

            media_id = pub["id"]
            logger.info(f"[Instagram] Published Reel id={media_id}")
            return {"success": True, "post_id": media_id}

    except Exception as e:
        logger.exception(f"[Instagram] Error: {e}")
        return {"success": False, "error": str(e)}
