import os
import sys
import time
import json
import urllib.request
import re
from google import genai
from medium_import import push_to_medium, FatalError
from twitter_api import post_tweet
from linkedin_api import post_linkedin

RSS_URL = os.getenv("RSS_URL", "https://smartinfralog.com/index.xml")
POSTED_URLS_FILE = os.path.join(os.path.dirname(__file__), "posted_urls.txt")

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def load_posted_urls():
    if not os.path.exists(POSTED_URLS_FILE):
        return set()
    with open(POSTED_URLS_FILE, "r") as f:
        return set(line.strip().rstrip('/') for line in f if line.strip() and not line.startswith("#"))

def append_posted_url(url):
    with open(POSTED_URLS_FILE, "a") as f:
        f.write(f"{url}\n")

def fetch_article_text(url):
    """
    Very basic HTML parsing to extract text content.
    For a production robust version, Beautifulsoup could be used, but keeping it dependency-light.
    """
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
        
        # Extremely basic text extraction: strip script/style tags, then strip all tags
        text = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Take first 4000 chars to avoid token limits for context
        return text[:4000]
    except Exception as e:
        print(f"Warning: Failed to fetch text from {url}: {e}")
        return ""

def generate_social_variants(title, url, text):
    """
    Uses Gemini (3.1 Pro) to generate variants.
    """
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set. Using fallback dummy text.")
        return {
            "twitter": f"New post: {title} {url} #BuildInPublic #Python",
            "linkedin": f"I just published a new article on my blog about: {title}.\n\nCheck it out here: {url}"
        }

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    system_prompt = """You are a cynical but highly skilled DevOps/Infrastructure engineer who hates repetitive tasks. 
You run a blog called "Smart Infra Log". You are writing social media promotional copy for your latest blog post.

You must output exactly a JSON object with two keys:
"twitter": A short, punchy tweet (max 280 chars) summarizing the technical highlight, slightly self-deprecating, ending with the tags #BuildInPublic #Python. DO NOT append the URL.
"linkedin": A slightly longer, more professional but still authentic post abstracting the engineering philosophy behind the post, ending with the URL.

Do not wrap the JSON in markdown code blocks, just output the raw JSON."""

    user_prompt = f"Title: {title}\nURL: {url}\n\nArticle excerpt:\n{text}"

    try:
        response = client.models.generate_content(
            model='gemini-2.5-pro', # Fallback to gemini-pro if 3.1 is not natively accepted by the older SDK name, actually we should use gemini-pro or gemini-2.5-pro
            contents=[system_prompt + "\n\n" + user_prompt],
        )
        
        result_text = response.text
        # Clean up any potential markdown formatting from the response
        result_text = result_text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        elif result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
            
        return json.loads(result_text.strip())
    except Exception as e:
        print(f"Failed to generate social variants via Gemini: {e}")
        # Fallback
        return {
            "twitter": f"New post: {title} #BuildInPublic #Python",
            "linkedin": f"I just published a new article on my blog about: {title}.\n\nCheck it out here: {url}"
        }

def main():
    import xml.etree.ElementTree as ET
    print(f"Fetching RSS feed natively from {RSS_URL}...")
    req = urllib.request.Request(RSS_URL, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        
        entries = []
        for item in root.findall('.//item'):
            title_elem = item.find('title')
            link_elem = item.find('link')
            if title_elem is not None and link_elem is not None:
                entries.append({'title': title_elem.text, 'link': link_elem.text})
                
    except Exception as e:
        print(f"Error fetching/parsing native RSS: {e}")
        sys.exit(1)
        
    if len(entries) == 0:
        print("Warning: Feed contains no entries or parsing failed.")
        sys.exit(1)
        
    posted_urls = load_posted_urls()
    new_entries = []
    
    for entry in reversed(entries):
        link = entry.get('link')
        title = entry.get('title')
        
        if not link:
            continue
            
        # Only process actual blog posts, skip pages like Privacy Policy, About, etc.
        if "/posts/" not in link:
            print(f"Skipping non-post page: {title} ({link})")
            continue
            
        clean_link = link.rstrip('/')
        if clean_link not in posted_urls:
            new_entries.append((clean_link, title))

    if not new_entries:
        print("No new articles to distribute.")
        return

    print(f"Found {len(new_entries)} new article(s) to distribute.")
    
    success_count = 0
    for url, title in new_entries:
        print(f"\n--- Processing: {title} ({url}) ---")
        
        # 1. Fetch text for AI variants
        text_excerpt = fetch_article_text(url)
        
        # 2. AI Gen
        print("Generating AI Social Variants...")
        variants = generate_social_variants(title, url, text_excerpt)
        twitter_text = variants.get("twitter", "")
        linkedin_text = variants.get("linkedin", "")
        
        # 3. Dispatch to X
        print("Pushing to X (Twitter)...")
        x_success = post_tweet(twitter_text, url)
        
        # 4. Dispatch to LinkedIn
        print("Pushing to LinkedIn...")
        in_success = post_linkedin(linkedin_text)
        
        # 5. Dispatch to Medium (RPA via Import)
        print("Pushing to Medium (RPA via Import)...")
        try:
            med_success = push_to_medium(url, title)
        except FatalError as e:
            print(f"FATAL ERROR: {e}")
            sys.exit(1)
            
        # 6. Assess Transaction
        if med_success:
            # Even if X or LinkedIn failed, if Medium succeeded we consider it posted 
            # because Medium RPA is the heaviest and we don't want to duplicate drafts.
            # In a true event-driven system, we'd have independent state for each platform.
            print(f"Article {url} successfully pushed to primary channels.")
            append_posted_url(url)
            success_count += 1
        else:
            print(f"Stopping execution due to failure on {url}.")
            sys.exit(1)
            
    print(f"\nSuccessfully distributed {success_count} articles.")

if __name__ == "__main__":
    main()
