import os
import sys
import time
import json
import subprocess
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
    
    # Use headless if no display is available (e.g. CI / SSH)
    import os
    if not os.environ.get("DISPLAY"):
        options.add_argument("--headless=new")
    
    # Set page load strategy to eager so it doesn't wait for all assets (like trackers)
    options.page_load_strategy = 'eager'
    
    # Let undetected_chromedriver auto-detect Chrome version
    driver = uc.Chrome(options=options)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(30)
    return driver

def get_duplicates_on_page(driver):
    """
    Scrolls down and returns a dictionary of duplicate story titles on the current page.
    Returns: { "lowercase title": count } (only where count > 1)
    """
    try:
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        while scroll_attempts < 30:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_attempts += 1
            print(f"Scrolled {scroll_attempts} times, new height: {new_height}", flush=True)
    except Exception as e:
        print(f"Warning: Scrolling interrupted (maybe script timeout): {e}", flush=True)
        
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

_debug_dumped = False

def delete_one_instance(driver, title):
    """
    Finds one story matching the title, clicks its More options, clicks Delete story, and confirms.
    Returns True if successfully deleted, False otherwise.
    """
    from selenium.webdriver.common.action_chains import ActionChains
    
    # Step 1: Find the story heading, scroll to it, and hover to reveal the 3-dots button
    heading_index = driver.execute_script("""
        var titleToMatch = arguments[0];
        var headings = Array.from(document.querySelectorAll('h2, h3'));
        for (var i = 0; i < headings.length; i++) {
            var t = (headings[i].innerText || headings[i].textContent || '').trim().toLowerCase();
            if (t === titleToMatch) {
                headings[i].scrollIntoView({behavior: 'smooth', block: 'center'});
                return i;
            }
        }
        return -1;
    """, title)
    
    if heading_index == -1:
        print(f"    [-] Could not find heading for: {title}", flush=True)
        return False
    
    # Hover over the heading to trigger the story row's :hover state and reveal the 3-dots
    time.sleep(0.5)
    try:
        headings = driver.find_elements(By.CSS_SELECTOR, "h2, h3")
        target_heading = headings[heading_index]
        ActionChains(driver).move_to_element(target_heading).pause(1.0).perform()
        print(f"    [*] Hovering over heading (index {heading_index})", flush=True)
    except Exception as e:
        print(f"    [WARN] Could not hover heading: {e}", flush=True)
    
    # Step 2: Find the 3-dots button, force it visible, and dispatch proper click events
    opened = driver.execute_script("""
        var titleToMatch = arguments[0];
        var allButtons = Array.from(document.querySelectorAll('button'));
        
        for (var b = 0; b < allButtons.length; b++) {
            var btn = allButtons[b];
            var btnText = (btn.innerText || btn.textContent || '').trim();
            if (btnText !== 'Toggle actions menu') continue;
            
            // Walk up to find if this button belongs to the target story
            var ancestor = btn.parentElement;
            for (var level = 0; level < 20 && ancestor && ancestor.tagName !== 'BODY'; level++) {
                var headingsHere = ancestor.querySelectorAll('h2, h3');
                for (var h = 0; h < headingsHere.length; h++) {
                    var ht = (headingsHere[h].innerText || headingsHere[h].textContent || '').trim().toLowerCase();
                    if (ht === titleToMatch) {
                        // Force the button and its ancestors visible (needed in headless mode)
                        btn.style.setProperty('opacity', '1', 'important');
                        btn.style.setProperty('visibility', 'visible', 'important');
                        btn.style.setProperty('display', 'inline-flex', 'important');
                        btn.style.setProperty('pointer-events', 'auto', 'important');
                        btn.style.setProperty('width', '36px', 'important');
                        btn.style.setProperty('height', '36px', 'important');
                        btn.style.setProperty('overflow', 'visible', 'important');
                        btn.style.setProperty('position', 'relative', 'important');
                        var p = btn.parentElement;
                        for (var pl = 0; pl < 5 && p; pl++) {
                            p.style.setProperty('opacity', '1', 'important');
                            p.style.setProperty('visibility', 'visible', 'important');
                            p.style.setProperty('overflow', 'visible', 'important');
                            p = p.parentElement;
                        }
                        
                        btn.scrollIntoView({block: 'center'});
                        
                        // Dispatch proper mouse event sequence to trigger React handlers
                        var rect = btn.getBoundingClientRect();
                        var cx = rect.left + rect.width / 2;
                        var cy = rect.top + rect.height / 2;
                        var opts = {bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy};
                        btn.dispatchEvent(new MouseEvent('mouseover', opts));
                        btn.dispatchEvent(new MouseEvent('mouseenter', {bubbles: false, view: window}));
                        btn.dispatchEvent(new MouseEvent('pointerdown', opts));
                        btn.dispatchEvent(new MouseEvent('mousedown', opts));
                        btn.dispatchEvent(new MouseEvent('pointerup', opts));
                        btn.dispatchEvent(new MouseEvent('mouseup', opts));
                        btn.dispatchEvent(new MouseEvent('click', opts));
                        return true;
                    }
                }
                ancestor = ancestor.parentElement;
            }
        }
        return false;
    """, title)
    
    if not opened:
        print(f"    [-] Could not find 'More options' button for: {title}", flush=True)
        return False
    
    print(f"    [*] Clicked 3-dots button via JS MouseEvent dispatch", flush=True)
    
    # Step 2: Wait for popup menu and click "Delete story" / "Delete draft"
    time.sleep(2)
    
    # Debug: dump what menu items are visible after clicking
    try:
        menu_items = driver.execute_script("""
            var items = [];
            var all = document.querySelectorAll('button, a, li, div[role="menuitem"], [role="option"]');
            for (var i = 0; i < all.length; i++) {
                var txt = (all[i].innerText || all[i].textContent || '').trim().toLowerCase();
                if (txt.includes('delete') || txt.includes('edit') || txt.includes('pin') || 
                    txt.includes('share') || txt.includes('hide') || txt.includes('copy')) {
                    items.push(txt.substring(0, 40));
                }
            }
            return items;
        """)
        print(f"    [DEBUG] Menu items found: {menu_items}", flush=True)
    except Exception as e:
        print(f"    [WARN] Could not dump menu items: {e}", flush=True)
    
    # Try to click Delete story / Delete draft using JS.
    # We must filter out hidden elements (width == 0) because Medium duplicates the menu in the DOM (mobile vs desktop).
    delete_keywords = ['delete story', 'delete draft']
    time.sleep(1)
    
    clicked_delete = driver.execute_script("""
        var keywords = arguments[0];
        var all = document.querySelectorAll('button, a, li, div[role="menuitem"], [role="option"]');
        for (var k = 0; k < keywords.length; k++) {
            for (var i = 0; i < all.length; i++) {
                var txt = (all[i].innerText || all[i].textContent || '').trim().toLowerCase();
                if (txt === keywords[k]) {
                    var rect = all[i].getBoundingClientRect();
                    // MUST be visible on screen
                    if (rect.width > 0 && rect.height > 0) {
                        all[i].scrollIntoView({block: 'center'});
                        
                        var cx = rect.left + rect.width / 2;
                        var cy = rect.top + rect.height / 2;
                        var opts = {bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy};
                        
                        // Fire full mouse sequence and standard click
                        all[i].dispatchEvent(new MouseEvent('pointerdown', opts));
                        all[i].dispatchEvent(new MouseEvent('mousedown', opts));
                        all[i].dispatchEvent(new MouseEvent('pointerup', opts));
                        all[i].dispatchEvent(new MouseEvent('mouseup', opts));
                        all[i].dispatchEvent(new MouseEvent('click', opts));
                        all[i].click(); // Fallback native click
                        return true;
                    }
                }
            }
        }
        return false;
    """, delete_keywords)
            
    if not clicked_delete:
        print(f"    [-] Could not find or click 'Delete story' menu item for: {title}", flush=True)
        driver.execute_script("document.body.click();")
        time.sleep(0.5)
        return False
        
    print(f"    [*] Clicked 'Delete story' via visible JS dispatch", flush=True)
        
    # Step 3: Wait for modal and confirm Delete
    time.sleep(2)
    confirmed = False
    
    # Find all buttons in the dialog and click the one that says 'delete'
    dialog_btns = driver.find_elements(By.CSS_SELECTOR, '[role="dialog"] button, .modal button')
    if not dialog_btns:
        dialog_btns = driver.find_elements(By.TAG_NAME, 'button')  # fallback
        
    for btn in dialog_btns:
        try:
            txt = (btn.text or btn.get_attribute('innerText') or '').strip().lower()
            if txt == 'delete' and btn.is_enabled():
                ActionChains(driver).move_to_element(btn).pause(0.5).click().perform()
                confirmed = True
                break
        except Exception:
            pass
            
    if not confirmed:
        print(f"    [-] Could not find confirmation 'Delete' button for: {title}", flush=True)
        driver.execute_script("document.body.click();")
        return False
        
    print(f"    [+] Successfully deleted one instance of: {title}", flush=True)
    time.sleep(3)
    return True

