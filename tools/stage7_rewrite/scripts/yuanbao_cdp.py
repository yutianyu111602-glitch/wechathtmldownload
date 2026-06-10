#!/usr/bin/env python3
"""
yuanbao_cdp.py — 元宝 CDP 自动化（Playwright → Chrome → 元宝Web版）
  - 问题轮换（活动→DJ→俱乐部→循环）
  - 每次新对话（防幻觉上下文污染）
  - DeepSeek API 最终 JSON 整理
  - 拟人化随机节奏（防封号）

依赖: pip install playwright
前提: Chrome 已启动在 9224 端口，且已登录元宝
      chrome --remote-debugging-port=9224 --remote-allow-origins=*
              --user-data-dir="C:/Users/pc/AppData/Local/Temp/chrome-yuanbao-bot"

用法:
  from yuanbao_cdp import YuanbaoCDP
  yb = YuanbaoCDP()
  result = yb.ask("请搜索：Quarion 电子音乐 DJ")
  # → {"type": "DJ", "name": "...", "summary": "...", "sources": [...]}

  # 轮换模式
  results = yb.rotate_ask([
      ("event", {"url": "https://mp.weixin.qq.com/s/xxx"}),
      ("dj",    {"name": "MIIIA", "handles": ["miiia_shanghai"]}),
      ("club",  {"name": "OIL Club", "city": "深圳"}),
  ])
"""

from playwright.sync_api import sync_playwright
import time, random, json, re, sys
from pathlib import Path
from datetime import datetime, date
from typing import Optional

# ── Config ─────────────────────────────────────────────────
CDP_URL = "http://127.0.0.1:9224"
YOUR_HOME = "https://yuanbao.tencent.com/chat"

# 节奏控制（无硬上限，靠随机性）
MIN_INTERVAL = 60        # 最小间隔秒数
MAX_INTERVAL = 180       # 最大间隔秒数
SESSION_MAX_HOURS = 6    # 单次会话最长时间

# ── 提示词模板（v3: 固定schema + markdown表格备选，不再随机变体）──
#
# 关键改进（2026-06-09）:
#   1. 固定单一schema，不再随机变体 — 字段名统一，解析更稳定
#   2. JSON + markdown表格双格式指令 — 不强求纯JSON，元宝做不到
#   3. 强约束（每个字段必填、未知填"未知"、不再编造）— 减少噪点
#   4. 俱乐部加入 sound_system 音响系统字段
#   5. 提示词最后加 "不要生成文件/代码，直接文本回复" — 防artifact

_OUTPUT_RULES = (
    "输出规则:\n"
    "1. 优先JSON格式；如无法纯JSON，用Markdown表格（| 字段 | 值 |）\n"
    "2. 每个字段都必须填写，未知的填\"未知\"\n"
    "3. 数组字段（genres/aliases/source_urls等）用逗号分隔\n"
    "4. 不要编造任何信息，以搜索结果为依据\n"
    "5. 不要生成文件、不要写代码块，直接文字回复"
)

# ── 实体识别（DJ/俱乐部/厂牌/活动/其他）───────────────────

ENTITY_JSON_SCHEMA = (
    '{"type":"dj|club|label|event|other","name_cn":"","name_en":"",'
    '"nationality":"","city":"","genres":[],"summary":"","source_urls":[]}'
)

ENTITY_TABLE_TEMPLATE = (
    "| 字段 | 值 |\n"
    "|------|----|\n"
    "| 类型 | DJ/俱乐部/厂牌/活动/其他 |\n"
    "| 中文名 | |\n"
    "| 英文名 | |\n"
    "| 国籍 | |\n"
    "| 城市 | |\n"
    "| 音乐风格 | (genres) |\n"
    "| 简介 | 2-3句话 |\n"
    "| 来源链接 | |"
)

ENTITY_PROMPT_HEADER = (
    "你是电子音乐/夜生活场景数据库录入助手。请识别以下实体并返回信息。\n"
)

ENTITY_QUESTION_TEMPLATES = [
    '在电子音乐/地下俱乐部场景中，"{name}"是什么身份？请识别并提取详细信息。',
    '请搜索并识别电子音乐领域中"{name}"的身份（DJ、俱乐部、厂牌、还是其他）。',
]

# ── 微信文章活动提取 ──────────────────────────────────────

