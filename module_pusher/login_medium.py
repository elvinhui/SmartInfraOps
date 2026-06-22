import os
import sys
import json
import undetected_chromedriver as uc

AUTH_JSON_FILE = os.getenv("MEDIUM_AUTH_JSON_FILE", "medium_auth.json")

def login():
    print("=======================================================")
    print("启动终极防封锁浏览器 (undetected-chromedriver)...")
    print("正在绕过 Cloudflare 安全检测，请稍候...")
    print("=======================================================")
    
    options = uc.ChromeOptions()
    driver = uc.Chrome(options=options, version_main=149)

    print(">> 正在打开 Medium 登录页...")
    driver.get("https://medium.com/m/signin")

    print("\n\n")
    print("⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐")
    print("【关键步骤】请在弹出的浏览器窗口中，手动完成 Medium 登录！")
    print("登录成功，看到您的 Medium 首页后，请回到这个黑框里按【回车键】！")
    print("⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐")
    print("\n\n")

    input("等待您完成登录... (登录完成后，请在这里按回车键继续): ")

    print("\n正在提取并保存您的专属身份凭证...")
    cookies = driver.get_cookies()

    auth_data = {
        "cookies": cookies,
        "origins": [
            {
                "origin": "https://medium.com",
                "localStorage": [
                    {
                        "name": "viewer-status|is-logged-in",
                        "value": "true"
                    }
                ]
            }
        ]
    }

    with open(AUTH_JSON_FILE, "w") as f:
        json.dump(auth_data, f, indent=2)

    driver.quit()

    print(f"\n✅ 登录凭证已成功保存到 {AUTH_JSON_FILE}！")
    print("防封锁配置大功告成！之后电脑开机即可全自动推送。")
    input("按回车键退出...")

if __name__ == "__main__":
    login()