def kill_zombie_chrome():
    """Kill any leftover chrome/chromedriver processes."""
    for proc_name in ['chrome', 'chromedriver']:
        try:
            subprocess.run(['pkill', '-f', proc_name], capture_output=True, timeout=5)
        except Exception:
            pass
    time.sleep(2)

def safe_get_with_cookies(driver, url, cookies, max_attempts=3):
    """
    Safely navigates to a URL. If it times out, it rebuilds the driver,
    re-applies cookies, and retries up to max_attempts.
    Returns the (possibly new) driver.
    """
    for attempt in range(max_attempts):
        try:
            # Need to be on a medium domain to set cookies if driver was just rebuilt
            if attempt > 0:
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
                    except: pass
                try: driver.execute_script("window.localStorage.setItem('viewer-status|is-logged-in', 'true');")
                except: pass
            
            driver.get(url)
            return driver
        except Exception as e:
            print(f"    [WARN] Page load attempt {attempt+1} failed for {url}: {e}", flush=True)
            if attempt < max_attempts - 1:
                print("    [WARN] Rebuilding driver and retrying...", flush=True)
                try: driver.quit()
                except: pass
                kill_zombie_chrome()
                driver = build_driver()
            else:
                print("    [-] All attempts failed. Giving up on this URL.", flush=True)
                raise e
    return driver

def cleanup_medium():
    cookies = load_cookies()
    if not cookies:
        print("No cookies found. Exiting.")
        return
    
    # Kill zombie Chrome processes before starting
    kill_zombie_chrome()
        
    driver = build_driver()
    try:
        # Initial authentication setup via 404 page
        driver = safe_get_with_cookies(driver, "https://medium.com/404", cookies)
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
                target_url = f"https://medium.com/me/stories/{page}"
                driver = safe_get_with_cookies(driver, target_url, cookies)
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