EVENT_JSON_SCHEMA = (
    '{"events":[{"title":"","date":"","venue":"","city":"",'
    '"lineup":[{"name":"","role":"headliner|support|b2b|guest"}],'
    '"ticket_price":"","description":"","source_url":""}]}'
)

EVENT_TABLE_TEMPLATE = (
    "| 字段 | 值 |\n"
    "|------|----|\n"
    "| 活动名称 | |\n"
    "| 日期 | YYYY-MM-DD |\n"
    "| 场地 | |\n"
    "| 城市 | |\n"
    "| 票价 | |\n"
    "| 演出阵容 | DJ名(角色), ... |\n"
    "| 简介 | |\n"
    "| 文章链接 | |"
)

EVENT_PROMPT_HEADER = (
    "你是电子音乐活动信息提取助手。请阅读以下微信公众号文章，提取所有活动详情。\n"
    "注意：一篇文章可能包含多个活动，请逐个提取。\n"
)

# ── DJ Bio 提取 ───────────────────────────────────────────

BIO_JSON_SCHEMA = (
    '{"name":"","name_cn":"","aliases":[],"nationality":"","genres":[],'
    '"city":"","resident_club":"","record_labels":[],"bio":"",'
    '"notable_performances":[],"source_urls":[]}'
)

BIO_TABLE_TEMPLATE = (
    "| 字段 | 值 |\n"
    "|------|----|\n"
    "| 艺名 | |\n"
    "| 中文名/本名 | |\n"
    "| 别名 | 逗号分隔 |\n"
    "| 国籍 | |\n"
    "| 音乐风格 | Techno, House... |\n"
    "| 所在城市 | |\n"
    "| 常驻俱乐部 | |\n"
    "| 所属厂牌 | 逗号分隔 |\n"
    "| 个人简介 | 2-3句话 |\n"
    "| 重要演出 | 场地 年份,... |\n"
    "| 来源链接 | |"
)

BIO_PROMPT_HEADER = (
    "你是电子音乐DJ资料库录入助手。请搜索并提取以下DJ的详细资料。\n"
)

# ── 俱乐部/场地识别（含音响系统）──────────────────────────

CLUB_JSON_SCHEMA = (
    '{"name":"","name_cn":"","city":"","address":"","capacity":"",'
    '"genre_focus":"","description":"",'
    '"sound_system":{"brand":"","model":"","type":"","description":""},'
    '"notable_events":[],"source_urls":[]}'
)

CLUB_TABLE_TEMPLATE = (
    "| 字段 | 值 |\n"
    "|------|----|\n"
    "| 场地名称 | |\n"
    "| 中文名 | |\n"
    "| 城市 | |\n"
    "| 地址 | |\n"
    "| 容量 | |\n"
    "| 音乐定位 | Techno/House/Experimental... |\n"
    "| 场地简介 | |\n"
    "| 🔊 音响品牌 | e.g. Funktion-One, L-Acoustics, Danley... |\n"
    "| 🔊 音响型号 | e.g. Resolution 2, K2... |\n"
    "| 🔊 音响类型 | 点声源/线阵列/定制/... |\n"
    "| 🔊 音响描述 | 配置细节和特色 |\n"
    "| 代表性活动 | 逗号分隔 |\n"
    "| 来源链接 | |"
)

CLUB_PROMPT_HEADER = (
    "你是电子音乐场地数据库录入助手。请搜索并提取以下俱乐部/场地的详细信息。\n"
    "特别注意：尽可能搜索该场地的音响系统信息（品牌、型号、配置）。\n"
    "如果搜索不到音响信息，在对应字段填\"未找到音响系统信息\"。\n"
)

CLUB_QUESTION_TEMPLATES = [
    '请搜索电子音乐俱乐部/场地"{name}"的详细信息，包括其音响系统配置。',
    '帮我了解地下电子音乐场地"{name}"。重点：音响系统是什么品牌型号？有什么特色？',
    '搜索"{name}"这个电子音乐场地，提取基本信息并特别关注音响设备配置。',
]


