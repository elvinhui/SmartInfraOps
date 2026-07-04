import os
import sys
import time
import requests
import traceback
from datetime import datetime, timedelta

# Environment variables for Umami
UMAMI_URL = os.getenv("UMAMI_URL")
UMAMI_USERNAME = os.getenv("UMAMI_USERNAME")
UMAMI_PASSWORD = os.getenv("UMAMI_PASSWORD")
UMAMI_WEBSITE_ID = os.getenv("UMAMI_WEBSITE_ID")

# Environment variables for NOC ChatOps
NOC_WEBHOOK_URL = os.getenv("NOC_WEBHOOK_URL")


def build_success_payload(date_str, pv, uv, bounces, top_pages_lines):
    """
    Builds the Slack Block Kit payload for a successful T-1 data fetch.
    """
    top_pages_formatted = "\n".join(top_pages_lines)
    if not top_pages_formatted:
        top_pages_formatted = "No page views recorded."

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📊 Smart Infra Log | 每日运行看板",
                    "emoji": True
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🟢 *正常* | {date_str}"
                    }
                ]
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Pageviews (PV)*\n{pv}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Visitors (UV)*\n{uv}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Bounces*\n{bounces}"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🔥 Top 3 Paths:*\n{top_pages_formatted}"
                }
            }
        ]
    }
    return payload


def build_critical_payload(error_msg="🚨 CRITICAL: 基础设施 (Umami) 状态异常，无法获取统计流。"):
    """
    Builds the Slack Block Kit payload for a critical alert (Umami down or timeout).
    """
    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 CRITICAL ALERT",
                    "emoji": True
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "🔴 *异常状态*"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{error_msg}*"
                }
            }
        ]
    }
    return payload


def send_webhook(payload):
    """
    Sends the JSON payload to the configured Slack/Discord Webhook URL.
    """
    if not NOC_WEBHOOK_URL:
        print("Error: NOC_WEBHOOK_URL is not set.")
        sys.exit(1)

    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(NOC_WEBHOOK_URL, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        print("Webhook alert sent successfully.")
    except Exception as e:
        print(f"Failed to send webhook alert: {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Response: {response.text}")


def get_umami_token():
    """Authenticates with Umami and returns a JWT token."""
    url = f"{UMAMI_URL.rstrip('/')}/api/auth/login"
    response = requests.post(url, json={
        "username": UMAMI_USERNAME,
        "password": UMAMI_PASSWORD
    }, timeout=10)
    response.raise_for_status()
    return response.json().get("token")


def fetch_umami_stats(token, start_ts, end_ts):
    """Fetches general stats (pv, uv, bounces) from Umami."""
    url = f"{UMAMI_URL.rstrip('/')}/api/websites/{UMAMI_WEBSITE_ID}/stats"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "startAt": start_ts,
        "endAt": end_ts
    }
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def fetch_umami_metrics(token, start_ts, end_ts):
    """Fetches page path metrics from Umami."""
    url = f"{UMAMI_URL.rstrip('/')}/api/websites/{UMAMI_WEBSITE_ID}/metrics"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "startAt": start_ts,
        "endAt": end_ts,
        "type": "path"
    }
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def fetch_and_alert():
    """Main execution function with try-except for heartbeat monitoring."""
    if not all([UMAMI_URL, UMAMI_USERNAME, UMAMI_PASSWORD, UMAMI_WEBSITE_ID, NOC_WEBHOOK_URL]):
        missing = [var for var in ["UMAMI_URL", "UMAMI_USERNAME", "UMAMI_PASSWORD", "UMAMI_WEBSITE_ID", "NOC_WEBHOOK_URL"] if not os.getenv(var)]
        print(f"Missing required environment variables: {', '.join(missing)}")
        if NOC_WEBHOOK_URL:
            # If we at least have the webhook, we can send a config error alert
            send_webhook(build_critical_payload(f"Configuration Error: Missing {', '.join(missing)}"))
        sys.exit(1)

    try:
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
            top_pages_lines.append(f"{i}. `{url_path}` ({views} views)")
            
        print("Assembling Slack Block Kit payload...")
        payload = build_success_payload(date_str, pv, uv, bounces, top_pages_lines)
        
        print("Sending successful NOC webhook report...")
        send_webhook(payload)
        
    except Exception as e:
        print(f"Exception occurred while fetching data from Umami: {e}")
        traceback.print_exc()
        
        # Send critical red alert card
        print("Sending CRITICAL alert to NOC webhook...")
        critical_payload = build_critical_payload("🚨 CRITICAL: 基础设施 (Umami) 状态异常，无法获取统计流。")
        send_webhook(critical_payload)
        # Exit with error status for GitHub Actions to record a failure
        sys.exit(1)


if __name__ == "__main__":
    fetch_and_alert()
