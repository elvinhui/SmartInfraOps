from playwright.sync_api import sync_playwright

def main():
    print("Opening browser for Medium login...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        print("Navigating to Medium...")
        page.goto("https://medium.com/")
        
        print("\n=========================================")
        print("PLEASE LOG IN TO MEDIUM IN THE BROWSER WINDOW.")
        print("Once you have successfully logged in and can see your homepage,")
        print("CLOSE the browser window.")
        print("=========================================\n")
        
        # Wait for the page to be closed
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        
        # Save the auth state
        context.storage_state(path="medium_auth.json")
        print("✅ Successfully saved login state to medium_auth.json")

if __name__ == "__main__":
    main()
