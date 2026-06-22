import os
import sys
import urllib.request
import json

RSS_URL = os.getenv("RSS_URL", "https://smartinfralog.com/index.xml")
POSTED_URLS_FILE = os.path.join(os.path.dirname(__file__), "posted_urls.txt")
MEDIUM_TOKEN = os.getenv("MEDIUM_TOKEN")

# --- Utility Functions ---

def load_posted_urls():
    if not os.path.exists(POSTED_URLS_FILE):
        return set()
    with open(POSTED_URLS_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip() and not line.startswith("#"))

def append_posted_url(url):
    with open(POSTED_URLS_FILE, "a") as f:
        f.write(f"{url}\n")

def medium_api_request(endpoint, method="GET", data=None):
    """Make an authenticated request to the Medium API."""
    url = f"https://api.medium.com/v1{endpoint}"
    headers = {
        "Authorization": f"Bearer {MEDIUM_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Charset": "utf-8",
    }
    
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())

def get_medium_user_id():
    """Get the authenticated user's Medium ID."""
    result = medium_api_request("/me")
    user_id = result["data"]["id"]
    print(f"Authenticated as: {result['data'].get('username', 'unknown')}")
    return user_id

def fetch_article_html(url):
    """Fetch the full HTML content of an article page."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")

def extract_article_content(html):
    """Extract the main article title and body from Hugo-generated HTML."""
    import re
    
    # Extract title from <title> tag or <h1>
    title = "Untitled"
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
        # Remove site name suffix like " | SmartInfraLog"
        title = re.split(r'\s*[\|–—-]\s*SmartInfraLog', title)[0].strip()
    
    # Try to extract <article> content first (Hugo's typical structure)
    article_match = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL | re.IGNORECASE)
    if article_match:
        body = article_match.group(1)
    else:
        # Fallback: extract main content area
        main_match = re.search(r'<main[^>]*>(.*?)</main>', html, re.DOTALL | re.IGNORECASE)
        if main_match:
            body = main_match.group(1)
        else:
            # Last resort: use the RSS description
            body = None
    
    return title, body

def push_to_medium(user_id, article_url, rss_description=""):
    """Push an article to Medium as a draft using the official API."""
    print(f"  Fetching article content from {article_url}...")
    
    try:
        html = fetch_article_html(article_url)
        title, body_html = extract_article_content(html)
    except Exception as e:
        print(f"  Warning: Could not fetch article HTML: {e}")
        title = article_url.split("/")[-2] if article_url.endswith("/") else article_url.split("/")[-1]
        body_html = None
    
    # If we couldn't extract body, fall back to RSS description
    if not body_html:
        if rss_description:
            body_html = f"<p>{rss_description}</p>"
        else:
            print(f"  Error: No content available for {article_url}")
            return False
    
    # Build the post payload
    post_data = {
        "title": title,
        "contentFormat": "html",
        "content": body_html,
        "canonicalUrl": article_url,
        "publishStatus": "draft",
    }
    
    print(f"  Publishing draft: \"{title}\"")
    
    try:
        result = medium_api_request(f"/users/{user_id}/posts", method="POST", data=post_data)
        post_url = result["data"].get("url", "unknown")
        print(f"  ✓ Draft created: {post_url}")
        return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"  ✗ Medium API error ({e.code}): {error_body}")
        return False
    except Exception as e:
        print(f"  ✗ Failed to create draft: {e}")
        return False

# --- Main ---

def main():
    if not MEDIUM_TOKEN:
        print("Error: MEDIUM_TOKEN environment variable is not set.")
        print("Go to Medium → Settings → Security and apps → Integration tokens to generate one.")
        sys.exit(1)
    
    # Step 1: Authenticate and get user ID
    print("Authenticating with Medium API...")
    try:
        user_id = get_medium_user_id()
    except Exception as e:
        print(f"Error: Failed to authenticate with Medium: {e}")
        sys.exit(1)
    
    # Step 2: Fetch RSS feed
    print(f"Fetching RSS feed from {RSS_URL} via rss2json...")
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={RSS_URL}"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
    except Exception as e:
        print(f"Error fetching RSS feed: {e}")
        sys.exit(1)
    
    if data.get("status") != "ok":
        print(f"Error: rss2json returned: {data.get('message', 'Unknown')}")
        sys.exit(1)
    
    entries = data.get("items", [])
    if not entries:
        print("Warning: Feed contains no entries.")
        sys.exit(1)
    
    # Step 3: Find new articles
    posted_urls = load_posted_urls()
    new_entries = []
    
    for entry in reversed(entries):
        link = entry.get("link")
        desc = entry.get("description", "")
        if link and link not in posted_urls:
            new_entries.append((link, desc))
    
    if not new_entries:
        print("No new articles to push to Medium.")
        return
    
    print(f"Found {len(new_entries)} new article(s) to push.\n")
    
    # Step 4: Push each article
    success_count = 0
    for url, desc in new_entries:
        print(f"Processing: {url}")
        if push_to_medium(user_id, url, desc):
            append_posted_url(url)
            success_count += 1
            print()
        else:
            print(f"\nStopping due to failure on {url}.")
            sys.exit(1)
    
    print(f"\nDone! Successfully pushed {success_count} article(s) to Medium as drafts.")

if __name__ == "__main__":
    main()
