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
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def get_supabase_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("FATAL ERROR: SUPABASE_URL or SUPABASE_KEY not set! Cannot track posted URLs robustly.")
        sys.exit(1)
    try:
        from supabase import create_client, Client
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"FATAL ERROR initializing Supabase client: {e}")
        sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
# URL tracking
# ──────────────────────────────────────────────────────────────────────────────

def load_posted_urls():
    client = get_supabase_client()
    try:
        response = client.table("posted_articles").select("url").execute()
        return set(row["url"].strip().rstrip('/') for row in response.data)
    except Exception as e:
        print(f"FATAL ERROR fetching from Supabase: {e}")
        print("Aborting to prevent duplicate posting.")
        sys.exit(1)

def append_posted_url(url):
    client = get_supabase_client()
    try:
        client.table("posted_articles").insert({"url": url}).execute()
        print(f"Recorded {url} to Supabase posted_articles table.")
    except Exception as e:
        print(f"FATAL ERROR inserting into Supabase: {e}")
        print("Aborting pipeline to prevent inconsistencies.")
        sys.exit(1)


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

def generate_social_variants(title, url, text, categories):
    """Uses DeepSeek to generate Twitter + LinkedIn copy, and Medium topics."""
    if not DEEPSEEK_API_KEY:
        print("DEEPSEEK_API_KEY not set. Using fallback text.")
        return {
            "twitter": f"New post: {title} #BuildInPublic #Python",
            "linkedin": f"I just published: {title}\n\n{url}",
            "medium_topics": categories[:5] if categories else ["Technology", "DevOps", "Infrastructure", "Python", "Cloud"]
        }

    import openai
    client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    
    system_prompt = (
        'You are a cynical but highly skilled DevOps/Infrastructure engineer who hates repetitive tasks. '
        'You run a blog called "Smart Infra Log". '
        'You must output exactly a JSON object with three keys:\n'
        '"twitter": A short, punchy tweet (max 280 chars) summarizing the technical highlight, '
        'slightly self-deprecating, ending with the tags #BuildInPublic #Python. DO NOT append the URL.\n'
        '"linkedin": A slightly longer, more professional but still authentic post abstracting the '
        'engineering philosophy behind the post, ending with the URL.\n'
        '"medium_topics": A list of exactly 5 short strings representing the best Medium.com topics/tags for this article, factoring in the original tags if relevant (e.g. ["DevOps", "Python", "Infrastructure", "Cloud", "SRE"]).\n'
        'Do not wrap the JSON in markdown code blocks, just output the raw JSON.'
    )
    user_prompt = f"Title: {title}\nURL: {url}\nOriginal Tags: {categories}\n\nArticle excerpt:\n{text}"

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
            "medium_topics": categories[:5] if categories else ["Technology", "DevOps", "Infrastructure", "Python", "Cloud"]
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
            categories = [c.text for c in item.findall('category') if c.text]
            if title_elem is not None and link_elem is not None:
                entries.append({'title': title_elem.text, 'link': link_elem.text, 'categories': categories})
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
            new_entries.append((clean_link, title, entry.get('categories', [])))

    if not new_entries:
        print("No new articles to distribute.")
        return

    if len(new_entries) > 2:
        print(f"Limiting to 2 articles per run (out of {len(new_entries)} new ones) to avoid bot detection.")
        new_entries = new_entries[:2]
    else:
        print(f"Found {len(new_entries)} new article(s) to distribute.")

    success_count = 0

    for url, title, categories in new_entries:
        print(f"\n--- Processing: {title} ({url}) ---")

        # 1. Fetch content
        text_excerpt = fetch_article_text(url)
        html_content = fetch_article_html(url)

        # 2. Polish article with DeepSeek (returns Markdown)
        print("Polishing article with DeepSeek...")
        polished_markdown = polish_article(html_content)
        # Empty string = DeepSeek skipped/failed; Medium keeps raw imported content

        # 3. Generate social copy with Gemini/DeepSeek
        print("Generating AI Social Variants and Medium Topics...")
        variants = generate_social_variants(title, url, text_excerpt, categories)
        twitter_text = variants.get("twitter", "")
        linkedin_text = variants.get("linkedin", "")
        medium_topics = variants.get("medium_topics", categories)
        if not isinstance(medium_topics, list):
            medium_topics = categories

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
            med_success = push_to_medium(url, title, polished_markdown, topics=medium_topics)
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
