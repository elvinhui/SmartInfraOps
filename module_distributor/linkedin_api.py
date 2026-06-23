import os
import requests
import time

def post_linkedin(text):
    """
    Posts text to LinkedIn using the Posts API.
    Implements Exponential Backoff.
    """
    access_token = os.getenv("LINKEDIN_TOKEN")
    person_urn = os.getenv("LINKEDIN_PERSON_URN") # Format: urn:li:person:{id}

    if not all([access_token, person_urn]):
        print("LinkedIn credentials not fully configured. Skipping post.")
        return False

    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": "202401",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    payload = {
        "author": person_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState": "PUBLISHED"
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            print("LinkedIn post created successfully!")
            print("Post ID:", response.headers.get("x-restli-id"))
            return True
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed to post to LinkedIn: {e}")
            if 'response' in locals() and hasattr(response, 'text'):
                print(f"API Response: {response.text}")
                
            if response.status_code == 401:
                print("LinkedIn Token has expired. Please refresh the token.")
                return False
                
            if attempt < max_retries - 1:
                sleep_time = 2 ** (attempt + 1)
                print(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                print("Max retries reached. Failed to post to LinkedIn.")
                return False
    return False

if __name__ == "__main__":
    pass
