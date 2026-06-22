"""
Medium API Probe - Tests multiple approaches to bypass Cloudflare.
Run this once to find which method works.
"""
import os
import sys
import json
import urllib.request
import urllib.error
import http.cookiejar

MEDIUM_SID = os.getenv("MEDIUM_SID", "")
MEDIUM_UID = os.getenv("MEDIUM_UID", "")

def try_request(label, url, headers=None, cookie_str=None):
    """Try a request and log the result."""
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"URL:  {url}")
    
    h = headers or {}
    h.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    h.setdefault("Accept", "application/json")
    
    if cookie_str:
        h["Cookie"] = cookie_str
    
    req = urllib.request.Request(url, headers=h)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            print(f"✅ Status: {code}")
            print(f"Response (first 500 chars):\n{body[:500]}")
            return code, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"❌ HTTP Error: {e.code}")
        print(f"Response (first 500 chars):\n{body[:500]}")
        return e.code, body
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None, str(e)

def main():
    if not MEDIUM_SID:
        print("Error: MEDIUM_SID not set.")
        sys.exit(1)
    
    print("=" * 60)
    print("MEDIUM API PROBE")
    print("Testing which endpoints work from GitHub Actions...")
    print("=" * 60)
    
    cookie = f"sid={MEDIUM_SID}; uid={MEDIUM_UID}"
    
    # --- Test 1: Official API with Bearer token (sid as token) ---
    try_request(
        "Official API /v1/me — Bearer auth (sid as token)",
        "https://api.medium.com/v1/me",
        headers={"Authorization": f"Bearer {MEDIUM_SID}"}
    )
    
    # --- Test 2: Official API with Cookie auth ---
    try_request(
        "Official API /v1/me — Cookie auth",
        "https://api.medium.com/v1/me",
        cookie_str=cookie
    )
    
    # --- Test 3: Medium internal API with Cookie auth ---
    try_request(
        "Internal API /_/api/users/me — Cookie auth",
        "https://medium.com/_/api/users/me",
        cookie_str=cookie
    )

    # --- Test 4: Medium GraphQL endpoint ---
    try_request(
        "GraphQL endpoint /_/graphql — Cookie auth (GET)",
        "https://medium.com/_/graphql?operationName=UserProfileQuery",
        cookie_str=cookie
    )

    # --- Test 5: Plain medium.com (expect Cloudflare block) ---
    try_request(
        "Plain medium.com homepage (baseline — expect CF block)",
        "https://medium.com/",
    )
    
    print("\n" + "=" * 60)
    print("PROBE COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
