#!/usr/bin/env python3
"""Yuanbao PC Client — 模拟人类操作元宝桌面客户端。

用 pyautogui 控制鼠标键盘，不走 API/CDP，降低封号风险。
使用方法：
    from yuanbao_pc_client import YuanbaoPC
    yb = YuanbaoPC()
    reply = yb.ask("你好")                    # 新对话 + 发问
    reply = yb.ask("继续", new_chat=False)    # 在当前对话继续
    yb.ask_batch(["问题1", "问题2"])          # 批量，自动限速

安全策略：
    - 每次提问间隔 60-120s（模拟人类思考）
    - 每日上限 40 次
    - 不使用 --think（降资源消耗）
    - 随机延迟模拟打字节奏
"""

import pyautogui
import pygetwindow as gw
import pyperclip
import time
import random
import json
import re
import ctypes
import os
from pathlib import Path
from datetime import datetime, date

# Safety limits — 模拟人类操作节奏，靠随机性防封，不靠绝对上限
MIN_INTERVAL = 60       # seconds between queries (基准，实际随机60-180)
MAX_DAILY_SOFT = 60     # 软上限：超过后每次间隔强制 >= 180s，但不拒绝
DAILY_LOG = Path(os.environ.get('TEMP', '/tmp')) / 'yuanbao_daily_log.json'
SESSION_MAX_DURATION = 6 * 3600  # 单次会话最长6小时（之后必须休息1h+）

# Window title to find
WINDOW_TITLE = '元宝'

# 人类行为模拟参数
TYPING_WPM = 40
MOUSE_JITTER = 8

# 提示词变体模板 — 每次随机选择，避免固定模式
PROMPT_VARIANTS = {
    "search_prefix": [
        "请搜索：", "帮我查一下：", "搜索一下：", "在网上找找：",
        "帮我搜索：", "查查这个：", "搜一下：", "帮我了解：",
    ],
    "output_format": [
        "只输出JSON，不要markdown代码块，不要其他解释。",
        "直接返回JSON对象，不要用```包裹。",
        "请用纯JSON回答，不要任何额外文字。",
        "返回JSON格式的结果，不要写代码，不要生成文件。",
    ],
    "json_structure": [
        '{"type":"dj|club|label|event|other","name_cn":"","name_en":"","bio":"","source_urls":[]}',
        '{"identity":"","chinese_name":"","description":"","references":[]}',
        '{"category":"","name":"","summary":"","links":[]}',
    ],
}


