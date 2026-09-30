"""
Local web dashboard for AgencyPost.
Run together with the watcher via main.py, or standalone:
  uvicorn dashboard:app --host 127.0.0.1 --port 8787 --reload
"""

from pathlib import Path
from datetime import datetime
import json

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import CLIENTS_DIR, BASE_DIR
from db import (
    get_connection, get_or_create_client, get_account, save_account,
    init_db
)

app = FastAPI(title="AgencyPost Dashboard")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def list_clients():
    clients = []
    if CLIENTS_DIR.exists():
        for p in sorted(CLIENTS_DIR.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                clients.append({"slug": p.name, "path": str(p)})
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, slug, name FROM clients ORDER BY slug")
    for row in cur.fetchall():
        slug = row["slug"]
        if not any(c["slug"] == slug for c in clients):
            clients.append({"slug": slug, "path": str(CLIENTS_DIR / slug)})
    conn.close()
    return clients


def get_client_status(slug: str):
    client_id = get_or_create_client(slug)
    platforms = ["youtube", "facebook", "instagram", "tiktok"]
    accounts = {}
    for p in platforms:
        acc = get_account(client_id, p)
        accounts[p] = {
            "connected": bool(acc and acc.get("access_token")),
            "account_name": acc.get("account_name") if acc else None,
            "account_id": acc.get("account_id") if acc else None,
        }

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, platform, status, title, scheduled_at, posted_at, error_message, created_at
        FROM post_queue
        WHERE client_id = ?
        ORDER BY created_at DESC
        LIMIT 20
    """, (client_id,))
    queue = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "slug": slug,
        "client_id": client_id,
        "accounts": accounts,
        "queue": queue,
    }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    clients = list_clients()
    statuses = [get_client_status(c["slug"]) for c in clients]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "clients": statuses,
        "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    })


@app.get("/client/{slug}", response_class=HTMLResponse)
async def client_detail(request: Request, slug: str):
    status = get_client_status(slug)
    return templates.TemplateResponse("client.html", {
        "request": request,
        "client": status,
        "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    })


@app.post("/client/{slug}/connect")
async def connect_account(
    slug: str,
    platform: str = Form(...),
    access_token: str = Form(...),
    refresh_token: str = Form(""),
    account_id: str = Form(""),
    account_name: str = Form(""),
    client_id_oauth: str = Form(""),
    client_secret: str = Form(""),
):
    cid = get_or_create_client(slug)
    extra = {}
    if client_id_oauth:
        extra["client_id"] = client_id_oauth
    if client_secret:
        extra["client_secret"] = client_secret

    save_account(cid, platform, {
        "access_token": access_token.strip(),
        "refresh_token": refresh_token.strip() or None,
        "account_id": account_id.strip() or None,
        "account_name": account_name.strip() or None,
        "extra_data": json.dumps(extra) if extra else None,
    })
    return RedirectResponse(f"/client/{slug}", status_code=303)


@app.post("/client/create")
async def create_client(slug: str = Form(...), name: str = Form("")):
    slug = slug.strip().lower().replace(" ", "_")
    if not slug:
        return RedirectResponse("/", status_code=303)
    get_or_create_client(slug, name or slug)
    for sub in ("ready", "posted", "failed"):
        (CLIENTS_DIR / slug / sub).mkdir(parents=True, exist_ok=True)
    return RedirectResponse(f"/client/{slug}", status_code=303)


@app.get("/api/status")
async def api_status():
    clients = list_clients()
    return {
        "clients": [get_client_status(c["slug"]) for c in clients],
        "time": datetime.utcnow().isoformat(),
    }


init_db()
