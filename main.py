import time
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from apscheduler.schedulers.background import BackgroundScheduler
import uvicorn

from config import CLIENTS_DIR, SCHEDULER_INTERVAL, PLATFORMS
from db import init_db, get_or_create_client, add_to_queue, get_due_posts, update_queue_status, get_account
from utils import logger, load_captions, get_schedule, move_video
from posters.youtube import post_to_youtube
from posters.meta import post_to_facebook, post_to_instagram
from posters.tiktok import post_to_tiktok

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8787


class VideoHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in {".mp4", ".mov", ".mkv"}:
            return

        if path.name.startswith(".") or path.name.endswith(".tmp"):
            return

        logger.info(f"New video detected: {path}")
        self.process_video(path)

    def process_video(self, video_path: Path):
        try:
            client_folder = video_path.parent.parent
            slug = client_folder.name
            client_id = get_or_create_client(slug)

            captions = load_captions(client_folder)
            scheduled_at = get_schedule(video_path)

            for platform in PLATFORMS:
                account = get_account(client_id, platform)
                if not account:
                    logger.warning(f"No {platform} account connected for {slug} — skipping")
                    continue

                title = captions.get(platform, {}).get("title") or captions.get("title") or video_path.stem
                caption = captions.get(platform, {}).get("caption") or captions.get("caption") or ""

                queue_id = add_to_queue(
                    client_id=client_id,
                    platform=platform,
                    video_path=str(video_path),
                    caption=caption,
                    title=title,
                    scheduled_at=scheduled_at
                )
                logger.info(f"Queued {platform} post #{queue_id} for {slug}" +
                            (f" at {scheduled_at}" if scheduled_at else " (immediate)"))

        except Exception as e:
            logger.exception(f"Error processing {video_path}: {e}")


def process_due_posts():
    due = get_due_posts()
    if not due:
        return

    logger.info(f"Processing {len(due)} due posts...")

    for post in due:
        video_path = Path(post["video_path"])
        if not video_path.exists():
            update_queue_status(post["id"], "failed", error="Video file missing")
            continue

        client_id = post["client_id"]
        platform = post["platform"]
        account = get_account(client_id, platform)

        if not account:
            update_queue_status(post["id"], "failed", error="Account not found")
            continue

        try:
            update_queue_status(post["id"], "uploading")

            if platform == "youtube":
                result = post_to_youtube(account, video_path, post["title"], post["caption"])
            elif platform == "facebook":
                result = post_to_facebook(account, video_path, post["caption"])
            elif platform == "instagram":
                result = post_to_instagram(account, video_path, post["caption"])
            elif platform == "tiktok":
                result = post_to_tiktok(account, video_path, post["caption"])
            else:
                raise ValueError(f"Unknown platform: {platform}")

            if result.get("success"):
                update_queue_status(post["id"], "posted", platform_post_id=result.get("post_id"))
                logger.info(f"Successfully posted to {platform}: {result.get('post_id')}")
            else:
                update_queue_status(post["id"], "failed", error=result.get("error", "Unknown error"))
                logger.error(f"Failed {platform}: {result.get('error')}")

        except Exception as e:
            update_queue_status(post["id"], "failed", error=str(e))
            logger.exception(f"Exception posting to {platform}: {e}")


def start_dashboard():
    """Run the FastAPI dashboard in a background thread."""
    from dashboard import app
    config = uvicorn.Config(
        app,
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


def main():
    init_db()
    logger.info("AgencyPost service starting...")

    # Start web dashboard
    dash_thread = threading.Thread(target=start_dashboard, daemon=True)
    dash_thread.start()
    logger.info(f"Dashboard available at http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")

    # Start folder watcher
    event_handler = VideoHandler()
    observer = Observer()
    observer.schedule(event_handler, str(CLIENTS_DIR), recursive=True)
    observer.start()
    logger.info(f"Watching folder: {CLIENTS_DIR}")

    # Start scheduler for delayed posts
    scheduler = BackgroundScheduler()
    scheduler.add_job(process_due_posts, "interval", seconds=SCHEDULER_INTERVAL)
    scheduler.start()
    logger.info("Scheduler started")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        observer.stop()
        scheduler.shutdown()
    observer.join()


if __name__ == "__main__":
    main()
