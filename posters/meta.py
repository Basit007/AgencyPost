"""
Meta (Facebook + Instagram) uploader - uploads straight from the local file.
No public URL / S3 needed.

account dict expected:
  - access_token : Page access token (long-lived / never-expiring)
  - account_id   : Facebook Page ID (facebook) or Instagram Business account ID (instagram)

Optional account.extra_data JSON:
  - facebook_format : "video" (default, resumable /videos) or "reel" (/video_reels)
  - share_to_feed   : bool, Instagram Reels only (default true)
"""

import json
import time
from pathlib import Path

import httpx

from utils import logger

API_VERSION = "v21.0"
GRAPH = f"https://graph.facebook.com/{API_VERSION}"
GRAPH_VIDEO = f"https://graph-video.facebook.com/{API_VERSION}"

POLL_INTERVAL = 10      # seconds between status checks
POLL_ATTEMPTS = 60      # ~10 minutes max
IG_CHUNK = 20 * 1024 * 1024


def _extra(account: dict) -> dict:
    raw = account.get("extra_data")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _err(data: dict) -> str | None:
    """Return a readable error string if a Graph response contains an error."""
    if isinstance(data, dict) and "error" in data:
        e = data["error"]
        if isinstance(e, dict):
            return f"{e.get('message')} (code {e.get('code')}, subcode {e.get('error_subcode')})"
        return str(e)
    return None


def _json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"error": {"message": f"HTTP {resp.status_code}: {resp.text[:300]}"}}


# --------------------------------------------------------------------------
# Facebook
# --------------------------------------------------------------------------

def post_to_facebook(account: dict, video_path: Path, caption: str,
                     client: httpx.Client | None = None) -> dict:
    try:
        page_id = account.get("account_id")
        token = account.get("access_token")
        if not page_id or not token:
            return {"success": False, "error": "Missing account_id (Page ID) or access_token"}

        own = client is None
        client = client or httpx.Client(timeout=300)
        try:
            fmt = _extra(account).get("facebook_format", "video")
            if fmt == "reel":
                return _facebook_reel(client, page_id, token, video_path, caption)
            return _facebook_video(client, page_id, token, video_path, caption)
        finally:
            if own:
                client.close()
    except Exception as e:
        logger.exception(f"[Facebook] Error: {e}")
        return {"success": False, "error": str(e)}


def _facebook_video(client, page_id, token, video_path: Path, caption: str) -> dict:
    """Resumable upload: start -> transfer chunks -> finish."""
    size = video_path.stat().st_size
    url = f"{GRAPH_VIDEO}/{page_id}/videos"

    start = _json(client.post(url, data={
        "upload_phase": "start", "file_size": size, "access_token": token}))
    if e := _err(start):
        return {"success": False, "error": f"FB start failed: {e}"}
    session_id = start["upload_session_id"]
    video_id = start["video_id"]
    start_off, end_off = int(start["start_offset"]), int(start["end_offset"])
    logger.info(f"[Facebook] Upload session {session_id}, video_id={video_id}")

    with open(video_path, "rb") as f:
        while start_off < end_off:
            f.seek(start_off)
            chunk = f.read(end_off - start_off)
            r = _json(client.post(
                url,
                data={"upload_phase": "transfer", "upload_session_id": session_id,
                      "start_offset": start_off, "access_token": token},
                files={"video_file_chunk": (video_path.name, chunk, "application/octet-stream")},
            ))
            if e := _err(r):
                return {"success": False, "error": f"FB transfer failed: {e}"}
            start_off, end_off = int(r["start_offset"]), int(r["end_offset"])
            logger.info(f"[Facebook] Upload progress: {int(start_off * 100 / size)}%")

    fin = _json(client.post(url, data={
        "upload_phase": "finish", "upload_session_id": session_id,
        "description": caption or "", "title": video_path.stem[:100],
        "access_token": token}))
    if e := _err(fin):
        return {"success": False, "error": f"FB finish failed: {e}"}
    if not fin.get("success", True):
        return {"success": False, "error": f"FB finish returned: {fin}"}

    logger.info(f"[Facebook] Posted video id={video_id}")
    return {"success": True, "post_id": video_id}


