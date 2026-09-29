import sqlite3
from datetime import datetime
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        account_id TEXT,
        account_name TEXT,
        access_token TEXT,
        refresh_token TEXT,
        token_expires_at TEXT,
        extra_data TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (client_id) REFERENCES clients(id),
        UNIQUE(client_id, platform)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS post_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        video_path TEXT NOT NULL,
        caption TEXT,
        title TEXT,
        scheduled_at TEXT,
        status TEXT DEFAULT 'pending',
        platform_post_id TEXT,
        error_message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        posted_at TEXT,
        FOREIGN KEY (client_id) REFERENCES clients(id)
    )
    """)

    conn.commit()
    conn.close()
    print("Database initialized.")

def get_or_create_client(slug: str, name: str = None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM clients WHERE slug = ?", (slug,))
    row = cur.fetchone()
    if row:
        client_id = row["id"]
    else:
        cur.execute("INSERT INTO clients (slug, name) VALUES (?, ?)", (slug, name or slug))
        client_id = cur.lastrowid
        conn.commit()
    conn.close()
    return client_id

def get_account(client_id: int, platform: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM accounts WHERE client_id = ? AND platform = ?",
        (client_id, platform)
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def save_account(client_id: int, platform: str, data: dict):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO accounts (client_id, platform, account_id, account_name,
                              access_token, refresh_token, token_expires_at, extra_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id, platform) DO UPDATE SET
            account_id = excluded.account_id,
            account_name = excluded.account_name,
            access_token = excluded.access_token,
            refresh_token = excluded.refresh_token,
            token_expires_at = excluded.token_expires_at,
            extra_data = excluded.extra_data
    """, (
        client_id, platform,
        data.get("account_id"),
        data.get("account_name"),
        data.get("access_token"),
        data.get("refresh_token"),
        data.get("token_expires_at"),
        data.get("extra_data")
    ))
    conn.commit()
    conn.close()

def add_to_queue(client_id: int, platform: str, video_path: str,
                 caption: str = "", title: str = "", scheduled_at: str = None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO post_queue (client_id, platform, video_path, caption, title, scheduled_at, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
    """, (client_id, platform, str(video_path), caption, title, scheduled_at))
    conn.commit()
    queue_id = cur.lastrowid
    conn.close()
    return queue_id

def get_due_posts():
    """Return posts that are pending and scheduled_at is null or in the past."""
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute("""
        SELECT * FROM post_queue
        WHERE status = 'pending'
          AND (scheduled_at IS NULL OR scheduled_at <= ?)
        ORDER BY created_at
    """, (now,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def update_queue_status(queue_id: int, status: str, platform_post_id: str = None, error: str = None):
    conn = get_connection()
    cur = conn.cursor()
    posted_at = datetime.utcnow().isoformat() if status == "posted" else None
    cur.execute("""
        UPDATE post_queue
        SET status = ?, platform_post_id = ?, error_message = ?, posted_at = ?
        WHERE id = ?
    """, (status, platform_post_id, error, posted_at, queue_id))
    conn.commit()
    conn.close()
