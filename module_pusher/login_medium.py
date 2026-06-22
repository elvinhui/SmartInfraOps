from playwright.sync_api import sync_playwright

def main():
    print("Opening browser for Medium login...")
    with sync_playwright() as p:
        try:
            # Use the real system Chrome to avoid Cloudflare detection
            browser = p.chromium.launch(headless=False, channel="chrome")
        except Exception as e:
            print(f"Could not launch system Chrome, falling back to Chromium... ({e})")
            browser = p.chromium.launch(headless=False)
            
        context = browser.new_context()
        
        # Inject an anti-bot script to help bypass Cloudflare spinner
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = context.new_page()
        
        print("Navigating to Medium...")
        page.goto("https://medium.com/")
        
        print("\n=========================================")
        print("PLEASE LOG IN TO MEDIUM IN THE BROWSER WINDOW.")
        print("Once you have successfully logged in and can see your homepage,")
        print("CLOSE the browser window.")
        print("=========================================\n")
        
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        
        context.storage_state(path="medium_auth.json")
        print("✅ Successfully saved login state to medium_auth.json")

if __name__ == "__main__":
    main()
