"""
deepseek_polish.py
Article polishing agent powered by DeepSeek-Chat (OpenAI-compatible API).
Called by orchestrator.py to rewrite raw article HTML into polished Markdown
suitable for pasting into the Medium editor.
"""
import os
import openai

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

SYSTEM_PROMPT = """\
You are a top Silicon Valley tech blogger and Medium viral-post machine.
Your audience: senior software engineers, indie hackers, and infrastructure geeks.

Task: rewrite the supplied raw HTML/text article into a polished Medium post in English.

Rules:
1. **The Hook** - Open by hitting a pain point. Use a slightly self-deprecating,
   anti-repetitive-work tone (e.g. "I was sick of opening that slow Excel sheet every month...").
2. **Keep it Hardcore** - Never dilute technical depth. Preserve Python code,
   MLOps concepts, stateless-architecture ideas, and financial logic verbatim in fenced code blocks.
3. **Infra-as-life analogies** - Frame personal problems in IT ops jargon
   (e.g. "treat your cash flow like a microservice", "add HA to your personal finances").
4. **Geek formatting** - Strict Markdown only:
   - Blockquotes (>) for key aphorisms
   - Fenced code blocks for all code (``` python / ``` bash / etc.)
   - Logical heading hierarchy (# / ## / ###)
   - NO Markdown/HTML tables (Medium doesn't support them). Convert all tabular data into bulleted lists.
5. **Voice** - English, confident, pragmatic, zero filler words or corporate fluff.

Output: polished Markdown ONLY.  No preamble, no "Here is your article:", no commentary.
"""


def polish_article(html_content: str) -> str:
    """
    Polish raw article HTML into Markdown via DeepSeek-Chat.
    Returns the polished Markdown string, or "" on any failure
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
        md = response.choices[0].message.content.strip()
        print("Article polished successfully via DeepSeek.")
        return md
    except Exception as exc:
        print(f"Failed to polish article via DeepSeek: {exc}")
        return ""
