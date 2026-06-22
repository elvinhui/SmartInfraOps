import os
import sys
import urllib.request
import urllib.parse
import json

RSS_URL = os.getenv("RSS_URL", "https://smartinfralog.com/index.xml")
POSTED_URLS_FILE = os.path.join(os.path.dirname(__file__), "posted_urls.txt")
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE_NUMBER")
WHATSAPP_APIKEY = os.getenv("WHATSAPP_API_KEY")

# --- Utility Functions ---

def load_posted_urls():
    if not os.path.exists(POSTED_URLS_FILE):
        return set()
    with open(POSTED_URLS_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip() and not line.startswith("#"))

def append_posted_url(url):
    with open(POSTED_URLS_FILE, "a") as f:
        f.write(f"{url}\n")

def send_whatsapp(message):
    """Send a WhatsApp message via CallMeBot API."""
    if not WHATSAPP_PHONE or not WHATSAPP_APIKEY:
        print("  [WhatsApp] Credentials not configured, printing to console only.")
        print(f"  [Message] {message}")
        return False

    encoded_msg = urllib.parse.quote_plus(message)
    api_url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={WHATSAPP_PHONE}"
        f"&text={encoded_msg}"
        f"&apikey={WHATSAPP_APIKEY}"
    )
    
    try:
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            print(f"  [WhatsApp] Sent (HTTP {status})")
            return True
    except Exception as e:
        print(f"  [WhatsApp] Failed to send: {e}")
        return False

def fetch_rss_entries():
    """Fetch RSS entries via rss2json proxy."""
    print(f"Fetching RSS feed from {RSS_URL} via rss2json...")
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={RSS_URL}"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())

    if data.get("status") != "ok":
        raise RuntimeError(f"rss2json error: {data.get('message', 'Unknown')}")

    return data.get("items", [])

# --- Main ---

def main():
    # Step 1: Fetch RSS
    try:
        entries = fetch_rss_entries()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not entries:
        print("Feed contains no entries.")
        sys.exit(1)

    # Step 2: Find new articles
    posted_urls = load_posted_urls()
    new_articles = []

    for entry in reversed(entries):  # oldest first
        link = entry.get("link")
        title = entry.get("title", "Untitled")
        if link and link not in posted_urls:
            new_articles.append((title, link))

    if not new_articles:
        print("No new articles found. Nothing to notify.")
        return

    print(f"Found {len(new_articles)} new article(s). Sending notifications...\n")

    # Step 3: Send WhatsApp notification for each new article
    for title, url in new_articles:
        print(f"→ {title}")

        message = (
            f"📝 *New Article Ready for Medium*\n"
            f"\n"
            f"*{title}*\n"
            f"\n"
            f"🔗 Original: {url}\n"
            f"\n"
            f"👉 Import here: https://medium.com/p/import\n"
            f"Paste the URL above into Medium's import page."
        )

        send_whatsapp(message)
        append_posted_url(url)
        print()

    print(f"Done! Notified {len(new_articles)} article(s).")

if __name__ == "__main__":
    main()
