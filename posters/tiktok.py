"""
TikTok Content Posting API (Direct Post).

Requires access_token with video.publish scope.
Unaudited apps are forced to SELF_ONLY (private) by TikTok.
"""

from pathlib import Path
import httpx
from utils import logger

TIKTOK_API = "https://open.tiktokapis.com"


def post_to_tiktok(account: dict, video_path: Path, caption: str,
                   privacy_level: str = "SELF_ONLY") -> dict:
    """
    Direct Post a video to TikTok.

    privacy_level (after audit): PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS,
                                 FOLLOWER_OF_CREATOR, SELF_ONLY
    Until audited, TikTok forces SELF_ONLY.
    """
    try:
        token = account.get("access_token")
        if not token:
            return {"success": False, "error": "Missing access_token"}

        video_size = video_path.stat().st_size
        chunk_size = min(10 * 1024 * 1024, video_size)
        total_chunk_count = max(1, (video_size + chunk_size - 1) // chunk_size)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        init_body = {
            "post_info": {
                "title": (caption or video_path.stem)[:150],
                "privacy_level": privacy_level,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunk_count,
            },
        }

        with httpx.Client(timeout=120) as client:
            r = client.post(
                f"{TIKTOK_API}/v2/post/publish/video/init/",
                headers=headers,
                json=init_body,
            )
            data = r.json()
            err = data.get("error") or {}
            if r.status_code >= 400 or (err and err.get("code") not in (None, "ok", "")):
                return {"success": False, "error": f"Init failed: {data}"}

            publish_id = data.get("data", {}).get("publish_id")
            upload_url = data.get("data", {}).get("upload_url")
            if not upload_url:
                return {"success": False, "error": f"No upload_url returned: {data}"}

            logger.info(f"[TikTok] Init OK, publish_id={publish_id}")

            with open(video_path, "rb") as f:
                for i in range(total_chunk_count):
                    start = i * chunk_size
                    end = min(start + chunk_size, video_size) - 1
                    chunk = f.read(end - start + 1)

                    upload_headers = {
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{video_size}",
                    }
                    ur = client.put(upload_url, headers=upload_headers, content=chunk)
                    if ur.status_code not in (200, 201, 308):
                        return {"success": False, "error": f"Chunk upload failed: {ur.status_code} {ur.text}"}
                    logger.info(f"[TikTok] Uploaded chunk {i+1}/{total_chunk_count}")

            status_r = client.post(
                f"{TIKTOK_API}/v2/post/publish/status/fetch/",
                headers=headers,
                json={"publish_id": publish_id},
            )
            status_data = status_r.json()
            logger.info(f"[TikTok] Status: {status_data}")

            return {
                "success": True,
                "post_id": publish_id,
                "status": status_data.get("data", {}).get("status"),
            }

    except Exception as e:
        logger.exception(f"[TikTok] Error: {e}")
        return {"success": False, "error": str(e)}
