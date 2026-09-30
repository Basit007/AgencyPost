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
        client_id = account.get("client_id")
        client_secret = account.get("client_secret")

        # Fallback: try to parse extra_data if it is a JSON string
        if (not client_id or not client_secret) and account.get("extra_data"):
            import json
            try:
                extra = json.loads(account["extra_data"]) if isinstance(account["extra_data"], str) else account["extra_data"]
                client_id = client_id or extra.get("client_id")
                client_secret = client_secret or extra.get("client_secret")
            except Exception:
                pass

        if not refresh_token:
            return {"success": False, "error": "Missing refresh_token in account"}

        if not client_id or not client_secret:
            return {
                "success": False,
                "error": "Missing client_id / client_secret. Store them in the account record (or in extra_data JSON)."
            }

        creds = Credentials(
            token=account.get("access_token"),
            refresh_token=refresh_token,
            token_uri=account.get("token_uri") or "https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                return {"success": False, "error": "Credentials are invalid and cannot be refreshed"}

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
