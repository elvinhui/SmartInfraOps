import os
import sys
import time
from playwright.sync_api import sync_playwright

class FatalError(Exception):
    pass

def post_tweet(text):
    """
    Posts a tweet using Playwright and a saved authentication state (twitter_auth.json).
    Returns True on success, False on recoverable error.
    """
    auth_file = os.getenv("TWITTER_AUTH_JSON_FILE", "twitter_auth.json")
    # check both current directory and the directory of this script
    script_dir = os.path.dirname(__file__)
    auth_file_path = auth_file if os.path.exists(auth_file) else os.path.join(script_dir, auth_file)

    if not os.path.exists(auth_file_path):
        print(f"Error: {auth_file_path} not found. Cannot authenticate with X (Twitter).")
        print("Please run: playwright codegen --save-storage=twitter_auth.json https://x.com")
        return False

    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=True)
        # Load auth state
        context = browser.new_context(storage_state=auth_file_path)
        
        # Grant clipboard permissions just in case
        context.grant_permissions(['clipboard-read', 'clipboard-write'])
        
        page = context.new_page()

        try:
            print("Navigating to X (Twitter) compose page...")
            page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded", timeout=60000)
            
            # Wait for the tweet textarea
            print("Waiting for tweet input area...")
            textarea_locator = page.locator('[data-testid="tweetTextarea_0"]').first
            textarea_locator.wait_for(state="visible", timeout=30000)
            textarea_locator.click()
            time.sleep(1)
            
            print("Typing tweet text (simulating real keystrokes)...")
            # Draft.js often ignores insert_text, so we type it out
            page.keyboard.type(text, delay=20)
            time.sleep(2)
            page.screenshot(path="debug_twitter_before_click.png")
            
            # Click the tweet button
            print("Clicking tweet button...")
            tweet_button = page.locator('[data-testid="tweetButton"]').last
            tweet_button.wait_for(state="visible", timeout=10000)
            tweet_button.click()
            
            # Wait for tweet to be sent
            time.sleep(5)
            page.screenshot(path="debug_twitter_after_click.png")
            
            print("Successfully pushed to X (Twitter).")
            return True

        except Exception as e:
            print(f"Error while pushing to X (Twitter): {e}")
            try:
                page.screenshot(path="error_twitter_rpa.png")
            except:
                pass
            return False
        finally:
            browser.close()

if __name__ == "__main__":
    test_text = f"Test tweet from Playwright RPA! Timestamp: {int(time.time())}"
    post_tweet(test_text)