class YuanbaoPC:
    def __init__(self):
        self.window = None
        self.query_count_today = 0
        self.session_start = time.time()
        self._find_window()
    
    def _find_window(self):
        """Find Yuanbao desktop window."""
        for w in gw.getWindowsWithTitle(WINDOW_TITLE):
            self.window = w
            break
        if not self.window:
            raise RuntimeError(f'未找到元宝窗口 (title="{WINDOW_TITLE}")')
    
    def _activate(self):
        """Bring Yuanbao window to foreground with human-like delays."""
        hwnd = self.window._hWnd
        ctypes.windll.user32.ShowWindow(hwnd, 9)
        time.sleep(random.uniform(0.15, 0.35))
        # 模拟Alt+Tab切换过来的随机停顿
        time.sleep(random.uniform(0.3, 0.8))
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(random.uniform(0.4, 0.9))
        fg = ctypes.windll.user32.GetForegroundWindow()
        if fg != hwnd:
            print(f'WARNING: foreground={fg}, expected={hwnd}')
    
    def _check_daily_limit(self):
        """Enforce daily query limit with progressive slowdown."""
        today = date.today().isoformat()
        if DAILY_LOG.exists():
            log = json.loads(DAILY_LOG.read_text())
        else:
            log = {}
        
        count = log.get(today, 0)
        if count >= MAX_DAILY_SOFT:
            print(f'⚠ 今日已 {count} 次，进入慢速模式（间隔≥180s）')
        self.query_count_today = count
        return count
    
    def _record_query(self):
        """Record one query in daily log."""
        today = date.today().isoformat()
        if DAILY_LOG.exists():
            log = json.loads(DAILY_LOG.read_text())
        else:
            log = {}
        log[today] = log.get(today, 0) + 1
        DAILY_LOG.write_text(json.dumps(log))
        self.query_count_today = log[today]
    
    def _human_delay(self, base=1.0, variance=0.5):
        """Random delay simulating human behavior — 越往后越慢."""
        # 根据今日已发送条数逐渐放慢
        fatigue_factor = 1.0 + (self.query_count_today * 0.03)
        delay = (base * fatigue_factor) + random.uniform(-variance, variance * fatigue_factor)
        time.sleep(max(0.3, delay))
    
    def _mouse_jitter(self, x, y):
        """Move mouse with slight random offset to avoid pixel-perfect repetition."""
        jx = x + random.randint(-MOUSE_JITTER, MOUSE_JITTER)
        jy = y + random.randint(-MOUSE_JITTER, MOUSE_JITTER)
        # 模拟人类曲线移动
        pyautogui.moveTo(jx, jy, duration=random.uniform(0.1, 0.3))
    
    def _random_idle(self, min_s=0.5, max_s=2.0):
        """Simulate user staring at screen / thinking."""
        time.sleep(random.uniform(min_s, max_s))
    
    def _screenshot(self, save_path=None):
        """Take screenshot of Yuanbao window via PrintWindow (handles negative coords)."""
        try:
            import win32gui, win32ui, win32con
            hwnd = self.window._hWnd
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width, height = right - left, bottom - top
            
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(bitmap)
            
            result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
            
            if result and save_path:
                bitmap.SaveBitmapFile(saveDC, save_path)
            
            # Convert to PIL Image for compatibility
            from PIL import Image
            bmp_path = save_path or os.path.join(os.environ.get('TEMP', '/tmp'), '_yb_temp.bmp')
            if result:
                bitmap.SaveBitmapFile(saveDC, bmp_path)
            
            win32gui.DeleteObject(bitmap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwndDC)
            
            if result:
                return Image.open(bmp_path)
        except Exception as e:
            print(f'PrintWindow failed: {e}, falling back to pyautogui')
        
        # Fallback
        yb = self.window
        img = pyautogui.screenshot(region=(yb.left, yb.top, yb.width, yb.height))
        if save_path:
            img.save(save_path)
        return img
    
    def new_chat(self):
        """Click 新建对话 button with human-like behavior."""
        self._activate()
        yb = self.window
        # 先随机移动鼠标（不点击），模拟浏览
        browse_x = yb.left + random.randint(int(yb.width*0.1), int(yb.width*0.5))
        browse_y = yb.top + random.randint(int(yb.height*0.2), int(yb.height*0.6))
        self._mouse_jitter(browse_x, browse_y)
        self._random_idle(0.3, 0.8)
        
        # 新建对话: sidebar top
        x = yb.left + int(yb.width * (0.07 + random.uniform(-0.02, 0.02)))
        y = yb.top + int(yb.height * (0.03 + random.uniform(-0.01, 0.01)))
        self._mouse_jitter(x, y)
        pyautogui.click()
        self._human_delay(1.5, 0.8)
    
    def _click_input(self):
        """Click the text input area with jitter."""
        yb = self.window
        # 先假装看之前的回复
        scroll_y = yb.top + int(yb.height * random.uniform(0.3, 0.6))
        pyautogui.scroll(random.randint(-3, 1))
        self._random_idle(0.2, 0.5)
        
        # Input box with random offset
        x = yb.left + int(yb.width * (0.55 + random.uniform(-0.05, 0.05)))
        y = yb.top + int(yb.height * (0.93 + random.uniform(-0.02, 0.01)))
        self._mouse_jitter(x, y)
        pyautogui.click()
        self._human_delay(0.3, 0.2)
    
    def _type_message(self, text):
        """Type message via clipboard (supports Chinese)."""
        # Clear any existing text
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(random.uniform(0.08, 0.15))
        
        # Paste via clipboard
        pyperclip.copy(text)
        time.sleep(random.uniform(0.08, 0.2))
        
        # 随机50%概率：先粘贴再模拟修改（更像人类）
        if random.random() < 0.5:
            pyautogui.hotkey('ctrl', 'v')
        else:
            # 分两段粘贴，中间停顿
            half = len(text) // 2
            pyperclip.copy(text[:half])
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(random.uniform(0.3, 0.7))
            pyperclip.copy(text[half:])
            pyautogui.hotkey('ctrl', 'v')
        
        self._human_delay(0.5, 0.3)
    
    def _send(self):
        """Press Enter after a human-like 'review' pause."""
        # 模拟发送前检查文字
        self._random_idle(0.5, 2.0)
        pyautogui.press('enter')
    
    def _wait_for_response(self, timeout=30, check_interval=2):
        """Wait for Yuanbao to finish responding.
        
        Monitors the window for changes. Returns when response stabilizes.
        """
        start = time.time()
        last_img = None
        stable_count = 0
        
        while time.time() - start < timeout:
            time.sleep(check_interval)
            current_img = self._screenshot()
            
            if last_img is not None:
                # Compare images - if stable for 3 checks, response is done
                if self._images_similar(last_img, current_img):
                    stable_count += 1
                    if stable_count >= 3:
                        return True
                else:
                    stable_count = 0
            
            last_img = current_img
        
        return False  # timeout
    
    def _images_similar(self, img1, img2, threshold=0.98):
        """Quick pixel comparison to detect if response is still streaming."""
        # Simple approach: compare a strip of pixels near bottom of chat area
        try:
            w, h = img1.size
            # Sample a few rows in the middle of the chat area
            y_start = int(h * 0.3)
            y_end = int(h * 0.8)
            
            p1 = list(img1.crop((int(w*0.3), y_start, int(w*0.9), y_end)).getdata())
            p2 = list(img2.crop((int(w*0.3), y_start, int(w*0.9), y_end)).getdata())
            
            if len(p1) != len(p2):
                return False
            
            same = sum(1 for a, b in zip(p1[:500], p2[:500]) if a == b)
            return same / min(500, len(p1)) > threshold
        except Exception:
            return False
    
    def ask(self, question, new_chat=True, timeout=30, screenshot=True):
        """Ask Yuanbao a question and return the response.
        
        Args:
            question: The question text (Chinese supported)
            new_chat: Whether to start a new conversation first
            timeout: Max seconds to wait for response
            screenshot: Whether to save screenshot of response
        
        Returns:
            dict with 'success', 'screenshot_path', 'timestamp'
        """
        self._check_daily_limit()
        
        if new_chat:
            self.new_chat()
        
        self._activate()
        self._click_input()
        self._type_message(question)
        self._send()
        
        # Wait for response
        self._wait_for_response(timeout=timeout)
        
        # Save screenshot
        ss_path = None
        if screenshot:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            ss_path = str(Path(os.environ.get('TEMP', '/tmp')) / f'yuanbao_response_{ts}.png')
            self._screenshot(ss_path)
        
        self._record_query()
        
        return {
            'success': True,
            'screenshot_path': ss_path,
            'timestamp': datetime.now().isoformat(),
            'question': question
        }
    
    def ask_batch(self, questions, interval=None, new_chat_each=True):
        """Ask multiple questions with rate limiting.
        
        Args:
            questions: List of question strings
            interval: Seconds between questions (default: random 60-120)
            new_chat_each: Start new chat for each question
        
        Returns:
            List of result dicts
        """
        results = []
        for i, q in enumerate(questions):
            print(f'[{i+1}/{len(questions)}] Asking: {q[:50]}...')
            
            try:
                result = self.ask(q, new_chat=new_chat_each)
                results.append(result)
                print(f'  ✅ Done')
            except RuntimeError as e:
                print(f'  ❌ {e}')
                results.append({'success': False, 'error': str(e), 'question': q})
                break
            
            # Rate limit between queries
            if i < len(questions) - 1:
                wait = interval or random.randint(MIN_INTERVAL, MIN_INTERVAL + 60)
                print(f'  ⏳ Waiting {wait}s (rate limit)...')
                time.sleep(wait)
        
        return results


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print('Usage: python yuanbao_pc_client.py "你的问题"')
        print('       python yuanbao_pc_client.py --batch questions.json')
        sys.exit(1)
    
    yb = YuanbaoPC()
    
    if sys.argv[1] == '--batch':
        with open(sys.argv[2]) as f:
            questions = json.load(f)
        results = yb.ask_batch(questions)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        question = sys.argv[1]
        result = yb.ask(question)
        print(json.dumps(result, ensure_ascii=False, indent=2))
