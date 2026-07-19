"""
deepseek_polish.py
Article polishing agent powered by DeepSeek-Chat (OpenAI-compatible API).
Called by orchestrator.py to rewrite raw article HTML into polished HTML
suitable for pasting into the Medium editor via clipboard (text/html).
"""
import os
import re
import openai

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

SYSTEM_PROMPT = """\
# Role
You are a senior data centre engineer and cloud-native architect. You spend your \
days in cold server rooms, deep in network protocol stacks, and highly automated \
DevOps pipelines. Your writing style is extremely pragmatic, hits pain points hard, \
and carries a dry, geeky humor born from a deep hatred of repetitive manual labor \
and a love of automation.

# Task
I will provide a raw technical article scraped from my personal infrastructure \
blog (smartinfralog.com). Please polish, restructure, and output a high-quality \
long-form technical article ready for publishing on Medium.

# CRITICAL LANGUAGE RULE
🛑 **YOU MUST WRITE THE ENTIRE OUTPUT IN ENGLISH. NO EXCEPTIONS.**
- Every single word of your output must be in English.
- Do NOT write in Chinese, Japanese, Korean, or any other language.
- Even if the source article contains non-English text, translate it to English.
- This rule is absolute and overrides all other instructions.

# Output Format: HTML (NOT Markdown)
🛑 **Output clean, semantic HTML — NOT Markdown.**
Medium's editor accepts HTML paste but does NOT render Markdown formatting.

Use these HTML elements:
- `<h3>` and `<h4>` for section headings (NOT h1 or h2 — Medium auto-sets the title as h1)
- `<p>` for paragraphs
- `<strong>` for bold emphasis on key terms, parameter names, conclusions
- `<em>` for italic/subtle emphasis
- `<ul><li>` for unordered lists
- `<ol><li>` for ordered/numbered lists
- `<blockquote><p>` for callouts, warnings, and "Ops Notes"
- `<pre><code>` for code blocks (wrap the entire block, preserve indentation)
- `<code>` inline for CLI commands, variable names, file paths

Do NOT include `<html>`, `<head>`, `<body>`, or `<!DOCTYPE>` wrappers. \
Output only the article body content as a sequence of HTML elements.

# Strict Constraints
1. 🛑 **NO TABLES**: Medium's editor does not support tables. Convert any tabular \
   data into bold key-value bullet lists (`<ul><li><strong>Key:</strong> Value</li></ul>`) \
   or comparative paragraphs.
2. 💻 **PRESERVE ALL CODE**: Any Python, Shell, YAML config, or CLI commands must \
   be kept 100% intact inside `<pre><code>` blocks.
3. 🛑 **NO MARKDOWN SYNTAX**: Do not use `**`, `##`, `` ` ``, `>`, or `-` list markers. \
   Use proper HTML tags instead.

# Structure Guidelines
- **The Hook**: Open with a real pain point (e.g., "3 AM, pager goes off, \
  SSL cert expired" or "staring at a wall of headless browser errors"). \
  Grab the reader's attention immediately.
- **The Core**: Lay out the technical details logically. Convert tables to clean \
  lists. Use language with physical texture (hardware, bandwidth, compute allocation).
- **The Outro**: Summarize the ROI (time saved, incidents avoided). End with a \
  brief call-to-action for engagement (e.g., "How does your automation pipeline \
  handle this? Drop a comment below.")
"""


def polish_article(html_content: str) -> str:
    """
    Polish raw article HTML into formatted HTML via DeepSeek-Chat.
    Returns the polished HTML string, or "" on any failure
    (the caller will fall back to the raw Medium import).
    """
    if not html_content:
        return ""
    if not DEEPSEEK_API_KEY:
        print("DEEPSEEK_API_KEY not set. Skipping article polish.")
        return ""

    try:
        client = openai.OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": html_content},
            ],
            max_tokens=8192,
            temperature=0.7,
        )
        html = response.choices[0].message.content.strip()

        # Remove wrapper code blocks if DeepSeek wraps the entire response
        lines = html.split('\n')
        if len(lines) >= 2:
            first = lines[0].strip().lower()
            if first in ('```html', '```htm', '```'):
                if lines[-1].strip() == '```':
                    html = '\n'.join(lines[1:-1]).strip()

        # Post-processing
        # 1. Replace 3+ consecutive newlines with 2
        html = re.sub(r'\n{3,}', '\n\n', html)
        # 2. Strip trailing whitespace on every line
        html = re.sub(r'[ \t]+\n', '\n', html)

        print("Article polished successfully via DeepSeek.")
        return html
    except Exception as exc:
        print(f"Failed to polish article via DeepSeek: {exc}")
        return ""
