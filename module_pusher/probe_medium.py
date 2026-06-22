"""
Medium API Probe v2 - Targeted test with full cookie auth + CSRF token.
The /_/api/ endpoints bypass Cloudflare. Now we test proper auth.
"""
import os
import sys
import json
import urllib.request
import urllib.error

MEDIUM_SID = os.getenv("MEDIUM_SID", "")
MEDIUM_UID = os.getenv("MEDIUM_UID", "")
MEDIUM_XSRF = os.getenv("MEDIUM_XSRF", "")

def try_request(label, url, method="GET", headers=None, cookie_str=None, data=None):
    """Try a request and log the result."""
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"URL:  {url} [{method}]")
    
    h = headers or {}
    h.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    h.setdefault("Accept", "application/json")
    
    if cookie_str:
        h["Cookie"] = cookie_str
    
    body = None
    if data:
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"
    
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
            print(f"✅ Status: {code}")
            # Strip Medium's XSS protection prefix
            clean = raw.replace("])}while(1);</x>", "")
            print(f"Response:\n{clean[:800]}")
            return code, clean
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        clean = raw.replace("])}while(1);</x>", "")
        print(f"❌ HTTP Error: {e.code}")
        print(f"Response:\n{clean[:800]}")
        return e.code, clean
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None, str(e)

def main():
    if not MEDIUM_SID:
        print("Error: MEDIUM_SID not set.")
        sys.exit(1)
    
    print("=" * 60)
    print("MEDIUM API PROBE v2 — Full Auth + CSRF")
    print("=" * 60)
    
    # Full cookie string
    cookies = f"sid={MEDIUM_SID}; uid={MEDIUM_UID}"
    if MEDIUM_XSRF:
        cookies += f"; xsrf={MEDIUM_XSRF}"
    
    # Headers with CSRF token
    auth_headers = {}
    if MEDIUM_XSRF:
        auth_headers["x-xsrf-token"] = MEDIUM_XSRF
    
    print(f"\nCookies set: sid=***, uid={MEDIUM_UID}, xsrf={'set' if MEDIUM_XSRF else 'NOT SET'}")
    
    # --- Test 1: /_/api/me (common internal endpoint) ---
    try_request(
        "Internal API: /_/api/me",
        "https://medium.com/_/api/me",
        headers=dict(auth_headers),
        cookie_str=cookies
    )
    
    # --- Test 2: /_/api/users/{uid} ---
    try_request(
        f"Internal API: /_/api/users/{MEDIUM_UID}",
        f"https://medium.com/_/api/users/{MEDIUM_UID}",
        headers=dict(auth_headers),
        cookie_str=cookies
    )
    
    # --- Test 3: /@me endpoint ---
    try_request(
        "Internal API: /@me",
        "https://medium.com/@me?format=json",
        headers=dict(auth_headers),
        cookie_str=cookies
    )
    
    # --- Test 4: Import story endpoint (GET to discover) ---
    try_request(
        "Import endpoint: /_/api/posts/import (GET probe)",
        "https://medium.com/_/api/posts/import",
        headers=dict(auth_headers),
        cookie_str=cookies
    )
    
    # --- Test 5: Try POST to import with a test URL ---
    test_url = "https://www.smartinfralog.com/posts/post-1781921757/"
    try_request(
        "Import endpoint: POST /_/api/posts/import",
        "https://medium.com/_/api/posts/import",
        method="POST",
        headers=dict(auth_headers),
        cookie_str=cookies,
        data={"url": test_url}
    )
    
    # --- Test 6: Try another import pattern ---
    try_request(
        "Import endpoint: POST /p/import with JSON",
        "https://medium.com/p/import",
        method="POST",
        headers=dict(auth_headers),
        cookie_str=cookies,
        data={"url": test_url}
    )
    
    # --- Test 7: Medium API v1 with cookie (control test) ---
    try_request(
        "Control: api.medium.com/v1/me with cookies + xsrf",
        "https://api.medium.com/v1/me",
        headers=dict(auth_headers),
        cookie_str=cookies
    )
    
    print("\n" + "=" * 60)
    print("PROBE v2 COMPLETE — Send these results back!")
    print("=" * 60)

if __name__ == "__main__":
    main()
