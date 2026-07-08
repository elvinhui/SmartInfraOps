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
                // Exact target based on Medium DOM
                var exact = document.querySelector('.js-importUrl, [data-default-value*="yoursite"]');
                if (exact) {
                    return exact;
                }
                
                var inputs = document.querySelectorAll('div[contenteditable="true"], input');
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
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'}); arguments[0].focus(); arguments[0].click();", input_elem)
                    time.sleep(1)
                    
                    try:
                        # .clear() throws InvalidElementStateException on contenteditable divs
                        if input_elem.tag_name.lower() == 'input':
                            input_elem.clear()
                        else:
                            actions = ActionChains(driver)
                            actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform()
                            time.sleep(0.5)
                        
                        human_typing(input_elem, canonical_url)
                    except Exception as selenium_err:
                        print(f"Selenium send_keys failed ({selenium_err}), falling back to JS injection...")
                        driver.execute_script("""
                            if (arguments[0].tagName.toLowerCase() === 'div') {
                                arguments[0].innerHTML = '<p>' + arguments[1] + '</p>';
                            } else {
                                arguments[0].value = arguments[1];
                            }
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
            if "/edit" in driver.current_url or ("/p/" in driver.current_url and "import" not in driver.current_url):
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

            import re
            polished_markdown = polished_markdown.strip()
            # Clean up excessive newlines before pasting to prevent huge vertical gaps
            polished_markdown = re.sub(r'\n{3,}', '\n\n', polished_markdown)
            
            # Put polished markdown into clipboard (WITHOUT title, since we type title manually)
            _set_clipboard(polished_markdown)
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
                print("Clearing editor and typing title via xdotool...")
                for _ in range(3):
                    subprocess.run(["xdotool", "key", "ctrl+a"])
                    time.sleep(0.3)
                subprocess.run(["xdotool", "key", "Delete"])
                time.sleep(1)
                
                # Type title
                subprocess.run(["xdotool", "type", "--delay", "50", title])
                time.sleep(1)
                subprocess.run(["xdotool", "key", "Return"])
                time.sleep(1)
                
                print("Pasting body via xdotool...")
                subprocess.run(["xdotool", "key", "ctrl+v"])
            else:
                print("Clearing editor and typing title via ActionChains...")
                actions = ActionChains(driver)
                for _ in range(3):
                    actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                    time.sleep(0.3)
                actions.send_keys(Keys.DELETE).perform()
                time.sleep(1)
                
                actions = ActionChains(driver)
                for char in title:
                    actions.send_keys(char)
                    actions.pause(random.uniform(0.02, 0.08))
                actions.send_keys(Keys.RETURN)
                actions.perform()
                time.sleep(1)
                
                print("Pasting body via ActionChains...")
                actions = ActionChains(driver)
                actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()

            time.sleep(5)
            print("Polished content pasted.")
            driver.save_screenshot("module_distributor/debug_after_paste.png")



        # ── Step 7: Wait for Autosave & Publish ───────────────────────────────
        print("Waiting for Medium autosave to complete...")
        # If Medium is stuck on "Saving..." or shows the red error banner, we can't publish.
        # We will wait up to 60 seconds. If stuck, we trigger a minor edit to force a retry.
        for save_attempt in range(30):
            save_status = driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                    if (txt === 'saving...') return 'saving';
                    if (txt === 'publish' || txt === 'publish and send') return 'ready';
                }
                return 'unknown';
            """)
            if save_status == 'ready':
                print("Autosave complete. Publish button is ready.")
                break
            
            if save_attempt > 0 and save_attempt % 10 == 0:
                print("Still saving... triggering a minor edit to force retry.")
                try:
                    # Type space and backspace at the end of the document
                    actions = ActionChains(driver)
                    actions.key_down(Keys.CONTROL).send_keys(Keys.END).key_up(Keys.CONTROL).perform()
                    time.sleep(0.5)
                    actions.send_keys(' ').send_keys(Keys.BACKSPACE).perform()
                except:
                    pass
            time.sleep(2)

        print("Waiting for Publish button and modal...")
        publish_clicked = False
        for attempt in range(20):
            # Click the publish button
            driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                    if (txt.includes('publish') && !txt.includes('publish now') && !btns[i].disabled && !btns[i].hasAttribute('aria-disabled') && btns[i].offsetParent !== null) {
                        btns[i].scrollIntoView({behavior: 'instant', block: 'center'});
                        btns[i].click();
                        return;
                    }
                }
            """)
            time.sleep(2)
            
            # Check if modal is open by looking for the topics input or "Publish now" button
            modal_open = driver.execute_script("""
                var el = document.querySelector('input[placeholder="Add a topic..."], input[aria-controls="tagMultiSelectMenu"]');
                var btns = document.querySelectorAll('button');
                var publishNow = Array.from(btns).some(b => (b.innerText || '').toLowerCase().trim().includes('publish now'));
                var overlays = document.querySelectorAll('[role="dialog"], [class*="overlay"]');
                return el !== null || publishNow || overlays.length > 0;
            """)
            
            if modal_open:
                publish_clicked = True
                print("Publish modal successfully opened.")
                break
                
            print(f"Publish modal not open after attempt {attempt + 1}, retrying click...")

        if not publish_clicked:
            driver.save_screenshot("module_distributor/error_medium_no_publish.png")
            raise Exception("Publish button not found or modal failed to open after waiting.")

        time.sleep(5)

        # Add Topics (up to 5 allowed on Medium)
        if topics is None:
            topics = ["Technology", "DevOps", "Infrastructure", "Python", "Cloud"]
        else:
            # Fallback if the topics list is empty, otherwise take the first 5 topics
            topics = topics[:5] if topics else ["Technology", "DevOps", "Infrastructure", "Python", "Cloud"]
            
        print(f"Adding topics: {topics}...")
        try:
            # The topic combobox only appears after Medium's publish modal fully renders.
            # The modal container can be taller than the viewport (especially in headless
            # 1280x800), so the topic section at the bottom may not be in the DOM or
            # visible until we scroll the modal container down.
            topic_input = None
            for attempt in range(20):
                # Scroll the publish modal container down to reveal the topic section.
                # Medium wraps the publish form in a scrollable overlay/dialog.
                driver.execute_script("""
                    // Try to scroll the modal/overlay that contains the publish form.
                    // Medium uses a few different container patterns:
                    
                    // 1. Look for the Topics heading text and scroll it into view
                    var allText = document.querySelectorAll('p, h3, h4, label, span, div');
                    for (var i = 0; i < allText.length; i++) {
                        var txt = (allText[i].textContent || '').trim();
                        if (txt === 'Topics' || txt === 'Add up to five topics to help readers find your story.') {
                            allText[i].scrollIntoView({behavior: 'instant', block: 'center'});
                            return;
                        }
                    }
                    
                    // 2. Scroll any scrollable overlay/dialog container
                    var overlays = document.querySelectorAll('[role="dialog"], [class*="overlay"], [class*="modal"]');
                    for (var i = 0; i < overlays.length; i++) {
                        if (overlays[i].scrollHeight > overlays[i].clientHeight) {
                            overlays[i].scrollTop = overlays[i].scrollHeight;
                            return;
                        }
                    }
                    
                    // 3. Fallback: scroll any large scrollable div
                    var divs = document.querySelectorAll('div');
                    for (var i = 0; i < divs.length; i++) {
                        var d = divs[i];
                        if (d.scrollHeight > d.clientHeight + 100 && d.scrollHeight > 500) {
                            d.scrollTop = d.scrollHeight;
                            return;
                        }
                    }
                    
                    // 4. Last resort: scroll the page itself
                    window.scrollTo(0, document.body.scrollHeight);
                """)
                time.sleep(1)

                topic_input = driver.execute_script("""
                    // Primary: exact match from DOM inspection
                    var el = document.querySelector('input[role="combobox"][aria-controls="tagMultiSelectMenu"]');
                    if (el) return el;
                    
                    // Secondary: placeholder match
                    el = document.querySelector('input[placeholder="Add a topic..."]');
                    if (el) return el;
                    
                    // Tertiary: aria-describedby match (from observed DOM)
                    el = document.querySelector('input[aria-describedby="tagMultiSelectMenu"]');
                    if (el) return el;
                    
                    // Quaternary: broad scan for any topic/tag input
                    var inputs = document.querySelectorAll('input');
                    for (var i = 0; i < inputs.length; i++) {
                        var ph = (inputs[i].placeholder || '').toLowerCase();
                        if (ph.includes('topic') || ph.includes('tag')) {
                            return inputs[i];
                        }
                    }
                    return null;
                """)
                if topic_input:
                    print(f"Found topic input on attempt {attempt + 1}.")
                    break
                if attempt % 5 == 4:
                    print(f"Topic input not found after {attempt + 1} attempts, still trying...")
                time.sleep(1)
            
            if topic_input:
                driver.save_screenshot("module_distributor/debug_topic_input_found.png")
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", topic_input)
                time.sleep(1.0)
                
                # Use ActionChains to click and type, which is more reliable for React inputs
                actions = ActionChains(driver)
                actions.move_to_element(topic_input).click()
                actions.pause(0.5)
                for topic in topics:
                    for char in topic:
                        actions.send_keys(char)
                        actions.pause(random.uniform(0.05, 0.15))
                    actions.pause(random.uniform(2.0, 3.0))  # Wait for autocomplete suggestions
                    actions.send_keys(Keys.RETURN)
                    actions.pause(random.uniform(0.8, 1.5))
                actions.perform()
                print("Topics added successfully.")
            else:
                driver.save_screenshot("module_distributor/error_topic_not_found.png")
                print("Topic input field not found after 20 attempts.")
                # Debug: dump all inputs found in the page
                debug_inputs = driver.execute_script("""
                    var inputs = document.querySelectorAll('input');
                    var info = [];
                    for (var i = 0; i < inputs.length; i++) {
                        info.push({
                            placeholder: inputs[i].placeholder || '',
                            role: inputs[i].getAttribute('role') || '',
                            type: inputs[i].type || '',
                            visible: inputs[i].offsetParent !== null,
                            rect: inputs[i].getBoundingClientRect().toJSON()
                        });
                    }
                    return JSON.stringify(info, null, 2);
                """)
                print(f"Debug - all inputs on page: {debug_inputs}")
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
