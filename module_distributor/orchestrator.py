import os
import sys
import time
import json
import urllib.request
import re
from openai import OpenAI
from uc_medium import push_to_medium, FatalError
from uc_twitter import post_tweet
from linkedin_api import post_linkedin

RSS_URL = os.getenv("RSS_URL", "https://smartinfralog.com/index.xml")
POSTED_URLS_FILE = os.path.join(os.path.dirname(__file__), "posted_urls.txt")

# OpenRouter Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

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

def fetch_article_html(url):
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

def polish_article_with_claude(html_content):
    if not html_content:
        return ""
    if not OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY not set. Cannot polish article.")
        return html_content
    
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    
    system_prompt = """你现在是一个顶级的硅谷技术博主兼 Medium 爆款制造机。你的受众是高级软件工程师、独立开发者和技术极客。

你的任务是将一篇硬核的技术设施/自动化理财博客，润色成符合 Medium 调性的高赞文章。

请严格遵循以下润色规则：
1. **情绪引入 (The Hook)：** 开头必须直击痛点。用略带自嘲、对重复性体力劳动极度厌恶的语气，讲出你为什么要写这个系统（例如：“我实在受够了每个月打开那个又蠢又慢的 Excel 去算汇率了...”）。
2. **保留硬核 (Keep it Hardcore)：** 绝对不要为了通俗而删减核心技术细节！保留所有的 Python 脚本、MLOps 概念、无状态(Stateless)架构理念和金融代码。受众喜欢看你秀硬核操作。
3. **降维打击的类比：** 尝试把生活中的问题，用 IT 基础设施的行话来解释。比如“把个人资产当成微服务来管理”、“给自己的现金流加上高可用架构”。
4. **排版极客化：** 严格使用 Markdown 格式。使用 Blockquotes (引用) 来标出核心箴言，使用代码块高亮代码，标题要有逻辑性和层次感。
5. **语言风格：** 英文输出，语气要自信、务实、直截了当 (Direct & Pragmatic)，杜绝毫无意义的客套废话。

非常重要的一点：你的输入是一段原始文章的HTML（或者是纯文本）。请直接输出润色后的Markdown内容，不要输出任何其他的客套话或前言后语。"""
    
    try:
        import markdown
        response = client.chat.completions.create(
            model="anthropic/claude-3-haiku",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": html_content}
            ],
            temperature=0.3
        )
        md_content = response.choices[0].message.content
        html_output = markdown.markdown(md_content, extensions=['fenced_code', 'tables'])
        return html_output
    except Exception as e:
        print(f"Failed to polish article via OpenRouter Claude: {e}")
        return html_content

def generate_social_variants(title, url, text):
    """
    Uses OpenRouter (GPT-4o-mini) to generate variants.
    """
    if not OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY not set. Using fallback dummy text.")
        return {
            "twitter": f"New post: {title} {url} #BuildInPublic #Python",
            "linkedin": f"I just published a new article on my blog about: {title}.\n\nCheck it out here: {url}"
        }

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    
    system_prompt = """You are a cynical but highly skilled DevOps/Infrastructure engineer who hates repetitive tasks. 
You run a blog called "Smart Infra Log". You are writing social media promotional copy for your latest blog post.

You must output exactly a JSON object with two keys:
"twitter": A short, punchy tweet (max 280 chars) summarizing the technical highlight, slightly self-deprecating, ending with the tags #BuildInPublic #Python. DO NOT append the URL.
"linkedin": A slightly longer, more professional but still authentic post abstracting the engineering philosophy behind the post, ending with the URL.

Do not wrap the JSON in markdown code blocks, just output the raw JSON."""

    user_prompt = f"Title: {title}\nURL: {url}\n\nArticle excerpt:\n{text}"

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        result_text = response.choices[0].message.content
        return json.loads(result_text)
    except Exception as e:
        print(f"Failed to generate social variants via OpenRouter: {e}")
        # Fallback
        return {
            "twitter": f"New post: {title} #BuildInPublic #Python",
            "linkedin": f"I just published a new article on my blog about: {title}.\n\nCheck it out here: {url}"
        }

def main():
    print(f"Fetching RSS feed from {RSS_URL} via rss2json...")
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={RSS_URL}"
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
    except Exception as e:
        print(f"Error fetching from rss2json: {e}")
        sys.exit(1)
        
    if data.get('status') != 'ok':
        print(f"Warning: rss2json returned an error: {data.get('message', 'Unknown')}")
        sys.exit(1)
        
    entries = data.get('items', [])
    if len(entries) == 0:
        print("Warning: Feed contains no entries.")
        sys.exit(1)
        
    posted_urls = load_posted_urls()
    new_entries = []
    
    for entry in reversed(entries):
        link = entry.get('link')
        title = entry.get('title')
        if link:
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
        
        # 1. Fetch text
        text_excerpt = fetch_article_text(url)
        html_content = fetch_article_html(url)
        
        # 1.5 Polish HTML
        print("Polishing article HTML with Claude...")
        polished_html = polish_article_with_claude(html_content)
        if not polished_html:
            polished_html = html_content # fallback
        
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
        
        # 5. Dispatch to Medium (RPA)
        print("Pushing to Medium (RPA)...")
        try:
            med_success = push_to_medium(url, title, polished_html)
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
