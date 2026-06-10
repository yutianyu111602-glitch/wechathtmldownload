#!/usr/bin/env python3
"""
yuanbao_bridge.py — PC 元宝桥接器 v2
=====================================
打通 wechat-article-exporter → opencli yuanbao → PC元宝桌面版 的通路。

用法:
  python yuanbao_bridge.py --url "https://mp.weixin.qq.com/s/xxx"
  python yuanbao_bridge.py --file article.html
  python yuanbao_bridge.py --text "文章内容..."
  python yuanbao_bridge.py --url "xxx" --think --timeout 180 --save-html

关键设计:
  - opencli yuanbao ask 会将换行符解释为"发送"(Enter键)
  - 因此所有多行文本必须先转换为单行（换行→" | "）
  - 每次调用前先 new 清空对话上下文
  - 深度思考模式用 --think 标志
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

# ── Config ───────────────────────────────────────────────────────
EXPORTER_BASE = "http://127.0.0.1:17300"
EXPORTER_API_KEY = os.environ.get(
    "WECHAT_EXPORTER_API_KEY",
    "ec9dd79cd6fb4ab49f6f1884be023640"
)
DOWNLOADS_DIR = Path("D:/downstream_results/stage7_rewrite/longrun/_yuanbao_bridge")


# ── HTML → clean text ────────────────────────────────────────────
class TextExtractor(HTMLParser):
    """Extract visible text from HTML, skipping scripts/styles."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, _):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip > 0:
            self.skip -= 1

    def handle_data(self, data):
        if self.skip == 0:
            s = data.strip()
            if s:
                self.parts.append(s)

    def get_text(self) -> str:
        return " ".join(self.parts)


def extract_text(html: str) -> str:
    """Extract clean article text from WeChat HTML."""
    ex = TextExtractor()
    ex.feed(html)
    raw = ex.get_text()
    # Remove CSS/JS noise lines
    lines = []
    for line in raw.split('\n'):
        s = line.strip()
        if not s or re.match(r'^[.#@]\w+[\s{].*[;}]', s):
            continue
        if re.match(r'^\w+\s*:\s*\d+px', s):
            continue
        lines.append(s)
    return ' '.join(lines)


def extract_image_urls(html: str) -> list:
    """Extract image URLs from WeChat article HTML."""
    urls = []
    # Match mmbiz.qpic.cn image URLs in src and data-src attributes
    for pattern in [
        r'data-src="(https?://mmbiz\.qpic\.cn/[^"]+)"',
        r'src="(https?://mmbiz\.qpic\.cn/[^"]+)"',
        r'data-src="(https?://mmecoa\.qpic\.cn/[^"]+)"',
        r'src="(https?://mmecoa\.qpic\.cn/[^"]+)"',
    ]:
        found = re.findall(pattern, html)
        urls.extend(found)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


