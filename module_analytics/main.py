import os
import sys
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Environment variables
UMAMI_URL = os.getenv("UMAMI_URL")
UMAMI_USERNAME = os.getenv("UMAMI_USERNAME")
UMAMI_PASSWORD = os.getenv("UMAMI_PASSWORD")
UMAMI_WEBSITE_ID = os.getenv("UMAMI_WEBSITE_ID")
WHATSAPP_PHONE_NUMBER = os.getenv("WHATSAPP_PHONE_NUMBER")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY")

def send_whatsapp_message(text):
    if not WHATSAPP_PHONE_NUMBER or not WHATSAPP_API_KEY:
        print("WhatsApp credentials not configured.")
        return
    
    url = f"https://api.callmebot.com/whatsapp.php"
    params = {
        "phone": WHATSAPP_PHONE_NUMBER,
        "text": text,
        "apikey": WHATSAPP_API_KEY
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        print("WhatsApp message sent successfully.")
    except Exception as e:
        print(f"Failed to send WhatsApp message: {e}")
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
        send_whatsapp_message("🚨 SmartInfra-Ops: Umami stats service is currently offline or unreachable.")
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
        send_whatsapp_message("🚨 SmartInfra-Ops: Failed to fetch Umami stats.")
        sys.exit(1)

def fetch_umami_metrics(token, start_ts, end_ts):
    url = f"{UMAMI_URL.rstrip('/')}/api/websites/{UMAMI_WEBSITE_ID}/metrics"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "startAt": start_ts,
        "endAt": end_ts,
        "type": "url"
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Failed to fetch Umami metrics: {e}")
        send_whatsapp_message("🚨 SmartInfra-Ops: Failed to fetch Umami metrics.")
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
    
    # Start of yesterday (00:00:00)
    start_of_yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    # End of yesterday (23:59:59)
    end_of_yesterday = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    start_ts = int(start_of_yesterday.timestamp() * 1000)
    end_ts = int(end_of_yesterday.timestamp() * 1000)
    
    date_str = yesterday.strftime('%Y-%m-%d')

    print(f"Fetching stats for T-1 ({date_str})...")
    stats = fetch_umami_stats(token, start_ts, end_ts)
    metrics = fetch_umami_metrics(token, start_ts, end_ts)

    pv = stats.get('pageviews', {}).get('value', 0)
    uv = stats.get('visitors', {}).get('value', 0)
    bounces = stats.get('bounces', {}).get('value', 0)
    
    # Sort metrics by views (y value in Umami v2) and get top 3
    # Format of metrics response in v2: [{"x": "/path", "y": 10}, ...]
    top_urls = sorted(metrics, key=lambda i: i.get('y', 0), reverse=True)[:3]
    
    report_lines = [
        f"📊 *SmartInfra-Ops Daily Report*",
        f"📅 Date: {date_str}",
        "",
        f"👁️ Pageviews (PV): {pv}",
        f"👤 Unique Visitors (UV): {uv}",
        f"🔙 Bounces: {bounces}",
        "",
        "🔥 *Top 3 Pages:*"
    ]
    
    for i, item in enumerate(top_urls, 1):
        url_path = item.get('x', 'Unknown')
        views = item.get('y', 0)
        report_lines.append(f"{i}. {url_path} ({views} views)")
        
    if not top_urls:
        report_lines.append("No page views recorded.")

    report_text = "\n".join(report_lines)
    print("Sending WhatsApp report...")
    send_whatsapp_message(report_text)

if __name__ == "__main__":
    main()
