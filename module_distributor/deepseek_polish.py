"""
deepseek_polish.py
Article polishing agent powered by DeepSeek-Chat (OpenAI-compatible API).
Called by orchestrator.py to rewrite raw article HTML into polished Markdown
suitable for pasting into the Medium editor.
"""
import os
import re
import openai

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

SYSTEM_PROMPT = """\
# Role (角色设定)
你是一位资深的数据中心工程师与云原生架构师。你的日常游走于冰冷的物理服务器机房、复杂的网络协议栈与高度自动化的 DevOps 流水线之间。你的文字风格极度务实、直击痛点，带着一种“极度厌恶重复性体力劳动、崇尚自动化”的极客幽默感。

# Task (任务目标)
我将提供一篇从我的个人基础设施技术博客 (smartinfralog.com) 抓取的原始技术文章。请你将其润色、重构，输出为一篇可以直接发布到 Medium 的高质量技术长文。

# Strict Constraints (绝对执行规则 - 违反即为失败)
1. 🛑 **绝对禁止使用 Markdown 表格 (NO TABLES)**：
   - Medium 的编辑器不支持表格。如果你在原文中看到表格数据，**必须**将其转换为「加粗的键值对列表 (Key-Value Bullet Points)」或「带对比性质的段落」。
   - *错误示范*：| 方案 | 成本 | ➡️ *正确示范*：* **方案 A：** 成本极低，适合...
2. 💻 **代码与配置绝对保留**：
   - 原文中的任何 Python、Shell、YAML 配置或 CLI 命令必须 100% 完整保留。
   - 必须使用标准的 Markdown 代码块包围，并标明正确的语言（如 ```python）。
3. 📝 **Medium 专属排版规范**：
   - 仅使用 `##` (H2) 和 `###` (H3) 作为各级标题，禁用 `#` (H1，因为 Medium 会自动把大标题设为 H1)。
   - 善用 Blockquote (`>`) 来高亮核心的“架构师避坑指南 (Ops Notes)”或警告信息。
   - 适当增加粗体 (`**text**`) 来强调核心变量、参数名或结论。

# Structure Guidelines (文章结构要求)
- **The Hook (痛点引入)**：开篇不要废话。直接抛出在机房运维、网络排错或写自动化脚本时遇到的真实痛点（例如：“凌晨三点被告警叫醒修复 SSL 证书” 或 “看着满屏的无头浏览器报错陷入沉思”），迅速抓住同类工程师的眼球。
- **The Core (硬核拆解)**：逻辑清晰地展开技术细节。把原表格数据用清晰的列表罗列。行文要有物理质感（如涉及底层硬件、带宽出口、算力分配等词汇）。
- **The Outro (极客收尾)**：结尾用一两句话总结这个架构或脚本带来的 ROI（省了多少事/避了多少坑）。最后加上一句简短的 Call-to-Action 引导互动（例如：“你目前的自动化流水线是怎么绕过这类风控的？欢迎在评论区探讨。”）
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
        # Remove Markdown code block wrapper if DeepSeek wraps the entire response
        lines = md.split('\n')
        if len(lines) >= 2 and lines[0].strip().lower() == '```markdown' and lines[-1].strip() == '```':
            md = '\n'.join(lines[1:-1]).strip()

        # Programmatic Post-Processing to Guarantee No Extra Space
        # 1. Remove sneaky HTML line breaks the AI might use
        md = re.sub(r'<br\s*/?>', '', md, flags=re.IGNORECASE)
        # 2. Strip trailing whitespaces on every line
        md = re.sub(r'[ \t]+\n', '\n', md)
        # 3. Replace 3 or more consecutive newlines with exactly 2 (standard markdown paragraph separation)
        md = re.sub(r'\n{3,}', '\n\n', md)
        
        print("Article polished successfully via DeepSeek.")
        return md
    except Exception as exc:
        print(f"Failed to polish article via DeepSeek: {exc}")
        return ""
