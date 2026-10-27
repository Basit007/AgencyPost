"""
Find the Page ID, Page access token and linked Instagram Business account ID
from a (long-lived) Facebook USER access token.

Usage:
    python -m auth.meta_helper <USER_ACCESS_TOKEN>

Page tokens obtained from a long-lived user token do not expire.
"""
import sys
import httpx

GRAPH = "https://graph.facebook.com/v21.0"


def main(user_token: str):
    r = httpx.get(f"{GRAPH}/me/accounts", params={
        "fields": "id,name,access_token,instagram_business_account{id,username}",
        "limit": 100, "access_token": user_token}, timeout=30).json()
    if "error" in r:
        print("Error:", r["error"].get("message"))
        return
    pages = r.get("data", [])
    if not pages:
        print("No Pages found. Check that the token has pages_show_list and you manage a Page.")
        return
    for p in pages:
        ig = p.get("instagram_business_account") or {}
        print("-" * 60)
        print(f"Page:          {p['name']}")
        print(f"Facebook ID:   {p['id']}")
        print(f"Page token:    {p['access_token']}")
        print(f"Instagram ID:  {ig.get('id', 'n/a (no IG Business account linked)')}"
              + (f"  (@{ig['username']})" if ig.get("username") else ""))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
