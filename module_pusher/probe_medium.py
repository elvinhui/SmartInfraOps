"""
Medium API Probe v3 - Auth verification + post creation endpoints.
Focus on finding auth-required endpoints and the correct import/publish pattern.
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
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"URL:  {url} [{method}]")
    
    h = headers or {}
    h.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    h.setdefault("Accept", "application/json")
    
    if cookie_str:
        h["Cookie"] = cookie_str
    
    body = None
    if data is not None:
        if isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = json.dumps(data).encode("utf-8")
            h["Content-Type"] = "application/json"
    
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
            clean = raw.replace("])}while(1);</x>", "")
            print(f"✅ Status: {code}")
            # Check if it's a Cloudflare challenge
            if "Just a moment" in clean:
                print("⚠️  Cloudflare challenge page!")
            else:
                print(f"Response:\n{clean[:1000]}")
            return code, clean
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        clean = raw.replace("])}while(1);</x>", "")
        print(f"❌ HTTP Error: {e.code}")
        if "Just a moment" in clean:
            print("⚠️  Cloudflare challenge page!")
        else:
            print(f"Response:\n{clean[:1000]}")
        return e.code, clean
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None, str(e)

def main():
    if not MEDIUM_SID:
        print("Error: MEDIUM_SID not set.")
        sys.exit(1)
    
    print("=" * 60)
    print("MEDIUM API PROBE v3 — Auth + Post Creation")
    print("=" * 60)
    
    cookies = f"sid={MEDIUM_SID}; uid={MEDIUM_UID}"
    if MEDIUM_XSRF:
        cookies += f"; xsrf={MEDIUM_XSRF}"
    
    base_headers = {}
    if MEDIUM_XSRF:
        base_headers["x-xsrf-token"] = MEDIUM_XSRF
    
    # ===== PART A: Auth verification =====
    print("\n\n>>> PART A: Auth Verification <<<")
    
    # Test 1: /me/settings?format=json (MUST be logged in)
    try_request(
        "Auth check: /me/settings?format=json",
        "https://medium.com/me/settings?format=json",
        headers=dict(base_headers),
        cookie_str=cookies
    )
    
    # Test 2: /me/stats?format=json (MUST be logged in)
    try_request(
        "Auth check: /me/stats?format=json",
        "https://medium.com/me/stats?format=json",
        headers=dict(base_headers),
        cookie_str=cookies
    )
    
    # Test 3: /me/notifications?format=json (MUST be logged in)
    try_request(
        "Auth check: /me/notifications?format=json",
        "https://medium.com/me/notifications?format=json",
        headers=dict(base_headers),
        cookie_str=cookies
    )
    
    # Test 4: /_/api/users/lo_xxx/profile (explicit UID path)
    try_request(
        "Auth check: /_/api/users/<uid>/profile",
        f"https://medium.com/_/api/users/{MEDIUM_UID}/profile",
        headers=dict(base_headers),
        cookie_str=cookies
    )
    
    # ===== PART B: Post creation endpoints =====
    print("\n\n>>> PART B: Post Creation Endpoints <<<")
    
    test_content = {
        "title": "Test Post",
        "content": "<p>Test content</p>",
        "contentFormat": "html",
        "canonicalUrl": "https://www.smartinfralog.com/posts/post-1781921757/",
        "publishStatus": "draft"
    }
    
    # Test 5: POST /_/api/posts (internal create)
    try_request(
        "Create post: POST /_/api/posts",
        "https://medium.com/_/api/posts",
        method="POST",
        headers=dict(base_headers),
        cookie_str=cookies,
        data=test_content
    )
    
    # Test 6: POST /_/api/users/<uid>/posts
    try_request(
        "Create post: POST /_/api/users/<uid>/posts",
        f"https://medium.com/_/api/users/{MEDIUM_UID}/posts",
        method="POST",
        headers=dict(base_headers),
        cookie_str=cookies,
        data=test_content
    )
    
    # Test 7: Try form-style import (like the import page does)
    form_data = urllib.parse.urlencode({"url": "https://www.smartinfralog.com/posts/post-1781921757/"})
    import urllib.parse
    try_request(
        "Import: POST /p/import (form data)",
        "https://medium.com/p/import",
        method="POST",
        headers={**base_headers, "Content-Type": "application/x-www-form-urlencoded"},
        cookie_str=cookies,
        data=form_data
    )

    # ===== PART C: Without cookies (control) =====
    print("\n\n>>> PART C: Control (no cookies) <<<")
    
    try_request(
        "Control: /me/settings without cookies",
        "https://medium.com/me/settings?format=json",
    )
    
    print("\n" + "=" * 60)
    print("PROBE v3 COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
