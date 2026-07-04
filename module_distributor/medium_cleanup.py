import os
import sys
import time
import json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DRY_RUN = False  # Set to False to actually delete stories

def load_cookies():
    auth_file = os.path.join(os.path.dirname(__file__), "medium_auth.json")
    if not os.path.exists(auth_file):
        print(f"Error: {auth_file} not found. Cannot authenticate with Medium.")
        return []
    try:
        with open(auth_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("cookies", [])
    except Exception as e:
        print(f"Error reading {auth_file}: {e}")
        return []

def build_driver():
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,800")
    # Using headless=False to evade bot detection
    driver = uc.Chrome(options=options, version_main=149, headless=False)
    return driver

def get_duplicates_on_page(driver):
    """
    Scrolls down and returns a dictionary of duplicate story titles on the current page.
    Returns: { "lowercase title": count } (only where count > 1)
    """
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        
    titles = driver.execute_script("""
        var found = [];
        var headings = document.querySelectorAll('h2, h3, a');
        for(var i=0; i<headings.length; i++){
            var t = headings[i].innerText || headings[i].textContent;
            if (t) {
                // Ensure it looks like a story title (not 'Write', 'Sign out', etc.)
                // Usually story titles are long enough and wrapped in h2/h3.
                if (headings[i].tagName.toLowerCase() === 'h2' || headings[i].tagName.toLowerCase() === 'h3') {
                    found.push(t.trim().toLowerCase());
                }
            }
        }
        return found;
    """)
    
    counts = {}
    for t in titles:
        # Ignore very short navigation words just in case
        if len(t) < 5:
            continue
        counts[t] = counts.get(t, 0) + 1
        
    return {t: c for t, c in counts.items() if c > 1}

def delete_one_instance(driver, title):
    """
    Finds one story matching the title, clicks its More options, clicks Delete story, and confirms.
    Returns True if successfully deleted, False otherwise.
    """
    # 1. Open dropdown
    opened = driver.execute_script("""
        var titleToMatch = arguments[0];
        var headings = document.querySelectorAll('h2, h3');
        for (var i = 0; i < headings.length; i++) {
            var t = (headings[i].innerText || headings[i].textContent || '').trim().toLowerCase();
            if (t === titleToMatch) {
                // Traverse up to find a container (usually an 'article' or a row div)
                var container = headings[i];
                for(var j=0; j<6; j++) { // go up to 6 levels
                    if(container.parentElement) container = container.parentElement;
                }
                
                // Find the dropdown button inside this container
                var btns = container.querySelectorAll('button');
                for (var b = 0; b < btns.length; b++) {
                    var aria = btns[b].getAttribute('aria-label') || '';
                    if (aria.toLowerCase().includes('more') || btns[b].innerHTML.includes('circle')) {
                        btns[b].scrollIntoView({behavior: 'smooth', block: 'center'});
                        btns[b].click();
                        return true;
                    }
                }
            }
        }
        return false;
    """, title)
    
    if not opened:
        print(f"    [-] Could not find 'More options' button for: {title}")
        return False
        
    time.sleep(1.5)
    
    # 2. Click "Delete story"
    clicked_delete = driver.execute_script("""
        var btns = document.querySelectorAll('button, a, div[role="menuitem"], div[role="button"]');
        for (var i = 0; i < btns.length; i++) {
            var txt = (btns[i].innerText || btns[i].textContent || '').trim().toLowerCase();
            if (txt === 'delete story') {
                btns[i].click();
                return true;
            }
        }
        return false;
    """)
    
    if not clicked_delete:
        print(f"    [-] Could not find 'Delete story' menu item for: {title}")
        # Click elsewhere to close menu
        driver.execute_script("document.body.click();")
        return False
        
    time.sleep(1.5)
    
    # 3. Confirm Delete
    confirmed = driver.execute_script("""
        var btns = document.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
            var txt = (btns[i].innerText || btns[i].textContent || '').trim().toLowerCase();
            // In the confirmation modal, find the red 'Delete' button.
            if (txt === 'delete' && !btns[i].disabled) {
                btns[i].click();
                return true;
            }
        }
        return false;
    """)
    
    if not confirmed:
        print(f"    [-] Could not find confirmation 'Delete' button for: {title}")
        # Try to cancel
        driver.execute_script("""
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                if ((btns[i].innerText || '').toLowerCase() === 'cancel') {
                    btns[i].click();
                }
            }
        """)
        return False
        
    print(f"    [+] Successfully deleted one instance of: {title}")
    time.sleep(3) # Wait for network request to finish and page to update
    return True

def cleanup_medium():
    cookies = load_cookies()
    if not cookies:
        print("No cookies found. Exiting.")
        return
        
    driver = build_driver()
    try:
        # Set cookies
        driver.get("https://medium.com/404")
        time.sleep(2)
        for c in cookies:
            cookie_dict = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".medium.com"),
                "path": c.get("path", "/")
            }
            if "secure" in c: cookie_dict["secure"] = c["secure"]
            if "httpOnly" in c: cookie_dict["httpOnly"] = c["httpOnly"]
            try: driver.add_cookie(cookie_dict)
            except Exception: pass
            
        try: driver.execute_script("window.localStorage.setItem('viewer-status|is-logged-in', 'true');")
        except: pass
        
        pages = ["drafts", "public"]
        for page in pages:
            print(f"\n==============================================")
            print(f"Scanning Medium {page.upper()} for duplicates...")
            print(f"==============================================")
            
            while True:
                driver.get(f"https://medium.com/me/stories/{page}")
                time.sleep(4)
                
                duplicates = get_duplicates_on_page(driver)
                if not duplicates:
                    print(f"No duplicates found on {page} page.")
                    break
                    
                total_to_delete = sum([count - 1 for count in duplicates.values()])
                print(f"Found {len(duplicates)} titles with duplicates ({total_to_delete} extra stories to remove).")
                
                deleted_any = False
                for title, count in duplicates.items():
                    extras = count - 1
                    print(f"\nTitle: '{title}' (Appears {count} times, removing {extras})")
                    
                    if DRY_RUN:
                        print(f"    [DRY RUN] Would delete {extras} instances of this story.")
                        continue
                        
                    # Delete exactly 'extras' instances
                    for i in range(extras):
                        print(f"    Attempting to delete instance {i+1} of {extras}...")
                        success = delete_one_instance(driver, title)
                        if success:
                            deleted_any = True
                        else:
                            print("    Stopping deletion for this title due to UI failure.")
                            break
                
                if DRY_RUN or not deleted_any:
                    # Break out of loop if we are not actually making changes,
                    # otherwise it will loop infinitely finding the same duplicates.
                    break
                    
    finally:
        driver.quit()
        print("\nCleanup session finished.")

if __name__ == "__main__":
    if DRY_RUN:
        print("!!! RUNNING IN DRY-RUN MODE. NO POSTS WILL BE DELETED. !!!")
        print("To actually delete posts, change DRY_RUN = False in the script.")
    cleanup_medium()
