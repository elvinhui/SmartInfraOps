import os
import sys
import time
import json
import urllib.request
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

RSS_URL = os.getenv("RSS_URL", "https://smartinfralog.com/index.xml")
POSTED_URLS_FILE = os.path.join(os.path.dirname(__file__), "posted_urls.txt")
AUTH_JSON_FILE = os.getenv("MEDIUM_AUTH_JSON_FILE", "medium_auth.json")

def load_posted_urls():
    if not os.path.exists(POSTED_URLS_FILE):
        return set()
    with open(POSTED_URLS_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip() and not line.startswith("#"))

def append_posted_url(url):
    with open(POSTED_URLS_FILE, "a") as f:
        f.write(f"{url}\n")

def push_to_medium(url):
    if not os.path.exists(AUTH_JSON_FILE):
        print(f"Error: {AUTH_JSON_FILE} not found. Cannot authenticate with Medium.")
        sys.exit(1)

    print(f"Loading cookies from {AUTH_JSON_FILE}...")
    with open(AUTH_JSON_FILE, "r") as f:
        auth_data = json.load(f)
    
    cookies = auth_data.get("cookies", [])

    print("Starting undetected-chromedriver...")
    options = uc.ChromeOptions()
    # options.add_argument("--headless") # Run visibly to bypass CF
    driver = uc.Chrome(options=options, version_main=149)
    
    try:
        # Navigate to 404 page first to set cookies for medium.com
        print("Navigating to medium.com to set cookies...")
        driver.get("https://medium.com/404")
        
        for cookie in cookies:
            cookie_dict = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain", ".medium.com"),
                "path": cookie.get("path", "/")
            }
            if "secure" in cookie: cookie_dict["secure"] = cookie["secure"]
            if "httpOnly" in cookie: cookie_dict["httpOnly"] = cookie["httpOnly"]
            
            try:
                driver.add_cookie(cookie_dict)
            except Exception as e:
                pass # Ignore if invalid

        try:
            driver.execute_script("window.localStorage.setItem('viewer-status|is-logged-in', 'true');")
        except:
            pass

        print(f"Navigating to Medium import page...")
        driver.get("https://medium.com/p/import")
        
        wait = WebDriverWait(driver, 30)
        print("Waiting for URL input field...")
        url_input = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='url']")))
        
        print(f"Submitting URL: {url}")
        url_input.send_keys(url)
        url_input.send_keys(Keys.RETURN)
        
        print("Waiting for Import button...")
        import_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Import')]")))
        import_btn.click()
        
        try:
            wait.until(EC.visibility_of_element_located((By.XPATH, "//button[contains(text(), 'Publish')]")))
        except Exception:
            print("Could not find Publish button, but import may have succeeded.")

        print(f"Successfully imported {url} to Medium (Saved as Draft).")
        return True
    except Exception as e:
        print(f"Failed to push {url} to Medium: {e}")
        try:
            driver.save_screenshot("debug_medium_uc.png")
            print("Saved debug screenshot to debug_medium_uc.png")
        except:
            pass
        return False
    finally:
        driver.quit()

def main():
    print(f"Fetching RSS feed from {RSS_URL} via rss2json...")
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={RSS_URL}"
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    
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
    
    for entry in reversed(entries):
        link = entry.get('link')
        if link and link not in posted_urls:
            new_entries.append(link)

    if not new_entries:
        print("No new articles to push to Medium.")
        return

    print(f"Found {len(new_entries)} new article(s) to push.")
    
    success_count = 0
    for url in new_entries:
        print(f"Processing: {url}")
        if push_to_medium(url):
            append_posted_url(url)
            success_count += 1
        else:
            print(f"Stopping execution due to failure on {url}.")
            sys.exit(1)
            
    print(f"Successfully pushed {success_count} articles.")

if __name__ == "__main__":
    main()
