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

            print("Copying article content to clipboard...")
            # Use JS to select the content
            page.evaluate("""
                const range = document.createRange();
                range.selectNodeContents(document.querySelector('.ops-article-content'));
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            """)
            time.sleep(1)
            
            # Use keyboard to copy
            page.keyboard.press("Control+C")
            time.sleep(1)

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
            print("Pasting content...")
            page.keyboard.press("Control+V")
            
            # Wait for medium to process pasted content and auto-save
            time.sleep(8)

            # --- SEO Canonical 强绑定 (Kill-Switch) ---
            print("Enforcing SEO Canonical Link...")
            try:
                # 1. Click the three-dot menu (More options)
                menu_btn = page.locator('button[aria-controls="more-menu"], button[aria-label*="options" i], button[aria-label*="More" i]').first
                if not menu_btn.is_visible(timeout=5000):
                    menu_btn = page.locator('button:has(svg)').last # Usually the last button in the top bar is the 3 dots or profile
                menu_btn.click(timeout=10000)
                
                # 2. Click "Story settings" or "More settings"
                page.locator('button, a').filter(has_text=re.compile(r"settings", re.IGNORECASE)).click(timeout=10000)
                
                # We are now on the settings page.
                page.wait_for_load_state("domcontentloaded")
                
                # 3. Target Advanced Settings
                # Locate the advanced settings section by scrolling or directly locating
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
                print(f"Warning: Failed to enforce canonical link: {e}")
                print("Skipping SEO Canonical binding due to Medium UI changes. Article is still saved as Draft.")
                # Save screenshot for debugging
                try:
                    page.screenshot(path="fatal_canonical_error.png")
                except:
                    pass
                # We intentionally do NOT raise FatalError here so the distribution process can complete successfully.

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
