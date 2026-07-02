"""
twitter_playwright.py
Posts a tweet via Playwright Chromium using cookie-based authentication.
Reads cookies from x_auth.json (decoded from X_AUTH_JSON_BASE64 secret).
"""
import os
import json
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _load_cookies() -> list:
    """Load Twitter/X cookies from x_auth.json (written by workflow)."""
    auth_file = os.path.join(os.path.dirname(__file__), "x_auth.json")
    if not os.path.exists(auth_file):
        print("Warning: x_auth.json not found. Skipping Twitter.")
        return []
    try:
        with open(auth_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("cookies", [])
    except Exception as e:
        print(f"Warning: Failed to load x_auth.json: {e}")
        return []


def _to_playwright_cookie(c: dict) -> dict:
    """Convert an EditThisCookie export dict to a Playwright cookie dict."""
    same_site_map = {
        "no_restriction": "None",
        "lax": "Lax",
        "strict": "Strict",
        "unspecified": "None",
    }
    raw_ss = (c.get("sameSite") or "no_restriction").lower()
    pw = {
        "name": c["name"],
        "value": c["value"],
        "domain": c.get("domain", ".x.com"),
        "path": c.get("path", "/"),
        "httpOnly": c.get("httpOnly", False),
        "secure": c.get("secure", True),
        "sameSite": same_site_map.get(raw_ss, "None"),
    }
    if "expirationDate" in c:
        pw["expires"] = int(c["expirationDate"])
    return pw


def post_tweet(text: str) -> bool:
    """
    Posts a tweet via Playwright stealth Chromium.
    Returns True on success, False on failure.
    """
    proxy_server = os.getenv("PROXY_SERVER")
    if proxy_server:
        print(f"Using SOCKS5 proxy: {proxy_server.split('@')[-1]}")
    else:
        print("Warning: No PROXY_SERVER set. Using direct connection (cloud IP).")

    cookies = _load_cookies()
    if not cookies:
        print("X (Twitter) cookies not configured. Skipping tweet.")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        proxy_config = {"server": proxy_server} if proxy_server else None
        context = browser.new_context(
            proxy=proxy_config,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        pw_cookies = []
        for c in cookies:
            try:
                pw_cookies.append(_to_playwright_cookie(c))
            except Exception:
                pass
        if pw_cookies:
            context.add_cookies(pw_cookies)

        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        try:
            print("Navigating to X (Twitter) home...")
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Click compose box
            print("Opening tweet compose box...")
            page.locator(
                '[data-testid="tweetTextarea_0"], [aria-label="Post text"]'
            ).first.click(timeout=15000)
            time.sleep(1)

            # Type tweet
            print(f"Typing tweet ({len(text)} chars)...")
            page.keyboard.type(text, delay=25)
            time.sleep(1)

            # Click post button
            print("Clicking Post button...")
            page.locator(
                '[data-testid="tweetButtonInline"], [data-testid="tweetButton"]'
            ).first.click(timeout=10000)
            time.sleep(3)

            print("Tweet posted successfully via Playwright!")
            return True

        except PlaywrightTimeoutError as e:
            print(f"Timeout while posting tweet: {e}")
            try:
                page.screenshot(path="error_twitter.png")
            except Exception:
                pass
            return False
        except Exception as e:
            print(f"Failed to post tweet via Playwright: {e}")
            try:
                page.screenshot(path="error_twitter.png")
            except Exception:
                pass
            return False
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    result = post_tweet("Test tweet from SmartInfraOps. #BuildInPublic")
    print(f"Result: {result}")
