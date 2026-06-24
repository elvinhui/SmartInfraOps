import os
import sys
import json
import undetected_chromedriver as uc

AUTH_JSON_FILE = os.path.join(os.path.dirname(__file__), "twitter_auth.json")

def login():
    print("=======================================================")
    print("启动终极防封锁浏览器 (undetected-chromedriver)...")
    print("正在绕过 X (Twitter) 的机器人安全检测，请稍候...")
    print("=======================================================")
    
    options = uc.ChromeOptions()
    # 使用和系统对应的 Chrome 版本，如果您报错可以去掉 version_main 参数
    try:
        driver = uc.Chrome(options=options, version_main=149)
    except:
        driver = uc.Chrome(options=options)

    print(">> 正在打开 X (Twitter) 登录页...")
    driver.get("https://x.com/login")

    print("\n\n")
    print("⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐")
    print("【关键步骤】请在弹出的浏览器窗口中，手动完成 X (Twitter) 登录！")
    print("注意：如果之前提示限制登录，这次使用的是高隐匿浏览器，正常登录即可。")
    print("登录成功，看到您的 X (Twitter) 首页信息流后，请回到这个黑框里按【回车键】！")
    print("⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐")
    print("\n\n")

    input("等待您完成登录... (看到首页信息流后，请在这里按回车键继续): ")

    print("\n正在提取并转换您的专属身份凭证 (适配 Playwright)...")
    selenium_cookies = driver.get_cookies()
    
    playwright_cookies = []
    for c in selenium_cookies:
        playwright_cookie = {
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": c.get("domain"),
            "path": c.get("path"),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
            "sameSite": c.get("sameSite", "Lax")
        }
        # Selenium uses 'expiry', Playwright uses 'expires'
        if "expiry" in c:
            playwright_cookie["expires"] = c["expiry"]
        else:
            playwright_cookie["expires"] = -1
            
        playwright_cookies.append(playwright_cookie)

    auth_data = {
        "cookies": playwright_cookies,
        "origins": []
    }

    with open(AUTH_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2)

    driver.quit()

    print(f"\n✅ 登录凭证已成功提取并保存到 {AUTH_JSON_FILE}！")
    print("Playwright 以后发推时将会直接继承这个受信任的登录状态。")
    input("按回车键退出...")

if __name__ == "__main__":
    login()
