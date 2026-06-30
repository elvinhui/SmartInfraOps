import os
import time
import json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

class FatalError(Exception):
    pass

def push_to_medium(url, title, content_html=None):
    """
    Imports an article to Medium using the 'Import a story' feature.
    This automatically sets the canonical URL.
    Returns True on success, False on recoverable error.
    """
    auth_file = os.getenv("MEDIUM_AUTH_JSON_FILE", "medium_auth.json")
    if not os.path.exists(auth_file):
        print(f"Error: {auth_file} not found. Cannot authenticate with Medium.")
        return False

    print(f"Loading cookies from {auth_file}...")
    with open(auth_file, "r") as f:
        auth_data = json.load(f)
    
    cookies = auth_data.get("cookies", [])

    print("Starting undetected-chromedriver (Local)...")
    options = uc.ChromeOptions()
    # No proxy used since this is running on self-hosted runner
    driver = uc.Chrome(options=options, version_main=149, headless=False)
    wait = WebDriverWait(driver, 30)
    
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
            except Exception:
                pass # Ignore if invalid

        try:
            driver.execute_script("window.localStorage.setItem('viewer-status|is-logged-in', 'true');")
        except:
            pass

        # Go to Medium import page
        print("Navigating to Medium import page...")
        driver.get("https://medium.com/p/import")
        time.sleep(3)

        # Input URL
        print(f"Inputting URL: {url}")
        success = driver.execute_script(f"""
            var inputs = document.querySelectorAll('input[type="url"], input[type="text"], input:not([type])');
            for (var i=0; i<inputs.length; i++) {{
                var rect = inputs[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {{
                    inputs[i].value = '{url}';
                    var tracker = inputs[i]._valueTracker;
                    if (tracker) {{ tracker.setValue(''); }}
                    inputs[i].dispatchEvent(new Event('input', {{ bubbles: true }}));
                    inputs[i].dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}
            }}
            return false;
        """)
        
        if not success:
            raise Exception("Failed to find URL input field on Import page.")
            
        time.sleep(1)
        
        # Click Import button
        print("Clicking Import button...")
        success = driver.execute_script("""
            var btns = document.querySelectorAll('button');
            for (var i=0; i<btns.length; i++) {
                var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                if (txt.includes('import')) {
                    btns[i].click();
                    return true;
                }
            }
            return false;
        """)
        if not success:
            raise Exception("Failed to find Import button.")
            
        # Wait for import to complete and click "See your story"
        print("Waiting for import to complete...")
        see_story_clicked = False
        for _ in range(15):
            time.sleep(2)
            clicked = driver.execute_script("""
                var btns = document.querySelectorAll('button, a');
                for (var i=0; i<btns.length; i++) {
                    var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                    if (txt.includes('see your story') || txt.includes('edit your story')) {
                        btns[i].click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                see_story_clicked = True
                print("Clicked 'See your story' button.")
                time.sleep(5)
                break
                
        if not see_story_clicked:
            print("Could not find 'See your story' button, checking if already redirected.")
        
        # Click Publish button to open modal
        print("Waiting for Publish button to be enabled and clicking...")
        for _ in range(15):
            success = driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for(var i=0; i<btns.length; i++){
                    var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                    if(txt === 'publish' && !btns[i].disabled && !btns[i].hasAttribute('aria-disabled')) {
                        btns[i].click();
                        return true;
                    }
                }
                return false;
            """)
            if success:
                break
            time.sleep(2)
            
        print("Waiting for modal to render...")
        time.sleep(5)
        
        # Click final Publish button in the modal
        print("Clicking final Publish button...")
        driver.execute_script("""
            var btns = Array.from(document.querySelectorAll('button'));
            var publishNowBtn = btns.find(b => {
                var txt = (b.innerText || b.textContent || '').toLowerCase().trim();
                return txt.includes('publish now');
            });
            if (publishNowBtn) {
                publishNowBtn.click();
            } else {
                var publishBtns = btns.filter(b => {
                    var txt = (b.innerText || b.textContent || '').toLowerCase().trim();
                    return txt === 'publish';
                });
                if (publishBtns.length > 1) {
                    publishBtns[publishBtns.length - 1].click();
                } else if (publishBtns.length === 1) {
                    publishBtns[0].click();
                }
            }
        """)
        
        print("Waiting for story to be published...")
        for _ in range(20):
            if "new-story" not in driver.current_url and "edit" not in driver.current_url:
                break
            time.sleep(1)
            
        print(f"Successfully pushed {url} to Medium (Imported and Published).")
        return True
        
    except FatalError:
        raise
    except Exception as e:
        print(f"Recoverable error while pushing {url} to Medium via Import: {e}")
        try:
            driver.save_screenshot("error_medium_import_uc.png")
        except:
            pass
        return False
    finally:
        driver.quit()
