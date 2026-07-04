"""
medium_import.py
Pushes an article to Medium using the "Import a story" feature via
undetected_chromedriver. Canonical link is automatically preserved by
Medium's import mechanism (it reads the original URL you supply).

After import, the AI-polished Markdown content is pasted into the editor
via clipboard to replace the raw imported text.
"""
import os
import sys
import time
import json
import subprocess
import tempfile
import random

def human_typing(element, text):
    """Types character by character with random delays to simulate human typing."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.04, 0.15))

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


class FatalError(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_cookies() -> list:
    """
    Reads cookies from medium_auth.json (placed by workflow).
    Supports both a bare list and {"cookies": [...]} shape.
    """
    auth_file = os.path.join(os.path.dirname(__file__), "medium_auth.json")
    if not os.path.exists(auth_file):
        print(f"Warning: {auth_file} not found. No cookies loaded.")
        return []
    try:
        with open(auth_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("cookies", [])
    except Exception as e:
        print(f"Warning: Failed to parse medium_auth.json: {e}")
        return []


def _set_clipboard(text: str):
    """
    Cross-platform clipboard write.
    On Linux uses xclip/xsel; falls back to a temp file approach.
    """
    try:
        # Try xclip (available after apt-get install xclip)
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode("utf-8"),
            check=True,
        )
        return
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ["xsel", "--clipboard", "--input"],
            input=text.encode("utf-8"),
            check=True,
        )
        return
    except Exception:
        pass
    # Last resort: pyperclip if installed
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception as e:
        print(f"Warning: All clipboard methods failed: {e}")


def _build_driver() -> uc.Chrome:
    """Spin up an undetected Chromium instance (headless via Xvfb on Linux)."""
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,800")
    # Do NOT pass headless=True so Medium doesn't trigger bot protection.
    # Xvfb provides a virtual display on the Linux runner.
    # Specify version_main=149 to match the Chrome version on ubuntu-latest
    driver = uc.Chrome(options=options, version_main=149, headless=False)
    return driver


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

def push_to_medium(canonical_url: str, title: str, polished_markdown: str = "", topics: list = None) -> bool:
    """
    Imports an article into Medium via the Import feature, which automatically
    sets the canonical link back to `canonical_url`.

    If `polished_markdown` is supplied, the imported content is replaced with
    the AI-polished version via clipboard paste.

    Returns True on success, False on recoverable error.
    Raises FatalError for unrecoverable problems.
    """
    cookies = _load_cookies()
    driver = _build_driver()
    wait = WebDriverWait(driver, 30)

    try:
        # ── Step 1: Set session cookies ────────────────────────────────────
        print("Setting Medium session cookies...")
        driver.get("https://medium.com/404")
        time.sleep(2)

        for c in cookies:
            cookie_dict = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".medium.com"),
                "path": c.get("path", "/"),
            }
            if "secure" in c:
                cookie_dict["secure"] = c["secure"]
            if "httpOnly" in c:
                cookie_dict["httpOnly"] = c["httpOnly"]
            try:
                driver.add_cookie(cookie_dict)
            except Exception:
                pass
                
        try:
            driver.execute_script("window.localStorage.setItem('viewer-status|is-logged-in', 'true');")
        except Exception:
            pass

        # ── Step 1.5: Check for duplicates ─────────────────────────
        print("Checking for existing stories to prevent duplicates...")
        try:
            for page in ["public", "drafts"]:
                driver.get(f"https://medium.com/me/stories/{page}")
                time.sleep(3)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                
                existing_titles = driver.execute_script("""
                    var titles = [];
                    var headings = document.querySelectorAll('h2, h3, a');
                    for(var i=0; i<headings.length; i++){
                        if (headings[i].innerText) {
                            titles.push(headings[i].innerText.trim().toLowerCase());
                        }
                    }
                    return titles;
                """)
                if title.lower() in existing_titles:
                    print(f"Title '{title}' already exists in Medium {page}. Skipping publish.")
                    return True
        except Exception as e:
            print(f"Warning: Failed to check existing stories: {e}")

        # ── Step 2: Navigate to Medium Import page ─────────────────────────

        print("Navigating to Medium import page...")
        driver.get("https://medium.com/p/import")
        time.sleep(4)

        # ── Step 3: Enter the canonical URL ───────────────────────────────
        print(f"Entering canonical URL: {canonical_url}")
        
        found_input = False
        for _ in range(15):
            input_elem = driver.execute_script("""
                var inputs = document.querySelectorAll('.js-importUrl, [data-default-value*="yoursite"], div[contenteditable="true"], input');
                for (var i = 0; i < inputs.length; i++) {
                    var rect = inputs[i].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && rect.top > 100) {
                        return inputs[i];
                    }
                }
                return null;
            """)
            if input_elem:
                try:
                    driver.execute_script("arguments[0].focus(); arguments[0].click();", input_elem)
                    time.sleep(0.5)
                    try:
                        input_elem.clear()
                        human_typing(input_elem, canonical_url)
                    except Exception as selenium_err:
                        print(f"Selenium send_keys failed ({selenium_err}), falling back to JS injection...")
                        driver.execute_script("""
                            arguments[0].innerText = arguments[1];
                            arguments[0].value = arguments[1];
                            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                        """, input_elem, canonical_url)
                    
                    found_input = True
                    break
                except Exception as e:
                    print(f"Error interacting with input: {e}")
            time.sleep(2)

        if not found_input:
            driver.save_screenshot("module_distributor/error_medium_no_input.png")
            raise Exception("Failed to find URL input field on Medium import page.")

        time.sleep(2)

        # ── Step 4: Click the Import button ───────────────────────────────
        print("Clicking Import button...")
        clicked = driver.execute_script("""
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                if (txt.includes('import')) {
                    if (btns[i].disabled || btns[i].hasAttribute('aria-disabled') && btns[i].getAttribute('aria-disabled') === 'true') {
                        continue;
                    }
                    btns[i].click();
                    return true;
                }
            }
            return false;
        """)
        if not clicked:
            driver.save_screenshot("module_distributor/error_medium_no_import_btn.png")
            raise Exception("Failed to find or click enabled Import button. React state might not have updated.")

        # ── Step 5: Wait for "See your story" / redirect to editor ────────
        print("Waiting for import to complete...")
        see_story_clicked = False
        for _ in range(20):
            time.sleep(2)
            clicked = driver.execute_script("""
                var els = document.querySelectorAll('button, a');
                for (var i = 0; i < els.length; i++) {
                    var txt = (els[i].innerText || els[i].textContent || '').toLowerCase().trim();
                    if (txt.includes('see your story') || txt.includes('edit your story')) {
                        els[i].click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                see_story_clicked = True
                print("Clicked 'See your story'.")
                time.sleep(5)
                break
            # Medium might auto-redirect to the editor now
            if "/edit" in driver.current_url or "/p/" in driver.current_url and driver.current_url != "https://medium.com/p/import":
                print("Auto-redirected to editor.")
                see_story_clicked = True
                break

        if not see_story_clicked:
            driver.save_screenshot("module_distributor/error_medium_no_see_story.png")
            raise Exception(f"Did not transition to editor. Current URL: {driver.current_url}")

        # Wait for editor to fully load
        time.sleep(8)
        print(f"Current URL after import: {driver.current_url}")
        if "/edit" not in driver.current_url and "/p/" not in driver.current_url:
            raise Exception("URL does not look like the Medium editor.")

        # ── Step 6: Paste AI-polished content (if provided) ───────────────
        if polished_markdown:
            print("Replacing imported content with AI-polished version...")

            # Prepend the title to the polished markdown so we can paste it all at once
            full_text = f"{title}\n\n{polished_markdown}"

            # Put polished markdown into clipboard
            _set_clipboard(full_text)
            time.sleep(0.5)

            # Focus first contenteditable (Medium editor)
            focused = driver.execute_script("""
                var editors = document.querySelectorAll('[contenteditable="true"]');
                if (editors.length > 0) {
                    editors[0].focus();
                    return true;
                }
                return false;
            """)
            if not focused:
                driver.save_screenshot("module_distributor/error_medium_no_editor.png")
                raise Exception("Could not find Medium editor contenteditable.")
            
            time.sleep(1)
            
            # Use xdotool if available (much more reliable in Xvfb than Selenium ActionChains)
            import shutil
            if shutil.which("xdotool"):
                print("Clearing editor and pasting via xdotool...")
                for _ in range(3):
                    subprocess.run(["xdotool", "key", "ctrl+a"])
                    time.sleep(0.3)
                subprocess.run(["xdotool", "key", "Delete"])
                time.sleep(1)
                subprocess.run(["xdotool", "key", "ctrl+v"])
            else:
                print("Clearing editor and pasting via ActionChains...")
                actions = ActionChains(driver)
                for _ in range(3):
                    actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                    time.sleep(0.3)
                actions.send_keys(Keys.DELETE).perform()
                time.sleep(1)
                actions = ActionChains(driver)
                actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()

            time.sleep(5)
            print("Polished content pasted.")
            driver.save_screenshot("module_distributor/debug_after_paste.png")

        # ── Step 7: Publish ───────────────────────────────────────────────
        print("Waiting for Publish button...")
        publish_clicked = False
        for _ in range(20):
            clicked = driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                    if (txt === 'publish' && !btns[i].disabled && !btns[i].hasAttribute('aria-disabled')) {
                        btns[i].click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                publish_clicked = True
                break
            time.sleep(2)

        if not publish_clicked:
            driver.save_screenshot("module_distributor/error_medium_no_publish.png")
            raise Exception("Publish button not found or not enabled after waiting.")

        time.sleep(5)

        # Add Topics (up to 5 allowed on Medium)
        if topics is None:
            topics = ["Technology", "DevOps", "Infrastructure", "Python", "Cloud"]
        else:
            # Fallback if the topics list is empty, otherwise take the first 5 topics
            topics = topics[:5] if topics else ["Technology", "DevOps", "Infrastructure", "Python", "Cloud"]
            
        print(f"Adding topics: {topics}...")
        try:
            topic_input = driver.execute_script("""
                var input = document.querySelector('input[placeholder="Add a topic..."]') || 
                            document.querySelector('input[role="combobox"][aria-controls="tagMultiSelectMenu"]');
                if (input) return input;
                
                var inputs = document.querySelectorAll('input');
                for(var i=0; i<inputs.length; i++) {
                    if(inputs[i].placeholder && (inputs[i].placeholder.toLowerCase().includes('topic') || inputs[i].placeholder.toLowerCase().includes('tag'))) {
                        return inputs[i];
                    }
                }
                return null;
            """)
            
            if topic_input:
                time.sleep(1)
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'}); arguments[0].focus(); arguments[0].click();", topic_input)
                time.sleep(random.uniform(1.0, 1.5))
                
                for topic in topics:
                    human_typing(topic_input, topic)
                    time.sleep(random.uniform(2.0, 3.0)) # Wait for autocomplete suggestions
                    topic_input.send_keys(Keys.RETURN)
                    time.sleep(random.uniform(0.8, 1.5))
                print("Topics added successfully.")
            else:
                print("Topic input field not found.")
        except Exception as e:
            print(f"Warning: Failed to add topics: {e}")

        # Click "Publish now" in the confirmation modal
        print("Clicking final 'Publish now' button...")
        driver.execute_script("""
            var btns = Array.from(document.querySelectorAll('button'));
            var btn = btns.find(b => {
                var txt = (b.innerText || b.textContent || '').toLowerCase().trim();
                return txt.includes('publish now');
            });
            if (btn) {
                btn.click();
                return;
            }
            // Fallback: last button with text 'publish'
            var pubs = btns.filter(b => {
                var txt = (b.innerText || b.textContent || '').toLowerCase().trim();
                return txt === 'publish';
            });
            if (pubs.length > 0) {
                pubs[pubs.length - 1].click();
            }
        """)

        # Wait for redirect away from editor
        print("Waiting for publish to complete...")
        for _ in range(20):
            cur = driver.current_url
            if "new-story" not in cur and "/edit" not in cur and "p/import" not in cur:
                break
            time.sleep(1)

        print(f"Successfully published {canonical_url} to Medium.")
        return True

    except FatalError:
        raise
    except Exception as e:
        print(f"Recoverable error while pushing {canonical_url} to Medium: {e}")
        try:
            driver.save_screenshot("error_medium_uc.png")
        except Exception:
            pass
        return False
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        # No auth file cleanup needed; handled by CI environment
