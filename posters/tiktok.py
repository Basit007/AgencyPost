"""
TikTok Content Posting API (Direct Post) - uploads from the local file.

account dict expected:
  - access_token / refresh_token / token_expires_at
  - account.extra_data JSON:
        client_id      : TikTok app "client key"
        client_secret  : TikTok app "client secret"
        tiktok_privacy : optional, e.g. "PUBLIC_TO_EVERYONE" (default "SELF_ONLY")

Notes:
  * Access tokens last 24h; this module refreshes them automatically and saves
    the new tokens to the database.
  * Unaudited TikTok apps are restricted to private posts (SELF_ONLY).
    The privacy level is always checked against the account's allowed options.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from db import update_account_tokens
from utils import logger

TIKTOK_API = "https://open.tiktokapis.com"
CHUNK_SIZE = 10 * 1024 * 1024        # TikTok: chunks must be 5-64 MB (last chunk up to 128 MB)
POLL_INTERVAL = 5                    # seconds
POLL_ATTEMPTS = 120                  # ~10 minutes
REFRESH_MARGIN = timedelta(minutes=5)


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


def _api_error(data: dict) -> str | None:
    err = (data or {}).get("error") or {}
    code = err.get("code")
    if code and code != "ok":
        return f"{code}: {err.get('message')} (log_id {err.get('log_id')})"
    return None


def _json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"error": {"code": f"http_{resp.status_code}", "message": resp.text[:300]}}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _plan_chunks(size: int) -> tuple[int, int]:
    """
    Return (chunk_size, total_chunk_count) following TikTok's rules:
    every chunk >= 5 MB, remainder bytes are merged into the final chunk,
    so total_chunk_count = floor(size / chunk_size). Smaller files go in one piece.
    """
    if size < 2 * CHUNK_SIZE:
        return size, 1
    return CHUNK_SIZE, size // CHUNK_SIZE


def _ensure_token(account: dict, client: httpx.Client) -> str:
    token = account.get("access_token")
    expires = _parse_dt(account.get("token_expires_at"))
    now = datetime.now(timezone.utc)
    if token and expires and expires - now > REFRESH_MARGIN:
        return token

    refresh = account.get("refresh_token")
    extra = _extra(account)
    key, secret = extra.get("client_id"), extra.get("client_secret")
    if not (refresh and key and secret):
        if token:
            logger.warning("[TikTok] Cannot refresh (need refresh_token + client_id/client_secret "
                           "in extra_data); using stored access token as-is")
            return token
        raise ValueError("Missing access_token, and no refresh_token/client credentials to get one")

    data = _json(client.post(
        f"{TIKTOK_API}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"client_key": key, "client_secret": secret,
              "grant_type": "refresh_token", "refresh_token": refresh},
    ))
    if "access_token" not in data:
        raise RuntimeError(f"TikTok token refresh failed: {data}")

    new_exp = (now + timedelta(seconds=int(data.get("expires_in", 86400)))).isoformat()
    if account.get("client_id") is not None:
        update_account_tokens(account["client_id"], "tiktok", data["access_token"],
                              data.get("refresh_token"), new_exp)
    logger.info("[TikTok] Access token refreshed")
    return data["access_token"]


def post_to_tiktok(account: dict, video_path: Path, caption: str,
                   privacy_level: str | None = None,
                   client: httpx.Client | None = None) -> dict:
    """Direct-post a local video to TikTok and wait for the publish result."""
    try:
        own = client is None
        client = client or httpx.Client(timeout=300)
        try:
            return _post(account, video_path, caption, privacy_level, client)
        finally:
            if own:
                client.close()
    except Exception as e:
        logger.exception(f"[TikTok] Error: {e}")
        return {"success": False, "error": str(e)}


def _post(account, video_path: Path, caption, privacy_level, client) -> dict:
    token = _ensure_token(account, client)
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json; charset=UTF-8"}

    # 1. Creator info (required by TikTok before every direct post)
    ci_resp = _json(client.post(f"{TIKTOK_API}/v2/post/publish/creator_info/query/", headers=headers))
    if e := _api_error(ci_resp):
        return {"success": False, "error": f"creator_info failed: {e}"}
    ci = ci_resp.get("data", {})
    options = ci.get("privacy_level_options") or []

    wanted = privacy_level or _extra(account).get("tiktok_privacy") or "SELF_ONLY"
    if wanted in options:
        privacy = wanted
    elif "SELF_ONLY" in options:
        privacy = "SELF_ONLY"
        logger.warning(f"[TikTok] {wanted} not allowed for this account (options: {options}); using SELF_ONLY")
    elif options:
        privacy = options[0]
    else:
        return {"success": False, "error": f"No privacy options returned by TikTok: {ci}"}

    # 2. Init upload
    size = video_path.stat().st_size
    chunk_size, chunk_count = _plan_chunks(size)
    init = _json(client.post(
        f"{TIKTOK_API}/v2/post/publish/video/init/",
        headers=headers,
        json={
            "post_info": {
                "title": (caption or video_path.stem)[:2200],
                "privacy_level": privacy,
                "disable_comment": bool(ci.get("comment_disabled", False)),
                "disable_duet": bool(ci.get("duet_disabled", False)),
                "disable_stitch": bool(ci.get("stitch_disabled", False)),
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": chunk_count,
            },
        },
    ))
    if e := _api_error(init):
        return {"success": False, "error": f"Init failed: {e}"}
    publish_id = init["data"]["publish_id"]
    upload_url = init["data"].get("upload_url")
    if not upload_url:
        return {"success": False, "error": f"No upload_url returned: {init}"}
    logger.info(f"[TikTok] Init OK, publish_id={publish_id}, privacy={privacy}, chunks={chunk_count}")

    # 3. Upload chunks
    with open(video_path, "rb") as f:
        for i in range(chunk_count):
            start = i * chunk_size
            end = size - 1 if i == chunk_count - 1 else start + chunk_size - 1
            chunk = f.read(end - start + 1)
            ur = client.put(upload_url, content=chunk, headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            })
            if ur.status_code not in (200, 201, 206):
                return {"success": False, "error": f"Chunk {i+1}/{chunk_count} failed: {ur.status_code} {ur.text[:300]}"}
            logger.info(f"[TikTok] Uploaded chunk {i+1}/{chunk_count}")

    # 4. Wait for TikTok to finish processing / publishing
    for _ in range(POLL_ATTEMPTS):
        s = _json(client.post(f"{TIKTOK_API}/v2/post/publish/status/fetch/",
                              headers=headers, json={"publish_id": publish_id}))
        if e := _api_error(s):
            return {"success": False, "error": f"Status check failed: {e}"}
        d = s.get("data", {})
        status = d.get("status")
        logger.info(f"[TikTok] Status: {status}")
        if status == "PUBLISH_COMPLETE":
            ids = d.get("publicaly_available_post_id") or d.get("publicly_available_post_id") or []
            return {"success": True, "post_id": str(ids[0]) if ids else publish_id,
                    "privacy": privacy}
        if status == "FAILED":
            return {"success": False, "error": f"TikTok publish failed: {d.get('fail_reason')}"}
        time.sleep(POLL_INTERVAL)
    return {"success": False, "error": "Timeout waiting for TikTok to publish"}
