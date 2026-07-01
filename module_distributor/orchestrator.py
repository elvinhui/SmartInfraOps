import os
import sys
import json
import urllib.request
import re
from google import genai
from medium_import import push_to_medium, FatalError
from twitter_playwright import post_tweet
from linkedin_api import post_linkedin
from deepseek_polish import polish_article

RSS_URL = os.getenv("RSS_URL", "https://smartinfralog.com/index.xml")
POSTED_URLS_FILE = os.path.join(os.path.dirname(__file__), "posted_urls.txt")

# AI Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# ──────────────────────────────────────────────────────────────────────────────
# URL tracking
# ──────────────────────────────────────────────────────────────────────────────

def load_posted_urls():
    if not os.path.exists(POSTED_URLS_FILE):
        return set()
    with open(POSTED_URLS_FILE, "r") as f:
        return set(line.strip().rstrip('/') for line in f if line.strip() and not line.startswith("#"))

def append_posted_url(url):
    with open(POSTED_URLS_FILE, "a") as f:
        f.write(f"{url}\n")


# ──────────────────────────────────────────────────────────────────────────────
# Article fetching
# ──────────────────────────────────────────────────────────────────────────────

def fetch_article_text(url):
    """Extract plain text from article URL (for social variant generation)."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
        text = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:4000]
    except Exception as e:
        print(f"Warning: Failed to fetch text from {url}: {e}")
        return ""

def fetch_article_html(url):
    """Fetch the article content div HTML for DeepSeek polishing."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        article_div = soup.find(class_="ops-article-content")
        if article_div:
            return str(article_div)
        return ""
    except Exception as e:
        print(f"Warning: Failed to fetch HTML from {url}: {e}")
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# Social variant generation (Gemini)
# ──────────────────────────────────────────────────────────────────────────────

def generate_social_variants(title, url, text):
    """Uses DeepSeek to generate Twitter + LinkedIn copy."""
    if not DEEPSEEK_API_KEY:
        print("DEEPSEEK_API_KEY not set. Using fallback text.")
        return {
            "twitter": f"New post: {title} #BuildInPublic #Python",
            "linkedin": f"I just published: {title}\n\n{url}",
        }

    import openai
    client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    
    system_prompt = (
        'You are a cynical but highly skilled DevOps/Infrastructure engineer who hates repetitive tasks. '
        'You run a blog called "Smart Infra Log". '
        'You must output exactly a JSON object with two keys:\n'
        '"twitter": A short, punchy tweet (max 280 chars) summarizing the technical highlight, '
        'slightly self-deprecating, ending with the tags #BuildInPublic #Python. DO NOT append the URL.\n'
        '"linkedin": A slightly longer, more professional but still authentic post abstracting the '
        'engineering philosophy behind the post, ending with the URL.\n'
        'Do not wrap the JSON in markdown code blocks, just output the raw JSON.'
    )
    user_prompt = f"Title: {title}\nURL: {url}\n\nArticle excerpt:\n{text}"

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=1024,
            temperature=0.7
        )
        result_text = response.choices[0].message.content.strip()
        return json.loads(result_text)
    except Exception as e:
        print(f"Failed to generate social variants via DeepSeek: {e}")
        return {
            "twitter": f"New post: {title} #BuildInPublic #Python",
            "linkedin": f"I just published: {title}\n\n{url}",
        }


# ──────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────────────

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
        print(f"Error fetching/parsing RSS: {e}")
        sys.exit(1)

    if not entries:
        print("Warning: Feed contains no entries.")
        sys.exit(1)

    posted_urls = load_posted_urls()
    new_entries = []
    for entry in reversed(entries):
        link = entry.get('link')
        title = entry.get('title')
        if not link:
            continue
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

        # 1. Fetch content
        text_excerpt = fetch_article_text(url)
        html_content = fetch_article_html(url)

        # 2. Polish article with DeepSeek (returns Markdown)
        print("Polishing article with DeepSeek...")
        polished_markdown = polish_article(html_content)
        # Empty string = DeepSeek skipped/failed; Medium keeps raw imported content

        # 3. Generate social copy with Gemini
        print("Generating AI Social Variants...")
        variants = generate_social_variants(title, url, text_excerpt)
        twitter_text = variants.get("twitter", "")
        linkedin_text = variants.get("linkedin", "")

        # 4. Post to X (Twitter) via Playwright
        print("Pushing to X (Twitter)...")
        if twitter_text:
            x_success = post_tweet(f"{twitter_text}\n\n{url}")
        else:
            x_success = False

        # 5. Post to LinkedIn
        print("Pushing to LinkedIn...")
        in_success = post_linkedin(linkedin_text)

        # 6. Push to Medium via undetected_chromedriver Import + paste
        print("Pushing to Medium (Import + AI paste)...")
        try:
            med_success = push_to_medium(url, title, polished_markdown)
        except FatalError as e:
            print(f"FATAL ERROR: {e}")
            sys.exit(1)

        # 7. Record success
        if med_success:
            print(f"Article {url} successfully pushed to primary channels.")
            append_posted_url(url)
            success_count += 1
        else:
            print(f"Stopping execution due to failure on {url}.")
            sys.exit(1)

    print(f"\nSuccessfully distributed {success_count} articles.")


if __name__ == "__main__":
    main()
