import os
import time
import json
import undetected_chromedriver as uc

def load_cookies():
    auth_file = os.path.join(os.path.dirname(__file__), "medium_auth.json")
    try:
        with open(auth_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("cookies", [])
    except Exception as e:
        print(e)
        return []

def main():
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if not os.environ.get("DISPLAY"):
        options.add_argument("--headless=new")
    
    driver = uc.Chrome(options=options)
    try:
        driver.get("https://medium.com/404")
        time.sleep(2)
        cookies = load_cookies()
        for c in cookies:
            cookie_dict = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".medium.com"),
                "path": c.get("path", "/")
            }
            if "secure" in c: cookie_dict["secure"] = c["secure"]
            if "httpOnly" in c: cookie_dict["httpOnly"] = c["httpOnly"]
            try: driver.add_cookie(cookie_dict)
            except: pass
            
        driver.get("https://medium.com/me/stories/drafts")
        time.sleep(10)
        
        html = driver.execute_script("return document.body.innerHTML;")
        with open("medium_drafts_dump.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Dumped HTML to medium_drafts_dump.html")
        
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
