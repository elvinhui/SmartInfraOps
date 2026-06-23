import os
import sys
import time
import re
from playwright.sync_api import sync_playwright

class FatalError(Exception):
    pass

def push_to_medium(url, title, content_html=None):
    """
    Pushes an article to Medium using Playwright and enforces SEO Canonical link.
    Returns True on success, False on recoverable error.
    Raises FatalError if SEO Kill-Switch is triggered.
    """
    auth_file = os.getenv("MEDIUM_AUTH_JSON_FILE", "medium_auth.json")
    if not os.path.exists(auth_file):
        print(f"Error: {auth_file} not found. Cannot authenticate with Medium.")
        return False

    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=True)
        # Load auth state
        context = browser.new_context(storage_state=auth_file)
        page = context.new_page()

        try:
            print(f"Navigating to original article: {url}...")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Wait for content to load
            page.wait_for_selector(".ops-article-content", timeout=30000)
            time.sleep(2) # Let images fully render

            print("Extracting article HTML...")
            content_html = page.evaluate("document.querySelector('.ops-article-content').innerHTML")
            
            print("Navigating to Medium new story editor...")
            page.goto("https://medium.com/new-story", wait_until="domcontentloaded", timeout=60000)
            
            # Type title
            print(f"Typing title: {title}")
            title_locator = page.locator('h3.graf--title, [data-placeholder="Title"], h1').first
            title_locator.wait_for(state="visible", timeout=30000)
            title_locator.click()
            page.keyboard.type(title)
            time.sleep(1)
            
            # Move to body and paste
            page.keyboard.press("Enter")
            time.sleep(1)
            print("Pasting content via JS...")
            # Use backticks for JS string, escaping backticks and ${ inside the HTML
            safe_html = content_html.replace('`', '\\`').replace('${', '\\${')
            page.evaluate(f"document.execCommand('insertHTML', false, `{safe_html}`)")
            
            # TRIGGER REACT AUTOSAVE (simulate typing to force Medium to recognize content change)
            page.keyboard.type(" ")
            time.sleep(1)
            page.keyboard.press("Backspace")
            
            # Wait for medium to process pasted content and auto-save
            time.sleep(10)

            # --- SEO Canonical 强绑定 (Kill-Switch) ---
            print("Enforcing SEO Canonical Link...")
            try:
                # 1. Bruteforce click buttons to find the "Settings" menu
                found_settings = False
                buttons = page.locator('nav button, header button').all()
                if not buttons:
                    buttons = page.locator('button').all()
                
                for btn in reversed(buttons):
                    try:
                        if "publish" in btn.inner_text().lower(): 
                            continue
                        btn.click(timeout=2000)
                        time.sleep(1.5)
                        if page.locator('button, a').filter(has_text=re.compile(r"settings", re.IGNORECASE)).first.is_visible():
                            found_settings = True
                            break
                    except Exception as loop_e:
                        pass
                        
                if not found_settings:
                    raise Exception("Bruteforce failed to find the More Options menu.")
                
                # 2. Click "Story settings" or "More settings"
                page.locator('button, a').filter(has_text=re.compile(r"settings", re.IGNORECASE)).first.click(timeout=10000)
                
                # We are now on the settings page.
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
                
                # 3. Target Advanced Settings
                advanced_settings = page.locator('h2').filter(has_text="Advanced Settings")
                if advanced_settings.is_visible():
                    advanced_settings.scroll_into_view_if_needed()
                
                # 4. Check "This story was originally published elsewhere"
                checkbox_label = page.locator('label').filter(has_text="This story was originally published elsewhere")
                checkbox_label.click(timeout=10000)
                
                # 5. Input canonical URL
                canonical_input = page.locator('input[placeholder="https://"]')
                canonical_input.fill(url)
                
                # 6. Click "Save canonical link"
                save_btn = page.locator('button').filter(has_text="Save canonical link")
                save_btn.click(timeout=10000)
                
                print("Canonical link successfully bound.")
                
            except Exception as e:
                print(f"Fatal Error during Canonical binding: {e}")
                try:
                    page.screenshot(path="fatal_canonical_error.png")
                except:
                    pass
                raise FatalError("SEO Kill-Switch triggered: Failed to enforce canonical link.")

            print(f"Successfully pushed {url} to Medium (Saved as Draft).")
            return True

        except FatalError:
            raise
        except Exception as e:
            print(f"Recoverable error while pushing {url} to Medium: {e}")
            try:
                page.screenshot(path="error_medium_rpa.png")
            except:
                pass
            return False
        finally:
            browser.close()

if __name__ == "__main__":
    # Test script if run standalone
    try:
        push_to_medium("https://www.smartinfralog.com/posts/post-1781962018/", "Test Article")
    except FatalError as e:
        print(f"ABORT: {e}")
        sys.exit(1)
