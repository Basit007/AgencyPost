"""
Meta (Facebook + Instagram) token helper.

Commands (run from the project folder):

  1) python -m auth.meta_helper exchange <APP_ID> <APP_SECRET> <SHORT_LIVED_USER_TOKEN>
       Turns the short-lived token from Graph API Explorer into a long-lived user token.

  2) python -m auth.meta_helper connect <CLIENT_SLUG> <LONG_LIVED_USER_TOKEN> [PAGE_ID]
       Finds the Facebook Page + linked Instagram Business account and saves BOTH
       accounts (with the never-expiring Page token and the numeric IDs) straight
       into the AgencyPost database for that client. PAGE_ID is only needed if
       you manage several Pages.

  3) python -m auth.meta_helper pages <USER_TOKEN>
       Just list your Pages, Page IDs and Instagram IDs (tokens are not printed).

  4) python -m auth.meta_helper check <TOKEN> <APP_ID> <APP_SECRET>
       Tells you whether a token is valid, when it expires and which permissions it has.

Tokens are never printed except by `exchange` (which you need to copy).
"""
import sys
from datetime import datetime, timezone

import httpx

GRAPH = "https://graph.facebook.com/v21.0"


def _get(path, params, client=None):
    c = client or httpx
    return c.get(f"{GRAPH}/{path}", params=params, timeout=30).json()


def exchange(app_id, app_secret, short_token, client=None) -> dict:
    return _get("oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": app_secret, "fb_exchange_token": short_token}, client)


def list_pages(user_token, client=None) -> list[dict]:
    r = _get("me/accounts", {
        "fields": "id,name,access_token,instagram_business_account{id,username}",
        "limit": 100, "access_token": user_token}, client)
    if "error" in r:
        raise RuntimeError(r["error"].get("message", str(r["error"])))
    return r.get("data", [])


def check_token(token, app_id, app_secret, client=None) -> dict:
    r = _get("debug_token", {"input_token": token,
                             "access_token": f"{app_id}|{app_secret}"}, client)
    return r.get("data", r)


def connect(slug, user_token, page_id=None, client=None) -> list[str]:
    """Save Facebook (+ Instagram) accounts for client `slug`. Returns status lines."""
    from db import get_or_create_client, get_account, save_account

    pages = list_pages(user_token, client)
    if not pages:
        raise RuntimeError("No Pages found. The token needs pages_show_list and you must be an admin of the Page.")
    if page_id:
        pages = [p for p in pages if p["id"] == str(page_id)]
        if not pages:
            raise RuntimeError(f"Page {page_id} not found among your Pages.")
    elif len(pages) > 1:
        names = "\n".join(f"  {p['id']}  {p['name']}" for p in pages)
        raise RuntimeError(f"You manage several Pages - pass PAGE_ID as the last argument:\n{names}")

    page = pages[0]
    token = page["access_token"]
    ig = page.get("instagram_business_account") or {}
    cid = get_or_create_client(slug)
    out = []

    def _save(platform, account_id, name):
        existing = get_account(cid, platform) or {}
        save_account(cid, platform, {
            "account_id": account_id, "account_name": name,
            "access_token": token, "refresh_token": existing.get("refresh_token"),
            "token_expires_at": None, "extra_data": existing.get("extra_data")})

    # verify the Page token really works before reporting success
    chk = _get(page["id"], {"fields": "id,name", "access_token": token}, client)
    if "error" in chk:
        raise RuntimeError(f"Page token rejected: {chk['error'].get('message')}")
    _save("facebook", page["id"], page["name"])
    out.append(f"Facebook  saved: {page['name']} (Page ID {page['id']})")

    if ig.get("id"):
        _save("instagram", ig["id"], f"@{ig.get('username')}" if ig.get("username") else page["name"])
        out.append(f"Instagram saved: @{ig.get('username')} (ID {ig['id']})")
    else:
        out.append("Instagram NOT saved: no Instagram Business/Creator account is linked to this Page.")
    return out


def _fmt_ts(ts):
    if not ts:
        return "never"
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(a):
    if len(a) == 4 and a[0] == "exchange":
        d = exchange(a[1], a[2], a[3])
        if "access_token" not in d:
            sys.exit(f"Error: {d.get('error', {}).get('message', d)}")
        print("Long-lived user token (copy it for the next step):")
        print(d["access_token"])
    elif len(a) in (3, 4) and a[0] == "connect":
        try:
            for line in connect(a[1], a[2], a[3] if len(a) == 4 else None):
                print(line)
        except RuntimeError as e:
            sys.exit(f"Error: {e}")
    elif len(a) == 2 and a[0] == "pages" or len(a) == 1 and a[0] not in ("exchange", "connect", "pages", "check"):
        try:
            pages = list_pages(a[-1])
        except RuntimeError as e:
            sys.exit(f"Error: {e}")
        for p in pages:
            ig = p.get("instagram_business_account") or {}
            print(f"{p['name']}: Page ID {p['id']} | Instagram ID {ig.get('id', 'n/a (not linked)')}"
                  + (f" (@{ig['username']})" if ig.get("username") else ""))
    elif len(a) == 4 and a[0] == "check":
        d = check_token(a[1], a[2], a[3])
        if d.get("error") and "is_valid" not in d:
            sys.exit(f"Error: {d['error']}")
        print(f"Valid:        {d.get('is_valid')}")
        print(f"Type:         {d.get('type')}")
        print(f"Expires:      {_fmt_ts(d.get('expires_at'))}")
        print(f"Permissions:  {', '.join(d.get('scopes', []))}")
        if d.get("error"):
            print(f"Problem:      {d['error'].get('message')}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])