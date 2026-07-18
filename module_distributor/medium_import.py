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


def _set_clipboard(text: str, is_html: bool = False):
    """
    Cross-platform clipboard write.
    On Linux uses xclip/xsel; falls back to a temp file approach.
    """
    try:
        # Try xclip (available after apt-get install xclip)
        cmd = ["xclip", "-selection", "clipboard"]
        if is_html:
            cmd.extend(["-t", "text/html"])
        proc = subprocess.run(
            cmd,
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
        time.sleep(5)
        
        # Verify the page has fully loaded (CSS/JS hydrated)
        for load_check in range(10):
            page_ready = driver.execute_script("""
                // Check if page has proper styling (not a degraded/unstyled page)
                var hasStylesheets = document.styleSheets.length >= 2;
                var hasImportBtn = !!Array.from(document.querySelectorAll('button')).find(
                    b => (b.innerText || '').toLowerCase().includes('import')
                );
                var hasInput = !!document.querySelector('input');
                return { ready: hasStylesheets && (hasImportBtn || hasInput), sheets: document.styleSheets.length, buttons: document.querySelectorAll('button').length };
            """)
            if page_ready.get('ready', False):
                print(f"Import page loaded (stylesheets: {page_ready.get('sheets')}, buttons: {page_ready.get('buttons')}).")
                break
            print(f"Import page not fully loaded yet (attempt {load_check + 1}/10, sheets={page_ready.get('sheets')}, buttons={page_ready.get('buttons')}). Waiting...")
            if load_check >= 4:
                # Try a full page refresh after 5 failed attempts
                print("Refreshing import page...")
                driver.refresh()
            time.sleep(3)

        # ── Step 3: Enter the canonical URL ───────────────────────────────
        print(f"Entering canonical URL: {canonical_url}")
        
        found_input = False
        for retry in range(15):
            input_elem = driver.execute_script("""
                // Exact target based on Medium DOM
                var exact = document.querySelector('.js-importUrl, [data-default-value*="yoursite"]');
                if (exact) return exact;
                
                // Prefer <input> elements first (more reliable for typing)
                var inputs = document.querySelectorAll('input[type="text"], input:not([type])');
                for (var i = 0; i < inputs.length; i++) {
                    var rect = inputs[i].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && rect.top > 100) return inputs[i];
                }
                // Fallback to contenteditable divs (only if no input found)
                var divs = document.querySelectorAll('div[contenteditable="true"]');
                for (var i = 0; i < divs.length; i++) {
                    var rect = divs[i].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && rect.top > 100) {
                        // Only accept div if the page appears fully loaded
                        if (document.styleSheets.length >= 2) return divs[i];
                    }
                }
                return null;
            """)
            if input_elem:
                tag = input_elem.tag_name.lower()
                print(f"Found URL input element: <{tag}>")
                try:
                    # Scroll into view
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});", input_elem)
                    time.sleep(0.5)
                    
                    url_entered = False
                    
                    # Method 1: ActionChains focus + ActionChains typing (most reliable for trusted input)
                    try:
                        ActionChains(driver).move_to_element(input_elem).click().perform()
                        time.sleep(0.3)
                        # Select all existing text and delete it
                        ActionChains(driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                        time.sleep(0.2)
                        ActionChains(driver).send_keys(Keys.DELETE).perform()
                        time.sleep(0.2)
                        # Type the URL character by character via ActionChains (sends to focused element)
                        for char in canonical_url:
                            ActionChains(driver).send_keys(char).perform()
                            time.sleep(random.uniform(0.03, 0.08))
                        url_entered = True
                        print("URL entered via ActionChains typing.")
                    except Exception as e1:
                        print(f"ActionChains typing failed: {e1}")
                    
                    # Method 2: element.send_keys (standard Selenium)
                    if not url_entered:
                        try:
                            if tag == 'input':
                                input_elem.clear()
                            human_typing(input_elem, canonical_url)
                            url_entered = True
                            print("URL entered via element.send_keys.")
                        except Exception as e2:
                            print(f"element.send_keys failed: {e2}")
                    
                    # Method 3: JS injection with React-aware value setter
                    if not url_entered:
                        print("Falling back to JS injection...")
                        driver.execute_script("""
                            var el = arguments[0], url = arguments[1];
                            if (el.tagName.toLowerCase() === 'div') {
                                el.textContent = url;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                            } else {
                                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                if (setter) setter.call(el, url);
                                else el.value = url;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                // Also fire React's synthetic event via a keyboard event
                                el.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
                                el.dispatchEvent(new KeyboardEvent('keyup', { key: 'a', bubbles: true }));
                            }
                        """, input_elem, canonical_url)
                        url_entered = True
                        print("URL entered via JS injection.")
                    
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
        # Wait for Import button to become truly enabled (React may need a moment)
        print("Clicking Import button...")
        import_clicked = False
        for import_attempt in range(10):
            import_btn = driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                    if (txt.includes('import')) {
                        btns[i].scrollIntoView({behavior: 'instant', block: 'center'});
                        return btns[i];
                    }
                }
                return null;
            """)
            
            if import_btn:
                # Check if the button is truly enabled
                is_disabled = driver.execute_script("""
                    var btn = arguments[0];
                    if (btn.disabled) return true;
                    if (btn.getAttribute('aria-disabled') === 'true') return true;
                    var style = window.getComputedStyle(btn);
                    if (style.pointerEvents === 'none') return true;
                    if (parseFloat(style.opacity) < 0.5) return true;
                    return false;
                """, import_btn)
                
                if is_disabled:
                    print(f"Import button found but disabled (attempt {import_attempt + 1}/10). Waiting...")
                    time.sleep(2)
                    continue
                
                try:
                    actions = ActionChains(driver)
                    actions.move_to_element(import_btn).click().perform()
                    import_clicked = True
                    print("Import button clicked via ActionChains.")
                    break
                except Exception as e:
                    print(f"ActionChains click on Import failed: {e}. Trying JS fallback...")
                    driver.execute_script("arguments[0].click();", import_btn)
                    import_clicked = True
                    break
            else:
                print(f"Import button not found (attempt {import_attempt + 1}/10). Waiting...")
                time.sleep(2)
        
        if not import_clicked:
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
            
            # Paste as PLAIN TEXT — Medium's editor crashes when pasting complex HTML
            # via clipboard (especially with code blocks). Plain text paste is much safer
            # and Medium natively handles markdown-like formatting.
            _set_clipboard(polished_markdown, is_html=False)
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

            time.sleep(10)
            print("Polished content pasted.")
            driver.save_screenshot("module_distributor/debug_after_paste.png")
            
            # ── Health check: verify editor didn't crash after paste ──────
            # Wait extra time for any delayed React crash to manifest
            time.sleep(5)
            page_info = driver.execute_script("""
                return {
                    url: window.location.href,
                    title: document.title,
                    bodyLen: document.body ? document.body.innerHTML.length : 0,
                    buttonCount: document.querySelectorAll('button').length,
                    hasEditor: !!document.querySelector('[contenteditable="true"]')
                };
            """)
            print(f"Post-paste health: {json.dumps(page_info)}")
            
            if page_info.get('buttonCount', 0) == 0 or not page_info.get('hasEditor', False):
                print("WARNING: Editor appears to have crashed after paste. Attempting page refresh recovery...")
                driver.refresh()
                time.sleep(10)
                page_info_2 = driver.execute_script("""
                    return {
                        buttonCount: document.querySelectorAll('button').length,
                        hasEditor: !!document.querySelector('[contenteditable="true"]')
                    };
                """)
                print(f"Post-refresh health: {json.dumps(page_info_2)}")
                if page_info_2.get('buttonCount', 0) == 0:
                    driver.save_screenshot("module_distributor/error_medium_editor_crash.png")
                    raise Exception("Medium editor crashed after paste and could not recover.")
                print("Editor recovered after page refresh.")


        # ── Step 7: Wait for Autosave & Publish ───────────────────────────────
        # Wait for autosave to complete (Medium might be saving the imported draft)
        print("Waiting for Medium to autosave...")
        for save_attempt in range(60):
            # Use both text matching AND CSS selector from real DOM inspection
            save_status = driver.execute_script("""
                var isSaving = false;
                var allText = document.body ? document.body.innerText.toLowerCase() : '';
                if (allText.includes('saving')) isSaving = true;
                
                var spans = document.querySelectorAll('span');
                for (var i = 0; i < spans.length; i++) {
                    var txt = (spans[i].innerText || '').toLowerCase().trim();
                    if (txt.includes('saving...') || txt === 'saving') isSaving = true;
                }
                if (isSaving) return 'saving';
                
                // Check by CSS selectors (from Medium's real DOM)
                var pubBtn = document.querySelector('button[data-action="show-prepublish"], button.button--publish, .js-publishDialogButtonText');
                if (pubBtn) return 'ready';
                
                // Fallback: check by text
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                    if ((txt === 'publish' || txt === 'publish and send') && !btns[i].disabled) {
                        return 'ready';
                    }
                }
                
                // Check if page has crashed (zero buttons)
                if (btns.length === 0) return 'crashed';
                
                return 'unknown';
            """)
            if save_status == 'ready':
                print("Autosave complete. Publish button is ready.")
                break
            elif save_status == 'crashed':
                print("WARNING: Page appears crashed during autosave wait. Refreshing...")
                driver.refresh()
                time.sleep(10)
            
            if save_attempt > 0 and save_attempt % 10 == 0:
                print("Still saving... triggering a minor edit to force retry.")
                try:
                    actions = ActionChains(driver)
                    actions.key_down(Keys.CONTROL).send_keys(Keys.END).key_up(Keys.CONTROL).perform()
                    time.sleep(0.5)
                    actions.send_keys(' ').send_keys(Keys.BACKSPACE).perform()
                except:
                    pass
            time.sleep(2)

        # Extra stabilization wait before clicking publish
        time.sleep(3)

        print("Waiting for Publish button and clicking...")
        publish_clicked = False
        editor_url = driver.current_url
        
        for attempt in range(10):
            page_state = driver.execute_script("""
                return {
                    buttonCount: document.querySelectorAll('button').length,
                    url: window.location.href
                };
            """)
            
            # If page crashed (0 buttons), refresh and retry
            if page_state.get('buttonCount', 0) == 0:
                print(f"Attempt {attempt + 1}: Page crashed (0 buttons). Refreshing...")
                driver.refresh()
                time.sleep(10)
                continue
            
            # Check if we already navigated away from editor (publish succeeded)
            current_url = page_state.get('url', '')
            if 'post_submit' in current_url or ('postPublishedType' in current_url):
                print(f"Attempt {attempt + 1}: Already on post-publish page. Publish succeeded!")
                publish_clicked = True
                break
            
            # Find the publish button
            publish_btn = driver.execute_script("""
                var btn = document.querySelector('button[data-action="show-prepublish"]');
                if (btn) { btn.scrollIntoView({behavior: 'instant', block: 'center'}); return btn; }
                btn = document.querySelector('button.button--publish');
                if (btn) { btn.scrollIntoView({behavior: 'instant', block: 'center'}); return btn; }
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].innerText || '').toLowerCase().trim();
                    if (txt === 'publish' || txt === 'publish and send') {
                        var rect = btns[i].getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            btns[i].scrollIntoView({behavior: 'instant', block: 'center'});
                            return btns[i];
                        }
                    }
                }
                return null;
            """)
            
            if publish_btn:
                print(f"Attempt {attempt + 1}: Publish button found. Clicking...")
                try:
                    ActionChains(driver).move_to_element(publish_btn).click().perform()
                except Exception as e:
                    print(f"ActionChains click failed: {e}. JS fallback...")
                    driver.execute_script("arguments[0].click();", publish_btn)
            else:
                print(f"Attempt {attempt + 1}: Publish button not found ({page_state.get('buttonCount', '?')} buttons).")
            
            # Wait for navigation or modal to appear
            time.sleep(5)
            
            # Check if URL changed (Medium's new flow: navigates to Story Preview page)
            new_url = driver.current_url
            if new_url != editor_url and '/edit' not in new_url:
                print(f"Page navigated to: {new_url}")
                publish_clicked = True
                break
            
            # Also check for old-style modal (in case Medium uses both flows)
            modal_open = driver.execute_script("""
                var dialog = document.querySelector('[role="dialog"], .overlay-content, .js-prepublishDialogContent');
                if (dialog && dialog.getBoundingClientRect().width > 0) return true;
                var el = document.querySelector('input[placeholder="Add a topic..."]');
                if (el && el.getBoundingClientRect().width > 0) return true;
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].innerText || '').toLowerCase().trim();
                    if (txt.includes('publish now') && btns[i].getBoundingClientRect().width > 0) return true;
                }
                return false;
            """)
            if modal_open:
                publish_clicked = True
                print("Old-style publish modal detected.")
                break
            
            print(f"Publish modal/navigation not detected after attempt {attempt + 1}, retrying...")

        if not publish_clicked:
            debug_info = driver.execute_script("""
                var btns = document.querySelectorAll('button');
                var texts = [];
                for(var i=0; i<btns.length && i<30; i++) {
                    texts.push((btns[i].innerText || '').trim().substring(0, 50));
                }
                return { url: window.location.href, totalButtons: btns.length, allButtonTexts: texts };
            """)
            print("DEBUG:", json.dumps(debug_info, indent=2))
            driver.save_screenshot("module_distributor/error_medium_no_publish.png")
            raise Exception("Publish button not found or navigation failed after waiting.")

        time.sleep(3)

        # ── Step 8: Handle Story Preview page (Medium's new publish flow) ─────
        # Medium now navigates to a "Story Preview" page after clicking Publish.
        # On this page we can add topics and click the final "Publish" button.
        current_url = driver.current_url
        is_story_preview = 'post_submit' in current_url or 'postPublishedType' in current_url
        
        if is_story_preview:
            print("On Story Preview page (Medium's new publish flow).")
        else:
            print("On publish modal (old flow).")

        # Add Topics (up to 5 allowed on Medium)
        if topics is None:
            topics = ["Technology", "DevOps", "Infrastructure", "Python", "Cloud"]
        else:
            topics = topics[:5] if topics else ["Technology", "DevOps", "Infrastructure", "Python", "Cloud"]
            
        print(f"Adding topics: {topics}...")
        try:
            topic_input = None
            for t_attempt in range(15):
                # Scroll to find topic input
                driver.execute_script("""
                    var allText = document.querySelectorAll('p, h3, h4, label, span, div');
                    for (var i = 0; i < allText.length; i++) {
                        var txt = (allText[i].textContent || '').trim();
                        if (txt === 'Topics' || txt.includes('Add up to five topics')) {
                            allText[i].scrollIntoView({behavior: 'instant', block: 'center'});
                            return;
                        }
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                """)
                time.sleep(1)

                topic_input = driver.execute_script("""
                    var el = document.querySelector('input[role="combobox"][aria-controls="tagMultiSelectMenu"]');
                    if (el) return el;
                    el = document.querySelector('input[placeholder="Add a topic..."]');
                    if (el) return el;
                    var inputs = document.querySelectorAll('input');
                    for (var i = 0; i < inputs.length; i++) {
                        var ph = (inputs[i].placeholder || '').toLowerCase();
                        if (ph.includes('topic') || ph.includes('tag')) return inputs[i];
                    }
                    return null;
                """)
                if topic_input:
                    print(f"Found topic input on attempt {t_attempt + 1}.")
                    break
                time.sleep(1)
            
            if topic_input:
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", topic_input)
                time.sleep(1.0)
                actions = ActionChains(driver)
                actions.move_to_element(topic_input).click()
                actions.pause(0.5)
                for topic in topics:
                    for char in topic:
                        actions.send_keys(char)
                        actions.pause(random.uniform(0.05, 0.15))
                    actions.pause(random.uniform(2.0, 3.0))
                    actions.send_keys(Keys.RETURN)
                    actions.pause(random.uniform(0.8, 1.5))
                actions.perform()
                print("Topics added successfully.")
            else:
                print("Topic input not found. Proceeding without topics.")
        except Exception as e:
            print(f"Warning: Failed to add topics: {e}")

        # ── Step 9: Click final Publish button ────────────────────────────────
        # On the Story Preview page, click the green "Publish" button to finalize.
        # On old modal, click "Publish now".
        print("Clicking final Publish button...")
        final_publish_btn = driver.execute_script("""
            var btns = document.querySelectorAll('button');
            // First look for "Publish now" (old flow)
            for (var i = 0; i < btns.length; i++) {
                var txt = (btns[i].innerText || '').toLowerCase().trim();
                if (txt.includes('publish now') && btns[i].getBoundingClientRect().width > 0) return btns[i];
            }
            // Then look for "Publish" (new Story Preview flow)
            for (var i = 0; i < btns.length; i++) {
                var txt = (btns[i].innerText || '').toLowerCase().trim();
                if (txt === 'publish' && btns[i].getBoundingClientRect().width > 0) return btns[i];
            }
            return null;
        """)
        
        if final_publish_btn:
            try:
                ActionChains(driver).move_to_element(final_publish_btn).click().perform()
                print("Final Publish button clicked.")
            except Exception as e:
                print(f"ActionChains failed on final publish: {e}. JS fallback...")
                driver.execute_script("arguments[0].click();", final_publish_btn)
        else:
            print("Warning: Final Publish button not found. Article may already be published.")

        # Wait for redirect/confirmation
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
