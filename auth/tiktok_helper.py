"""
Get TikTok access + refresh tokens for a client account (one-time per account).

Step 1 - print the login URL and open it in a browser (log in as the TikTok account):
    python -m auth.tiktok_helper url <CLIENT_KEY> <REDIRECT_URI>

Step 2 - after approving, copy the full URL you were redirected to and run:
    python -m auth.tiktok_helper token <CLIENT_KEY> <CLIENT_SECRET> <REDIRECT_URI> "<REDIRECT_URL_OR_CODE>"

REDIRECT_URI must exactly match the one registered in your TikTok developer app.
Paste the printed tokens into the dashboard (Client ID / Client Secret go in the
"OAuth client credentials" box).
"""
import secrets
import sys
from urllib.parse import urlencode, urlparse, parse_qs, unquote

import httpx

SCOPES = "user.info.basic,video.publish"


def auth_url(client_key: str, redirect_uri: str) -> str:
    q = urlencode({"client_key": client_key, "scope": SCOPES, "response_type": "code",
                   "redirect_uri": redirect_uri, "state": secrets.token_urlsafe(8)})
    return f"https://www.tiktok.com/v2/auth/authorize/?{q}"


def extract_code(value: str) -> str:
    if value.startswith("http"):
        value = parse_qs(urlparse(value).query).get("code", [""])[0]
    return unquote(value)


def exchange(client_key, client_secret, redirect_uri, code_or_url) -> dict:
    r = httpx.post("https://open.tiktokapis.com/v2/oauth/token/",
                   headers={"Content-Type": "application/x-www-form-urlencoded"},
                   data={"client_key": client_key, "client_secret": client_secret,
                         "code": extract_code(code_or_url), "grant_type": "authorization_code",
                         "redirect_uri": redirect_uri}, timeout=30)
    return r.json()


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "url":
        print(auth_url(a[1], a[2]))
    elif len(a) == 5 and a[0] == "token":
        d = exchange(*a[1:])
        if "access_token" not in d:
            sys.exit(f"Error: {d}")
        print(f"open_id:       {d.get('open_id')}")
        print(f"access_token:  {d['access_token']}  (expires in {d.get('expires_in')}s)")
        print(f"refresh_token: {d.get('refresh_token')}  (expires in {d.get('refresh_expires_in')}s)")
        print(f"scope:         {d.get('scope')}")
    else:
        sys.exit(__doc__)
