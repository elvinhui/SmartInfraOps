import os
import sys
import time
import requests
import json
from datetime import datetime, timedelta

# Environment variables for Umami
UMAMI_URL = os.getenv("UMAMI_URL")
UMAMI_USERNAME = os.getenv("UMAMI_USERNAME")
UMAMI_PASSWORD = os.getenv("UMAMI_PASSWORD")
UMAMI_WEBSITE_ID = os.getenv("UMAMI_WEBSITE_ID")

# Environment variables for Meta WhatsApp Cloud API
META_WA_TOKEN = os.getenv("META_WA_TOKEN")
WA_PHONE_ID = os.getenv("WA_PHONE_ID")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER")
WA_TEMPLATE_NAME = os.getenv("WA_TEMPLATE_NAME", "smartinfra_daily_report")

def send_whatsapp_alert(text):
    """Fallback plain text alert for infrastructure failures."""
    if not all([META_WA_TOKEN, WA_PHONE_ID, MY_PHONE_NUMBER]):
        print("Meta WhatsApp credentials not configured. Cannot send alert.")
        return
    
    url = f"https://graph.facebook.com/v22.0/{WA_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_WA_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": MY_PHONE_NUMBER,
        "type": "text",
        "text": {"body": text}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        print("WhatsApp alert sent successfully.")
    except Exception as e:
        print(f"Failed to send WhatsApp alert: {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Response: {response.text}")

def send_whatsapp_template_message(date_str, pv, uv, bounces, top_pages_str):
    """Sends the daily report using a pre-approved Meta WhatsApp Template."""
    if not all([META_WA_TOKEN, WA_PHONE_ID, MY_PHONE_NUMBER]):
        print("Meta WhatsApp credentials not configured. Cannot send report.")
        sys.exit(1)
        
    url = f"https://graph.facebook.com/v22.0/{WA_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_WA_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": MY_PHONE_NUMBER,
        "type": "template",
        "template": {
            "name": WA_TEMPLATE_NAME,
            "language": {
                "code": "zh_CN" # Adjust to match your approved template language
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        { "type": "text", "text": str(date_str) },
                        { "type": "text", "text": str(pv) },
                        { "type": "text", "text": str(uv) },
                        { "type": "text", "text": str(bounces) },
                        { "type": "text", "text": str(top_pages_str) }
                    ]
                }
            ]
        }
    }
    
    # Exponential backoff for API calls
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            
            if response.status_code == 400 and "Template name does not exist" in response.text:
                print("Warning: Template not found. Falling back to plain text message.")
                fallback_text = (
                    f"📊 *SmartInfra-Ops Daily Report*\n"
                    f"📅 Date: {date_str}\n\n"
                    f"👁️ Pageviews (PV): {pv}\n"
                    f"👤 Unique Visitors (UV): {uv}\n"
                    f"🔙 Bounces: {bounces}\n\n"
                    f"🔥 *Top 3 Pages:*\n{top_pages_str}"
                )
                send_whatsapp_alert(fallback_text)
                return
                
            response.raise_for_status()
            print("WhatsApp template message sent successfully.")
            return
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if 'response' in locals() and hasattr(response, 'text'):
                print(f"API Response: {response.text}")
            if attempt < max_retries - 1:
                sleep_time = 2 ** (attempt + 1)
                print(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                print("Max retries reached. Failed to send WhatsApp message.")
                sys.exit(1)

def get_umami_token():
    url = f"{UMAMI_URL.rstrip('/')}/api/auth/login"
    try:
        response = requests.post(url, json={
            "username": UMAMI_USERNAME,
            "password": UMAMI_PASSWORD
        }, timeout=10)
        response.raise_for_status()
        return response.json().get("token")
    except Exception as e:
        print(f"Failed to authenticate with Umami: {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Status Code: {response.status_code}")
            print(f"Response Body: {response.text[:1000]}")
        print(f"Attempted URL: {url}")
        send_whatsapp_alert("🚨 SmartInfra-Ops 警告：基础设施统计服务异常，Umami 控制面板无法访问。")
        sys.exit(1)

def fetch_umami_stats(token, start_ts, end_ts):
    url = f"{UMAMI_URL.rstrip('/')}/api/websites/{UMAMI_WEBSITE_ID}/stats"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "startAt": start_ts,
        "endAt": end_ts
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Failed to fetch Umami stats: {e}")
        send_whatsapp_alert("🚨 SmartInfra-Ops 警告：无法从 Umami 提取 PV/UV 数据。")
        sys.exit(1)

def fetch_umami_metrics(token, start_ts, end_ts):
    url = f"{UMAMI_URL.rstrip('/')}/api/websites/{UMAMI_WEBSITE_ID}/metrics"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "startAt": start_ts,
        "endAt": end_ts,
        "type": "path"
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Failed to fetch Umami metrics: {e}")
        send_whatsapp_alert("🚨 SmartInfra-Ops 警告：无法从 Umami 提取 Top Pages 页面级数据。")
        sys.exit(1)

def main():
    if not all([UMAMI_URL, UMAMI_USERNAME, UMAMI_PASSWORD, UMAMI_WEBSITE_ID]):
        print("Missing required Umami environment variables.")
        sys.exit(1)

    print("Authenticating with Umami...")
    token = get_umami_token()

    # Calculate T-1 timestamps (milliseconds)
    now = datetime.now()
    yesterday = now - timedelta(days=1)
    
    start_of_yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_yesterday = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    start_ts = int(start_of_yesterday.timestamp() * 1000)
    end_ts = int(end_of_yesterday.timestamp() * 1000)
    
    date_str = yesterday.strftime('%Y-%m-%d')

    print(f"Fetching stats for T-1 ({date_str})...")
    stats = fetch_umami_stats(token, start_ts, end_ts)
    metrics = fetch_umami_metrics(token, start_ts, end_ts)

    pv_data = stats.get('pageviews', 0)
    pv = pv_data.get('value', 0) if isinstance(pv_data, dict) else pv_data

    uv_data = stats.get('visitors', 0)
    uv = uv_data.get('value', 0) if isinstance(uv_data, dict) else uv_data

    bounces_data = stats.get('bounces', 0)
    bounces = bounces_data.get('value', 0) if isinstance(bounces_data, dict) else bounces_data
    
    # Sort metrics by views and get top 3
    top_urls = sorted(metrics, key=lambda i: i.get('y', 0), reverse=True)[:3]
    
    top_pages_lines = []
    for i, item in enumerate(top_urls, 1):
        url_path = item.get('x', 'Unknown')
        views = item.get('y', 0)
        top_pages_lines.append(f"{i}. {url_path} ({views} views)")
        
    if not top_urls:
        top_pages_lines.append("No page views recorded.")

    top_pages_str = "\n".join(top_pages_lines)

    print("Sending WhatsApp report...")
    send_whatsapp_template_message(date_str, pv, uv, bounces, top_pages_str)

if __name__ == "__main__":
    main()