class YuanbaoCDP:
    """元宝 CDP 自动化客户端。"""

    def __init__(self, cdp_url: str = CDP_URL):
        self.cdp_url = cdp_url
        self._playwright = None
        self._browser = None
        self._page = None
        self.session_start = time.time()
        self.query_count = 0

    # ── 连接管理 ─────────────────────────────────────────

    def connect(self):
        """连接到 Chrome CDP，定位元宝页面。"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(self.cdp_url)
        self._page = self._find_or_create_page()
        self._ensure_ready()
        return self

    def _find_or_create_page(self):
        """找到或创建元宝页面。"""
        for ctx in self._browser.contexts:
            for page in ctx.pages:
                if "yuanbao" in page.url:
                    return page
        page = self._browser.contexts[0].new_page()
        page.goto(YOUR_HOME, timeout=20000)
        time.sleep(5)
        return page

    def _ensure_ready(self):
        """确保：深度思考=OFF, 联网搜索=ON。

        v5: 元宝 UI 更新 — "联网搜索" 已从独立 toggle 移入 "工具" 下拉菜单。
        需要先点击"工具"，再在弹出菜单中点击"联网搜索"。
        """
        editor = self._page.locator(".ql-editor")
        if editor.count() == 0:
            raise RuntimeError("元宝未登录或页面异常")

        # 0. 检测登录过期 (hyc-login-v2 浮层 + placeholder="请登录后输入内容")
        login_overlay = self._page.locator(".hyc-login-v2")
        if login_overlay.count() > 0:
            ph = self._page.evaluate("() => document.querySelector('.ql-editor')?.getAttribute('data-placeholder') || ''")
            if '登录' in ph:
                raise RuntimeError(
                    "元宝登录已过期，需要手动微信扫码重新登录。"
                    "请在 Chrome 窗口完成登录后重试。"
                )

        # 1. 深度思考 — 仍在工具栏直接可见
        deep = self._page.evaluate('''() => {
            for(const el of document.querySelectorAll('*')) {
                if (el.innerText?.trim() === '深度思考') {
                    return el.closest('[class*="active"]') !== null;
                }
            }
            return false;
        }''')
        if deep:
            self._page.evaluate('''() => {
                for(const el of document.querySelectorAll('*')) {
                    if (el.innerText?.trim() === '深度思考') { el.click(); return 'off'; }
                }
            }''')
            print("  🔧 深度思考 → OFF", file=sys.stderr)

        # 2. 联网搜索 — v5: 在"工具"下拉菜单中
        search_active = self._page.evaluate('''() => {
            // 先检查搜索是否已在激活态（可能有指示器）
            for(const el of document.querySelectorAll('[class*="SearchSwitch"]')) {
                if (el.closest('[class*="active"]') || el.classList.contains('active')) return true;
            }
            return false;
        }''')

        if not search_active:
            # 点击"工具"按钮
            self._page.evaluate('''() => {
                for(const el of document.querySelectorAll('*')) {
                    if (el.innerText?.trim() === '工具') { el.click(); return 'tools'; }
                }
            }''')
            self._random_pause(0.3, 0.6)
            # 在下拉菜单中点击"联网搜索"
            self._page.evaluate('''() => {
                for(const el of document.querySelectorAll('*')) {
                    const t = (el.innerText || '').trim();
                    if (t === '联网搜索' || t.includes('联网搜索')) {
                        el.click(); return 'search_on';
                    }
                }
            }''')
            print("  🔧 联网搜索 → ON", file=sys.stderr)
            self._random_pause(0.2, 0.4)

        return self

    def new_chat(self):
        """JavaScript 新建对话。"""
        self._page.evaluate('''() => {
            const icon = document.querySelector('.icon-yb-ic_newchat_20');
            if(icon) { icon.parentElement.click(); return; }
            const btns = document.querySelectorAll('*');
            for(const b of btns) {
                if(b.innerText?.trim() === '新建对话') { b.click(); return; }
            }
        }''')
        time.sleep(random.uniform(1.5, 3.0))

    # ── 查询 ─────────────────────────────────────────────

    def _human_type(self, text: str):
        """模拟人类输入：点击→随机停顿→粘贴→随机停顿→偶尔滚动。"""
        editor = self._page.locator(".ql-editor")
        
        # 先假装浏览之前的对话（偶尔滚一下）
        if random.random() < 0.3:
            self._page.mouse.wheel(0, random.randint(-200, 100))
            self._random_pause(0.3, 0.8)
        
        # 点击输入框（位置微调）
        editor.first.click()
        self._random_pause(0.3, 0.9)
        
        # 清空
        self._page.keyboard.press("Control+a")
        self._random_pause(0.05, 0.15)
        
        # 随机：有时分两段粘贴
        if random.random() < 0.35 and len(text) > 30:
            half = len(text) // 2
            editor.first.fill(text[:half])
            self._random_pause(0.3, 0.8)  # 模拟思考
            editor.first.fill(text)  # 填完整
        else:
            editor.first.fill(text)
        
        self._random_pause(0.4, 1.2)
        
        # 随机：发送前"检查"文字（无操作停顿）
        if random.random() < 0.4:
            self._random_pause(0.5, 2.0)

    def _random_pause(self, lo: float, hi: float):
        """拟人随机停顿。越后面越慢。"""
        fatigue = 1.0 + (self.query_count * 0.02)
        base = lo + random.random() * (hi - lo)
        time.sleep(base * fatigue)

    def _wait_for_response(self, timeout: int = 60) -> str:
        """等待元宝回复完成，返回最后一条AI回复的纯文本。
        
        v4 fix: 不再用 page.text_content("body") —— body 含大量 Next.js 数据，
        且超过一定长度会截断导致 JSON 缺闭合括号。
        改为只提取最后一条 .agent-chat__list__item--ai 的文本。
        """
        elapsed = 0
        interval = 3 + random.random() * 3
        last_text = ""
        stable = 0
        silence_after_stable = 0

        while elapsed < timeout:
            time.sleep(interval)
            elapsed += interval

            # 检查是否有 loading/streaming 指示器
            loading = self._page.locator(
                '[class*="loading"], [class*="streaming"], [class*="thinking"], '
                '[class*="generating"], [class*="typing"]'
            ).count()
            if loading > 0:
                stable = 0
                continue

            # v4: 只读最后一条 AI 回复，不读整个 body
            current = self._page.evaluate('''() => {
                const items = document.querySelectorAll('.agent-chat__list__item--ai');
                if (items.length === 0) return '';
                const last = items[items.length - 1];
                return last.textContent || '';
            }''') or ""

            if current == last_text:
                stable += 1
                if stable >= 2:
                    silence_after_stable += 1
                    if silence_after_stable >= 1:
                        break
            else:
                stable = 0
                silence_after_stable = 0
                last_text = current

        # 最终提取
        return self._page.evaluate('''() => {
            const items = document.querySelectorAll('.agent-chat__list__item--ai');
            if (items.length === 0) return '';
            return items[items.length - 1].textContent || '';
        }''') or ""

    def ask(
        self,
        question: str,
        new_chat: bool = True,
        timeout: int = 60,
        parse_json: bool = True,
    ) -> dict:
        """发送一个问题，等待回复，返回结构化结果。"""
        self._check_health()

        if new_chat:
            self.new_chat()
            self._random_pause(0.5, 1.5)

        self._human_type(question)
        
        # 发送前最后随机停顿
        self._random_pause(0.3, 1.0)
        
        self._page.keyboard.press("Enter")
        self.query_count += 1

        # 等待回复
        full_text = self._wait_for_response(timeout)

        result = {
            "success": True,
            "question": question,
            "response_text": full_text,
            "parsed_json": None,
            "sources": [],
            "timestamp": datetime.now().isoformat(),
        }

        if parse_json:
            result["parsed_json"] = self._extract_json(full_text)

        urls = re.findall(r"https?://[^\s\)\]】]+", full_text)
        result["sources"] = list(dict.fromkeys(urls))[:10]

        return result

    def _extract_json(self, text: str) -> Optional[dict]:
        """从回复中提取JSON对象。v3: 先试JSON，再试markdown表格。"""
        # 1. 尝试代码块中的JSON（支持多个代码块）
        code_matches = list(re.finditer(r"```(?:json)?\s*\n?(\{[\s\S]*?\})\n?```", text))
        for code_match in code_matches:
            try:
                parsed = json.loads(code_match.group(1))
                if self._score_json_candidate(code_match.group(1)) <= 0:
                    continue  # skip error/template code blocks
                # Merge with markdown table data
                table_data = self._parse_markdown_table(text)
                if table_data and isinstance(parsed, dict):
                    for k, v in parsed.items():
                        if k not in table_data or not table_data.get(k):
                            table_data[k] = v
                    return table_data
                return parsed
            except json.JSONDecodeError:
                continue

        # 2. 找独立的 { ... } 对象
        brace_depth = 0
        json_start = -1
        candidates = []
        for i, c in enumerate(text):
            if c == "{":
                if brace_depth == 0:
                    json_start = i
                brace_depth += 1
            elif c == "}":
                brace_depth -= 1
                if brace_depth == 0 and json_start >= 0:
                    candidates.append(text[json_start : i + 1])
                    json_start = -1

        # Handle unbalanced (e.g. page JSON cut off mid-stream)
        if brace_depth > 0 and json_start >= 0:
            # Try to find a natural endpoint: next } or end of text
            end = text.find("}", json_start)
            if end >= 0:
                candidates.append(text[json_start : end + 1])
            else:
                candidates.append(text[json_start:] + "}")

        # Score and try candidates (prefer rich over large)
        scored = [(self._score_json_candidate(c), c) for c in candidates]
        scored = [(s, c) for s, c in scored if s > 0]  # skip errors/templates
        scored.sort(key=lambda x: x[0], reverse=True)

        for score, cand in scored:
            try:
                parsed = json.loads(cand)
                # Merge with markdown table data if available (e.g. club info in table + sound_system in JSON)
                table_data = self._parse_markdown_table(text)
                if table_data and isinstance(parsed, dict):
                    # JSON sub-objects (like sound_system) merge into table data
                    for k, v in parsed.items():
                        if k not in table_data or not table_data.get(k):
                            table_data[k] = v
                    return table_data
                return parsed
            except json.JSONDecodeError:
                try:
                    fixed = self._fix_json(cand)
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    continue

        # 3. Fallback: markdown表格 → JSON
        return self._parse_markdown_table(text)

    def _score_json_candidate(self, json_str: str) -> int:
        """Score a JSON candidate string. Returns -1 for errors/templates, 0+ for real data."""
        # Valid fields we expect in any schema
        _VALID_FIELDS = {
            "name", "name_cn", "name_en", "city", "address", "capacity",
            "genre_focus", "description", "sound_system", "genres", "nationality",
            "type", "brand", "model", "events", "lineup", "artists", "title",
            "summary", "source_urls", "record_labels", "notable_performances",
            "aliases", "bio", "resident_club", "source_url", "event_name",
            "venue", "date", "ticket_price",
        }
        _ERROR_PATTERNS = ["无法提取", "无法搜索", "error", "不支持", "无法识别",
                           "pageProps", "buildId", "assetPrefix", "nextExport",
                           "isFallback", "scriptLoader", "query"]

        try:
            obj = json.loads(json_str)
        except json.JSONDecodeError:
            # Try fix first
            try:
                obj = json.loads(self._fix_json(json_str))
            except json.JSONDecodeError:
                return -1

        if not isinstance(obj, dict) or not obj:
            return -1

        # Check for error patterns in values
        all_vals = " ".join(str(v) for v in obj.values())
        for pat in _ERROR_PATTERNS:
            if pat in all_vals:
                return -1

        # Score by real (non-empty, non-unknown) fields
        score = 0
        for k, v in obj.items():
            if k not in _VALID_FIELDS:
                continue
            if v and v not in ("", [], "未知", None):
                if isinstance(v, dict):
                    score += sum(1 for sv in v.values() if sv and sv not in ("", "未知"))
                elif isinstance(v, list):
                    score += len(v)
                else:
                    score += 1
        return score

    def _fix_json(self, text: str) -> str:
        """修复常见JSON错误。"""
        # 单引号 → 双引号（小心不破坏字符串内部）
        fixed = text.replace("'", '"')
        # 移除尾逗号
        fixed = re.sub(r",\s*}", "}", fixed)
        fixed = re.sub(r",\s*]", "]", fixed)
        # 修复无引号的key
        fixed = re.sub(r'([{,])\s*(\w+)\s*:', r'\1"\2":', fixed)
        # 修复 ... 省略号
        fixed = re.sub(r'"\.\.\."', '""', fixed)
        fixed = re.sub(r',\s*\.\.\.', '', fixed)
        # 修复中文冒号
        fixed = re.sub(r'：', ':', fixed)
        return fixed

    def _parse_markdown_table(self, text: str) -> Optional[dict]:
        """从markdown表格提取结构化数据 → JSON。
        
        识别格式:
          | 字段 | 值 |
          |------|-----|
          | 类型 | DJ |
          | 中文名 | 某某 |
        
        注意：过滤模板占位值（如 "Techno/House/Experimental..."），
        优先取文本后半段的表格（元宝回复在页面下方）。
        """
        # 找到所有表格行
        all_tables = re.findall(
            r"\|([^|]+)\|([^|]+)\|",
            text
        )
        if not all_tables:
            return None

        # 模板值过滤
        _TPL_VALS = {
            "dj/俱乐部/厂牌/活动/其他", "techno/house/experimental...",
            "e.g. funktion-one, l-acoustics, danley...",
            "e.g. resolution 2, k2...", "点声源/线阵列/定制/...",
            "配置细节和特色", "逗号分隔", "场地 年份,...",
            "2-3句话", "yyyy-mm-dd", "dj名(角色), ...",
            "techno, house...", "(genres)",
        }
        
        # 跳过表头行和模板占位
        def _is_real_val(v: str) -> bool:
            v = v.strip().lower()
            if not v or v in ("", "|"):
                return False
            if v in _TPL_VALS:
                return False
            if v.startswith("e.g."):
                return False
            return True

        result = {}
        has_real_data = False
        
        for key_raw, val_raw in all_tables:
            key = key_raw.strip()
            val = val_raw.strip()
            
            # 跳过表头行
            if key in ("", "字段", "------", "---"):
                continue
            if key.startswith("-"):
                continue
            
            # 只取有实际值的行
            if not _is_real_val(val):
                continue
            
            has_real_data = True
            
            # 字段名清理
            key_clean = key.lower().replace(" ", "_").replace("🔊", "")
            key_clean = re.sub(r'[^a-z\u4e00-\u9fff_]', '', key_clean)
            
            # 数组字段：逗号分隔
            if any(k in key for k in ["风格", "genres", "genre", "厂牌", "labels", "label", 
                                        "来源", "source", "别名", "aliases", "演出", "events",
                                        "活动", "链接", "urls", "表现", "performances"]):
                items = [v.strip() for v in val.split(",") if v.strip() and v.strip() != "未知"]
                if items:
                    result[key_clean] = items

            elif any(sk in key for sk in ["音响品牌", "音响型号", "音响类型", "音响描述"]):
                # 收集音响系统字段
                ss = result.get("sound_system", {})
                if "品牌" in key:
                    ss["brand"] = val
                elif "型号" in key:
                    ss["model"] = val
                elif "类型" in key:
                    ss["type"] = val
                elif "描述" in key:
                    ss["description"] = val
                result["sound_system"] = ss

            elif any(k in key for k in ["简介", "描述", "bio", "summary", "description", "biography"]):
                result[key_clean] = val if val != "未知" else ""

            else:
                result[key_clean] = val if val != "未知" else ""

        return result if has_real_data and len(result) >= 2 else None

    def _check_health(self):
        """检查会话健康状态。"""
        elapsed = (time.time() - self.session_start) / 3600
        if elapsed > SESSION_MAX_HOURS:
            print(f"⚠ 会话已运行 {elapsed:.1f}h，建议休息后重启")

    # ── 批量 ─────────────────────────────────────────────

    def ask_batch(
        self,
        questions: list[str],
        interval: tuple = (MIN_INTERVAL, MAX_INTERVAL),
    ) -> list[dict]:
        """批量查询，自动随机间隔。

        Args:
            questions: 问题列表
            interval: (最小秒, 最大秒) 间隔范围
        """
        results = []
        for i, q in enumerate(questions):
            print(f"[{i+1}/{len(questions)}] {q[:60]}...", file=sys.stderr)

            try:
                result = self.ask(q)
                results.append(result)
                j = result.get("parsed_json")
                if j:
                    name = j.get("name") or j.get("name_cn") or j.get("event_name") or "?"
                    print(f"  ✅ → {name}", file=sys.stderr)
                else:
                    print(f"  ✅ (no JSON)", file=sys.stderr)
            except Exception as e:
                print(f"  ❌ {e}", file=sys.stderr)
                results.append({"success": False, "error": str(e), "question": q})

            if i < len(questions) - 1:
                wait = random.randint(*interval)
                # 越到后面越慢
                fatigue = 1.0 + (i * 0.05)
                wait = int(wait * fatigue)
                print(f"  ⏳ {wait}s...", file=sys.stderr)
                time.sleep(wait)

        return results

    # ── 轮换模式 ─────────────────────────────────────────

    def rotate_ask(
        self,
        tasks: list[tuple[str, dict]],
        interval: tuple = (MIN_INTERVAL, MAX_INTERVAL),
    ) -> list[dict]:
        """问题类型轮换：活动→DJ→俱乐部→循环，避免固定模式。

        Args:
            tasks: [("event", {"url":"..."}), ("dj",{"name":"..."}), ("club",{"name":"..."})]
            interval: (最小秒, 最大秒) 间隔范围
        """
        results = []
        type_count = {"event": 0, "dj": 0, "club": 0}

        for i, (task_type, params) in enumerate(tasks):
            t = task_type
            type_count[t] = type_count.get(t, 0) + 1
            label = f"{t}#{type_count[t]}"

            print(f"\n[{i+1}/{len(tasks)}] {label}", file=sys.stderr)

            try:
                if t == "event":
                    result = self.extract_wechat_article(params["url"])
                elif t == "dj":
                    result = self.extract_dj_bio(
                        params["name"],
                        wechat_urls=params.get("wechat_urls"),
                    )
                elif t == "club":
                    result = self.identify_club(
                        params["name"],
                        city=params.get("city"),
                    )
                else:
                    result = self.ask(params.get("question", str(params)))

                result["task_type"] = t
                results.append(result)

                j = result.get("parsed_json")
                if j:
                    preview = j.get("name") or j.get("name_cn") or j.get("event_name") or "?"
                    print(f"  ✅ {preview}", file=sys.stderr)
                else:
                    print(f"  ✅ (no JSON parsed)", file=sys.stderr)

            except Exception as e:
                print(f"  ❌ {e}", file=sys.stderr)
                results.append({
                    "success": False, "error": str(e),
                    "task_type": t, "params": params,
                })

            if i < len(tasks) - 1:
                wait = random.randint(*interval)
                fatigue = 1.0 + (i * 0.05)
                wait = int(wait * fatigue)
                # 额外：连续同类型时多加休息
                if i >= 2 and tasks[i-1][0] == t and tasks[i-2][0] == t:
                    wait += random.randint(30, 90)
                print(f"  ⏳ {wait}s...", file=sys.stderr)
                time.sleep(wait)

        return results

    # ── 便捷方法 ─────────────────────────────────────────

    def identify_entity(self, name: str, handles: list[str] = None) -> dict:
        """识别一个实体（DJ/CLUB/LABEL等）。"""
        handle_str = f"（相关账号：{', '.join(handles)}）" if handles else ""
        
        question = random.choice(ENTITY_QUESTION_TEMPLATES).format(name=name)
        if handle_str:
            question += f" {handle_str}"
        
        prompt = (
            f"{ENTITY_PROMPT_HEADER}\n"
            f"{question}\n\n"
            f"JSON格式: {ENTITY_JSON_SCHEMA}\n\n"
            f"表格格式（如JSON不可行）:\n{ENTITY_TABLE_TEMPLATE}\n\n"
            f"{_OUTPUT_RULES}"
        )
        return self.ask(prompt)

    def extract_wechat_article(self, url: str) -> dict:
        """提取微信公众号文章的活动信息。"""
        prompt = (
            f"{EVENT_PROMPT_HEADER}\n"
            f"文章链接: {url}\n\n"
            f"JSON格式: {EVENT_JSON_SCHEMA}\n\n"
            f"表格格式（如JSON不可行，每个活动一个表）:\n{EVENT_TABLE_TEMPLATE}\n\n"
            f"{_OUTPUT_RULES}"
        )
        return self.ask(prompt)

    def extract_dj_bio(self, name: str, wechat_urls: list[str] = None) -> dict:
        """提取DJ的详细Bio。必须提供微信文章URL以提高准确度。"""
        if not wechat_urls:
            print(f"⚠ extract_dj_bio: 未提供微信文章URL，{name} 的结果可能不准确", file=sys.stderr)

        urls_part = f"优先参考以下微信文章: {' '.join(wechat_urls)}" if wechat_urls else ""

        prompt = (
            f"{BIO_PROMPT_HEADER}\n"
            f"DJ名称: {name}\n"
            f"{urls_part}\n\n"
            f"JSON格式: {BIO_JSON_SCHEMA}\n\n"
            f"表格格式（如JSON不可行）:\n{BIO_TABLE_TEMPLATE}\n\n"
            f"{_OUTPUT_RULES}"
        )
        return self.ask(prompt, timeout=90)

    def identify_club(self, name: str, city: str = None) -> dict:
        """识别俱乐部/场地信息（含音响系统）。"""
        city_str = f"（{city}）" if city else ""
        
        question = random.choice(CLUB_QUESTION_TEMPLATES).format(name=f'{name}{city_str}')
        
        prompt = (
            f"{CLUB_PROMPT_HEADER}\n"
            f"{question}\n\n"
            f"JSON格式: {CLUB_JSON_SCHEMA}\n\n"
            f"表格格式（如JSON不可行）:\n{CLUB_TABLE_TEMPLATE}\n\n"
            f"{_OUTPUT_RULES}"
        )
        return self.ask(prompt, timeout=90)

    # ── DeepSeek 后处理 ────────────────────────────────────

    def normalize_with_deepseek(
        self,
        raw_json: dict,
        schema_type: str = "entity",
        api_key: str = None,
    ) -> dict:
        """用 DeepSeek API 整理/验证元宝返回的 JSON。

        元宝有时输出不稳定（字段名不一致、嵌套错误），
        DeepSeek 做最终规范化，确保字段统一。

        Args:
            raw_json: 元宝返回的原始 parsed_json
            schema_type: "entity" | "event" | "bio" | "club"
            api_key: DeepSeek API key（默认从 DEEPSEEK_API_KEY 环境变量取）
        """
        import os as _os
        key = api_key or _os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            return raw_json  # 无 key 则跳过

        schemas = {
            "entity": ENTITY_JSON_SCHEMA,
            "event": EVENT_JSON_SCHEMA,
            "bio": BIO_JSON_SCHEMA,
            "club": CLUB_JSON_SCHEMA,
        }

        target = schemas.get(schema_type, schemas["entity"])
        
        prompt = (
            f"请将以下非结构化数据整理成标准JSON格式。\n"
            f"目标Schema: {target}\n"
            f"原始数据: {json.dumps(raw_json, ensure_ascii=False)}\n"
            f"规则: 1)字段名映射到schema 2)缺失字段填null 3)不编造信息 4)只输出JSON"
        )

        try:
            import requests as _r
            resp = _r.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 1024,
                },
                timeout=20,
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # 提取JSON
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            print(f"DeepSeek normalize failed: {e}", file=sys.stderr)

        return raw_json  # fallback

    # ── 清理 ─────────────────────────────────────────────

    def close(self):
        """断开连接（不关闭浏览器）。"""
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def __enter__(self):
        return self.connect()

    def __exit__(self, *args):
        self.close()


# ── CLI ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  py yuanbao_cdp.py '请搜索：Quarion 电子音乐 DJ'")
        print("  py yuanbao_cdp.py --entity 'MIIIA' --handles miiia_shanghai")
        print("  py yuanbao_cdp.py --wechat 'https://mp.weixin.qq.com/s/xxx'")
        print("  py yuanbao_cdp.py --bio 'Kun' --urls url1 url2")
        print("  py yuanbao_cdp.py --batch questions.json")
        sys.exit(1)

    with YuanbaoCDP() as yb:
        if sys.argv[1] == "--entity":
            name = sys.argv[2]
            handles = sys.argv[3:] if len(sys.argv) > 3 else None
            result = yb.identify_entity(name, handles)
        elif sys.argv[1] == "--wechat":
            result = yb.extract_wechat_article(sys.argv[2])
        elif sys.argv[1] == "--bio":
            name = sys.argv[2]
            urls = sys.argv[3:] if len(sys.argv) > 3 else None
            result = yb.extract_dj_bio(name, urls)
        elif sys.argv[1] == "--batch":
            with open(sys.argv[2], encoding="utf-8") as f:
                questions = json.load(f)
            results = yb.ask_batch(questions)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            sys.exit(0)
        else:
            result = yb.ask(" ".join(sys.argv[1:]))

        print(json.dumps(result, ensure_ascii=False, indent=2))