def _facebook_reel(client, page_id, token, video_path: Path, caption: str) -> dict:
    """Reels flow: start -> upload binary to rupload -> finish (PUBLISHED) -> poll."""
    size = video_path.stat().st_size
    url = f"{GRAPH}/{page_id}/video_reels"

    start = _json(client.post(url, data={"upload_phase": "start", "access_token": token}))
    if e := _err(start):
        return {"success": False, "error": f"FB reel start failed: {e}"}
    video_id = start["video_id"]
    upload_url = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{API_VERSION}/{video_id}"

    up = _json(client.post(
        upload_url,
        headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
        content=video_path.read_bytes(),
    ))
    if e := _err(up):
        return {"success": False, "error": f"FB reel upload failed: {e}"}
    if up.get("success") is False:
        return {"success": False, "error": f"FB reel upload returned: {up}"}

    fin = _json(client.post(url, data={
        "upload_phase": "finish", "video_id": video_id,
        "video_state": "PUBLISHED", "description": caption or "",
        "access_token": token}))
    if e := _err(fin):
        return {"success": False, "error": f"FB reel finish failed: {e}"}

    for _ in range(POLL_ATTEMPTS):
        s = _json(client.get(f"{GRAPH}/{video_id}",
                             params={"fields": "status", "access_token": token}))
        st = (s.get("status") or {})
        phase = (st.get("publishing_phase") or {}).get("status")
        vstat = st.get("video_status")
        logger.info(f"[Facebook] Reel status: video={vstat} publishing={phase}")
        if phase == "complete" or vstat == "ready" and not st.get("publishing_phase"):
            logger.info(f"[Facebook] Reel published id={video_id}")
            return {"success": True, "post_id": video_id}
        if vstat == "error" or phase == "error":
            return {"success": False, "error": f"FB reel processing failed: {st}"}
        time.sleep(POLL_INTERVAL)
    return {"success": False, "error": "Timeout waiting for Facebook reel to publish"}


# --------------------------------------------------------------------------
# Instagram (Reels)
# --------------------------------------------------------------------------

def post_to_instagram(account: dict, video_path: Path, caption: str,
                      client: httpx.Client | None = None) -> dict:
    """
    Publish an Instagram Reel from a local file.
    Flow: create container (resumable) -> upload binary -> poll -> media_publish.
    """
    try:
        ig_user_id = account.get("account_id")
        token = account.get("access_token")
        if not ig_user_id or not token:
            return {"success": False, "error": "Missing account_id (IG user id) or access_token"}

        share_to_feed = _extra(account).get("share_to_feed", True)
        size = video_path.stat().st_size

        own = client is None
        client = client or httpx.Client(timeout=300)
        try:
            c = _json(client.post(f"{GRAPH}/{ig_user_id}/media", data={
                "media_type": "REELS", "upload_type": "resumable",
                "caption": caption or "",
                "share_to_feed": str(bool(share_to_feed)).lower(),
                "access_token": token}))
            if e := _err(c):
                return {"success": False, "error": f"IG container creation failed: {e}"}
            container_id = c["id"]
            upload_url = c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{API_VERSION}/{container_id}"
            logger.info(f"[Instagram] Container created: {container_id}")

            up = _json(client.post(
                upload_url,
                headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
                content=video_path.read_bytes(),
            ))
            if e := _err(up):
                return {"success": False, "error": f"IG upload failed: {e}"}
            if up.get("success") is False:
                return {"success": False, "error": f"IG upload returned: {up}"}
            logger.info("[Instagram] Video bytes uploaded, waiting for processing")

            for _ in range(POLL_ATTEMPTS):
                s = _json(client.get(f"{GRAPH}/{container_id}", params={
                    "fields": "status_code,status", "access_token": token}))
                status = s.get("status_code")
                logger.info(f"[Instagram] Container status: {status}")
                if status == "FINISHED":
                    break
                if status in ("ERROR", "EXPIRED") or _err(s):
                    return {"success": False, "error": f"IG container failed: {s}"}
                time.sleep(POLL_INTERVAL)
            else:
                return {"success": False, "error": "Timeout waiting for Instagram container"}

            pub = _json(client.post(f"{GRAPH}/{ig_user_id}/media_publish", data={
                "creation_id": container_id, "access_token": token}))
            if e := _err(pub):
                return {"success": False, "error": f"IG publish failed: {e}"}
            if "id" not in pub:
                return {"success": False, "error": f"IG publish failed: {pub}"}

            logger.info(f"[Instagram] Published Reel id={pub['id']}")
            return {"success": True, "post_id": pub["id"]}
        finally:
            if own:
                client.close()
    except Exception as e:
        logger.exception(f"[Instagram] Error: {e}")
        return {"success": False, "error": str(e)}
