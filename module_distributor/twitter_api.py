import os
import tweepy
import time

def post_tweet(text):
    """
    Posts a tweet using the Twitter API v2.
    Implements Exponential Backoff for rate limiting / network jitter.
    """
    consumer_key = os.getenv("X_CONSUMER_KEY")
    consumer_secret = os.getenv("X_CONSUMER_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
        print("X (Twitter) credentials not fully configured. Skipping tweet.")
        return False

    client = tweepy.Client(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        access_token=access_token,
        access_token_secret=access_token_secret
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.create_tweet(text=text)
            print(f"Tweet posted successfully! ID: {response.data['id']}")
            return True
        except tweepy.errors.TooManyRequests as e:
            print(f"Rate limited by X: {e}")
            sleep_time = 2 ** (attempt + 1)
            print(f"Retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)
        except Exception as e:
            print(f"Attempt {attempt + 1} failed to post tweet: {e}")
            if attempt < max_retries - 1:
                sleep_time = 2 ** (attempt + 1)
                print(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                print("Max retries reached. Failed to post tweet.")
                return False
    return False

if __name__ == "__main__":
    # Test
    pass