# ── Exporter download ────────────────────────────────────────────
def download_article(url: str, timeout: int = 30) -> str:
    """Download WeChat article HTML via exporter API."""
    api = f"{EXPORTER_BASE}/api/public/v1/download?url={url}&format=html"
    req = Request(api, headers={"X-Auth-Key": EXPORTER_API_KEY})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except HTTPError as e:
        print(f"[error] Exporter HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"[error] Exporter unreachable: {e.reason}", file=sys.stderr)
        sys.exit(1)


# ── Prompt building ──────────────────────────────────────────────
def build_prompt(article_text: str, image_urls: list = None) -> str:
    """Build a single-line extraction prompt for yuanbao."""
    # Truncate if too long (yuanbao input has practical limits)
    text = article_text[:3000]

    # Replace newlines with ' | ' delimiter
    text = text.replace('\n', ' | ')

    img_part = ""
    if image_urls:
        img_urls_short = ' | '.join(image_urls[:8])
        img_part = f" | 图片URL(按序): {img_urls_short}"

    # Single-line prompt (no newlines! opencli interprets \n as Enter=send)
    prompt = (
        f'请从以下活动文中提取每场活动信息并输出纯净JSON(不要markdown代码块)。'
        f'{img_part}'
        f' | 文章内容: {text}'
        f' | 格式: {{"events":[{{"date":"YYYY-MM-DD","title":"","djs":[],"price":"","venue":"","poster_img_url":""}}]}}'
        f' | 无法确定的字段用 null'
        f' | 只输出JSON'
    )
    return prompt


# ── Yuanbao invocation ───────────────────────────────────────────
def find_opencli() -> str:
    """Locate the opencli executable."""
    opencli = os.path.expandvars(r"%APPDATA%\npm\opencli.cmd")
    if Path(opencli).exists():
        return opencli
    # Try PATH
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for ext in (".cmd", ".exe", ""):
            p = Path(d) / f"opencli{ext}"
            if p.exists():
                return str(p)
    return "opencli"  # last resort


def call_yuanbao(prompt: str, think: bool = False, timeout: int = 180) -> str:
    """Call opencli yuanbao ask (with new conversation) and return response."""
    opencli = find_opencli()

    # Step 1: New conversation to clear context
    print("[yuanbao] Starting new conversation...", file=sys.stderr)
    result = subprocess.run(
        [opencli, "yuanbao", "new"],
        capture_output=True, text=True, timeout=30,
        encoding='utf-8', errors='replace',
    )
    if result.returncode != 0:
        print(f"[yuanbao] WARNING: new failed (exit {result.returncode})", file=sys.stderr)

    time.sleep(1.5)  # Let browser settle

    # Step 2: Send prompt (as single line)
    cmd = [opencli, "yuanbao", "ask", prompt]
    if think:
        cmd.append("--think")
    cmd.extend(["--timeout", str(timeout)])

    print(f"[yuanbao] Sending prompt ({len(prompt)} chars)...", file=sys.stderr)
    result = subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=timeout + 30,
        encoding='utf-8', errors='replace',
    )
    if result.returncode != 0:
        print(f"[yuanbao] Exit code {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"[yuanbao] stderr: {result.stderr[:500]}", file=sys.stderr)

    return result.stdout.strip()


def parse_response(raw: str) -> dict:
    """Parse opencli yuanbao response, extracting structured JSON."""
    assistant_match = re.search(
        r'Role:\s*Assistant\s*\nText:\s*(.*)',
        raw, re.DOTALL | re.IGNORECASE
    )
    if not assistant_match:
        return {"error": "No assistant response found", "raw_response": raw[:500]}

    text = assistant_match.group(1).strip()

    # Try direct JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try as double-escaped JSON string (yuanbao wraps JSON inside a JSON string)
    try:
        inner = json.loads(text)  # parse outer string
        if isinstance(inner, str):
            return json.loads(inner)  # parse inner JSON
        return inner  # was an object directly
    except (json.JSONDecodeError, TypeError):
        pass

    # Try unescaping (yuanbao sometimes outputs \[ and \] which aren't valid JSON)
    try:
        unescaped = text.replace('\\"', '"').replace('\\\\', '\\').replace('\\[', '[').replace('\\]', ']')
        return json.loads(unescaped)
    except json.JSONDecodeError:
        pass

    # Match code block
    code_match = re.search(r'```(?:json)?\s*\n?(\{[\s\S]*?\})\n?```', text)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass

    # Match bare { ... "events" ... }
    json_match = re.search(r'\{[\s\S]*"events"[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return {"raw_response": text[:500], "error": "Could not parse JSON"}


# ── Main ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="PC 元宝桥接器 v2 — 微信公众号文章 → 结构化活动 JSON"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="微信公众号文章 URL")
    input_group.add_argument("--file", help="本地 HTML 文件路径")
    input_group.add_argument("--text", help="直接输入文章文本")

    parser.add_argument("--think", action="store_true", help="启用深度思考模式")
    parser.add_argument("--timeout", type=int, default=180, help="元宝超时(秒)")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--save-html", action="store_true", help="保存HTML")
    parser.add_argument("--dry-run", action="store_true", help="仅下载+提取，不调元宝")
    parser.add_argument("--no-new", action="store_true", help="不启动新对话(复用现有)")

    args = parser.parse_args()

    # ── Step 1: Get content ──
    if args.url:
        print(f"[bridge] Downloading: {args.url}", file=sys.stderr)
        html = download_article(args.url)
        if args.save_html:
            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            fname = DOWNLOADS_DIR / f"article_{ts}.html"
            fname.write_text(html, encoding='utf-8')
            print(f"[bridge] Saved: {fname}", file=sys.stderr)
    elif args.file:
        html = Path(args.file).read_text(encoding='utf-8', errors='ignore')
    else:
        html = None

    if html:
        text = extract_text(html)
        image_urls = extract_image_urls(html)
        print(f"[bridge] Text: {len(text)} chars, Images: {len(image_urls)}", file=sys.stderr)
    else:
        text = args.text
        image_urls = []

    if args.dry_run:
        print(f"\n--- Text (first 800 chars) ---\n{text[:800]}")
        if image_urls:
            print(f"\n--- Image URLs ---")
            for i, u in enumerate(image_urls[:5]):
                print(f"  [{i}] {u[:100]}")
        return

    # ── Step 2: Build prompt ──
    prompt = build_prompt(text, image_urls=image_urls if image_urls else None)
    print(f"[bridge] Prompt: {len(prompt)} chars", file=sys.stderr)

    # ── Step 3: Call yuanbao ──
    response = call_yuanbao(prompt, think=args.think, timeout=args.timeout)

    if not response:
        print(json.dumps({"error": "No response"}, ensure_ascii=False, indent=2))
        sys.exit(1)

    # ── Step 4: Parse & output ──
    if args.format == "text":
        print(response)
    else:
        result = parse_response(response)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
