import os
import sys
import time
import json
import random
import requests
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class FatalError(Exception):
    pass

def verify_ip_killswitch():
    print("Executing Infra Kill-Switch IP Verification...")
    proxies = {
        "http": "http://127.0.0.1:8080",
        "https": "http://127.0.0.1:8080",
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Use ip-api.com for ASN and Country info
            resp = requests.get("http://ip-api.com/json", proxies=proxies, timeout=10)
            data = resp.json()
            org = data.get("org", "").lower()
            isp = data.get("isp", "").lower()
            country = data.get("countryCode", "").upper()
            print(f"Detected Proxy Location: {country}, ISP/Org: {org} / {isp}")
            
            # Check against Microsoft/Azure/Github
            if "microsoft" in org or "microsoft" in isp or "github" in org:
                print("FATAL: Kill-Switch triggered. IP belongs to Microsoft/GitHub. Proxy tunnel failed.")
                sys.exit(1)
            
            # Check geographic alignment if strictly enforced in PRD
            if country not in ["SG", "MY"]:
                print(f"Warning: Proxy country is {country}, expected SG or MY. Proceeding at your own risk.")
            return # Success
                
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"IP verify failed ({e}), retrying in 5s...")
                time.sleep(5)
            else:
                print(f"FATAL: Kill-Switch triggered. Failed to reach external API via proxy after retries. Reason: {e}")
                sys.exit(1)

def bionic_type(driver, element, text):
    """Bionic typing replacement that uses JS to support emojis (non-BMP chars) safely."""
    print("Bionic Interaction: Simulating thinking pause before typing...")
    time.sleep(random.uniform(1.0, 3.0))
    driver.execute_script("document.execCommand('insertText', false, arguments[0]);", text)
    time.sleep(1.0)

def post_tweet(text, url):
    """
    Posts a tweet using undetected_chromedriver via local gost proxy (127.0.0.1:8080).
    Phase 1: Pure text, no URL.
    Phase 2: Text in main tweet, URL in a self-reply.
    """
    verify_ip_killswitch()

    phase = os.getenv("X_PHASE", "1")
    auth_file = os.getenv("TWITTER_AUTH_JSON_FILE", "twitter_auth.json")
    script_dir = os.path.dirname(__file__)
    auth_file_path = auth_file if os.path.exists(auth_file) else os.path.join(script_dir, auth_file)

    if not os.path.exists(auth_file_path):
        print(f"Error: {auth_file_path} not found. Cannot authenticate with X.")
        return False

    print(f"Loading cookies from {auth_file_path}...")
    with open(auth_file_path, "r") as f:
        auth_data = json.load(f)
    cookies = auth_data.get("cookies", [])

    options = uc.ChromeOptions()
    options.add_argument('--proxy-server=http://127.0.0.1:8080')
    
    print("Starting undetected-chromedriver for X...")
    driver = uc.Chrome(options=options, version_main=149, headless=False)
    wait = WebDriverWait(driver, 30)

    try:
        # Load X.com to set cookies
        print("Navigating to x.com to set cookies...")
        driver.get("https://x.com/404")
        
        for cookie in cookies:
            cookie_dict = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain", ".x.com"),
                "path": cookie.get("path", "/")
            }
            if "secure" in cookie: cookie_dict["secure"] = cookie["secure"]
            if "httpOnly" in cookie: cookie_dict["httpOnly"] = cookie["httpOnly"]
            try:
                driver.add_cookie(cookie_dict)
            except Exception:
                pass

        print("Navigating to X compose page...")
        driver.get("https://x.com/compose/tweet")
        time.sleep(5)
        
        # 1. Focus text area
        print("Waiting for tweet input area...")
        textarea_xpath = "//div[@data-testid='tweetTextarea_0']"
        textarea = wait.until(EC.presence_of_element_located((By.XPATH, textarea_xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", textarea)
        time.sleep(1)
        
        try:
            textarea.click()
        except:
            driver.execute_script("arguments[0].click();", textarea)
            
        time.sleep(1)

        # 2. Bionic typing
        print(f"Entering text (Phase {phase} mode)...")
        bionic_type(driver, textarea, text)
        time.sleep(2)
        
        driver.save_screenshot("debug_twitter_before_click.png")
        
        # 3. Click Tweet button
        print("Clicking tweet button...")
        tweet_btn_xpath = "//button[@data-testid='tweetButton']"
        tweet_button = wait.until(EC.presence_of_element_located((By.XPATH, tweet_btn_xpath)))
        
        # Use robust click for headless
        try:
            tweet_button.click()
        except:
            driver.execute_script("arguments[0].click();", tweet_button)
            
        print("Waiting for tweet to be sent...")
        time.sleep(5)
        
        if phase == "2":
            print("Phase 2 active: Initiating self-reply for URL injection...")
            try:
                toast_view_xpath = "//a[@dir='ltr' and .//span[text()='View']] | //a[@data-testid='toast-action']"
                view_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, toast_view_xpath)))
                try:
                    view_btn.click()
                except:
                    driver.execute_script("arguments[0].click();", view_btn)
                time.sleep(4)
                
                print("Clicking Reply button...")
                reply_btn_xpath = "//button[@data-testid='reply']"
                reply_btn = wait.until(EC.presence_of_element_located((By.XPATH, reply_btn_xpath)))
                try:
                    reply_btn.click()
                except:
                    driver.execute_script("arguments[0].click();", reply_btn)
                time.sleep(2)
                
                reply_textarea = wait.until(EC.presence_of_element_located((By.XPATH, "//div[@data-testid='tweetTextarea_0']")))
                print("Injecting URL via self-reply...")
                reply_msg = f"Full details here: {url}"
                bionic_type(driver, reply_textarea, reply_msg)
                time.sleep(2)
                
                reply_submit_xpath = "//button[@data-testid='tweetButton']"
                reply_submit = wait.until(EC.presence_of_element_located((By.XPATH, reply_submit_xpath)))
                try:
                    reply_submit.click()
                except:
                    driver.execute_script("arguments[0].click();", reply_submit)
                    
                print("URL injected successfully via self-reply.")
                time.sleep(5)
            except Exception as e:
                print(f"Warning: Failed to execute Phase 2 self-reply. Reason: {e}")
                driver.save_screenshot("error_twitter_reply.png")

        print("Successfully pushed to X (Twitter).")
        return True

    except Exception as e:
        print(f"Error while pushing to X (Twitter): {e}")
        try:
            driver.save_screenshot("error_twitter_rpa_uc.png")
        except:
            pass
        return False
    finally:
        driver.quit()

if __name__ == "__main__":
    test_text = f"Test stealth tweet from UC RPA! Timestamp: {int(time.time())}"
    test_url = "https://smartinfralog.com/test-url"
    post_tweet(test_text, test_url)
