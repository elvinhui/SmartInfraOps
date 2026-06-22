import os
import sys
from playwright.sync_api import sync_playwright

RSS_URL = os.getenv("RSS_URL", "https://smartinfralog.com/index.xml")
POSTED_URLS_FILE = os.path.join(os.path.dirname(__file__), "posted_urls.txt")
AUTH_JSON_FILE = os.getenv("MEDIUM_AUTH_JSON_FILE", "medium_auth.json")

def load_posted_urls():
    if not os.path.exists(POSTED_URLS_FILE):
        return set()
    with open(POSTED_URLS_FILE, "r") as f:
        # Ignore comments and empty lines
        return set(line.strip() for line in f if line.strip() and not line.startswith("#"))

def append_posted_url(url):
    with open(POSTED_URLS_FILE, "a") as f:
        f.write(f"{url}\n")

def push_to_medium(url):
    with sync_playwright() as p:
        if not os.path.exists(AUTH_JSON_FILE):
            print(f"Error: {AUTH_JSON_FILE} not found. Cannot authenticate with Medium.")
            sys.exit(1)

        print(f"Starting browser with state from {AUTH_JSON_FILE}...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=AUTH_JSON_FILE)
        page = context.new_page()
        
        try:
            print(f"Navigating to Medium import page...")
            page.goto("https://medium.com/p/import", timeout=60000)
            page.wait_for_load_state('domcontentloaded', timeout=30000)
            
            # Debug: log what page we actually landed on
            print(f"DEBUG: Current URL = {page.url}")
            print(f"DEBUG: Page title = {page.title()}")
            page.screenshot(path="debug_medium_page.png", full_page=True)
            print("DEBUG: Screenshot saved to debug_medium_page.png")
            print(f"DEBUG: Page content (first 2000 chars):")
            print(page.content()[:2000])
            
            # Check if we are actually logged in by looking for import input
            page.wait_for_selector('input[type="url"]', timeout=30000)
            
            print(f"Submitting URL: {url}")
            page.fill('input[type="url"]', url)
            page.keyboard.press("Enter")
            
            # Wait for "Import" button
            page.wait_for_selector('button:has-text("Import")', timeout=30000)
            page.click('button:has-text("Import")')
            
            # Wait for the editor to load or for import to finish
            page.wait_for_load_state('networkidle', timeout=60000)
            
            # Check if it loaded the editor by looking for 'Publish' button
            try:
                page.wait_for_selector('button:has-text("Publish")', timeout=30000)
                # At this point, the article is imported as a draft on Medium.
                # The canonical URL is automatically set by Medium's import tool.
            except Exception as e:
                print("Could not find Publish button, but import may have succeeded.")
                
            print(f"Successfully imported {url} to Medium (Saved as Draft).")
            return True
        except Exception as e:
            print(f"Failed to push {url} to Medium: {e}")
            return False
        finally:
            browser.close()

import urllib.request
import json

def main():
    print(f"Fetching RSS feed from {RSS_URL} via rss2json...")
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={RSS_URL}"
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
    except Exception as e:
        print(f"Error fetching from rss2json: {e}")
        sys.exit(1)
        
    if data.get('status') != 'ok':
        print(f"Warning: rss2json returned an error: {data.get('message', 'Unknown')}")
        sys.exit(1)
        
    entries = data.get('items', [])
    if len(entries) == 0:
        print("Warning: Feed contains no entries.")
        sys.exit(1)
        
    posted_urls = load_posted_urls()
    new_entries = []
    
    # Process from oldest to newest if you prefer, but usually iterating entries is fine
    # entries is usually newest first. We reverse to push oldest first
    for entry in reversed(entries):
        link = entry.get('link')
        if link and link not in posted_urls:
            new_entries.append(link)

    if not new_entries:
        print("No new articles to push to Medium.")
        return

    print(f"Found {len(new_entries)} new article(s) to push.")
    
    # Push articles
    success_count = 0
    for url in new_entries:
        print(f"Processing: {url}")
        if push_to_medium(url):
            append_posted_url(url)
            success_count += 1
        else:
            print(f"Stopping execution due to failure on {url}.")
            # Stop execution to prevent further failures and throw Exit Code 1
            sys.exit(1)
            
    print(f"Successfully pushed {success_count} articles.")

if __name__ == "__main__":
    main()
