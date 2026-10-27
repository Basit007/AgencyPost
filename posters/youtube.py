"""
YouTube uploader using YouTube Data API v3.
Requires the account dict to contain at least:
  - refresh_token
  - client_id
  - client_secret
Optional: access_token, token_uri, account_id (channel id)
"""

from pathlib import Path
from utils import logger

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
except ImportError:
    Credentials = None  # type: ignore


def post_to_youtube(account: dict, video_path: Path, title: str, description: str,
                    privacy_status: str = "private", publish_at: str | None = None) -> dict:
    """
    Upload a video to YouTube.

    privacy_status: "public" | "private" | "unlisted"
    publish_at: ISO 8601 UTC string (e.g. "2026-09-30T14:00:00Z").
                Only works when privacy_status="private".
    """
    if Credentials is None:
        return {"success": False, "error": "google-api-python-client / google-auth not installed"}

    try:
        refresh_token = account.get("refresh_token")

        # NOTE: account["client_id"] is the internal AgencyPost client row id, NOT the
        # Google OAuth client id. OAuth credentials live in extra_data only.
        import json
        extra = account.get("extra_data") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        client_id = extra.get("client_id")
        client_secret = extra.get("client_secret")

        if not refresh_token:
            return {"success": False, "error": "Missing refresh_token in account"}

        if not client_id or not client_secret:
            return {
                "success": False,
                "error": "Missing client_id / client_secret. Store them in the account's extra_data "
                         "(dashboard: 'OAuth client credentials')."
            }

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=account.get("token_uri") or "https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )
        # Always fetch a fresh access token (pasted ones expire after ~1 hour)
        creds.refresh(Request())

        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": (title or video_path.stem)[:100],
                "description": description or "",
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        if publish_at and privacy_status == "private":
            body["status"]["publishAt"] = publish_at

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=8 * 1024 * 1024,
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"[YouTube] Upload progress: {int(status.progress() * 100)}%")

        video_id = response.get("id")
        logger.info(f"[YouTube] Uploaded successfully: {video_id}")
        return {"success": True, "post_id": video_id}

    except HttpError as e:
        error_content = e.content.decode("utf-8") if e.content else str(e)
        logger.error(f"[YouTube] HttpError: {error_content}")
        return {"success": False, "error": f"YouTube API error: {error_content}"}
    except Exception as e:
        logger.exception(f"[YouTube] Unexpected error: {e}")
        return {"success": False, "error": str(e)}
