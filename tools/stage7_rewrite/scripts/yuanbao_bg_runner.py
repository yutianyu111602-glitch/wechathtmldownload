#!/usr/bin/env python3
"""
yuanbao_bg_runner.py — 元宝后台运行器
使用虚拟桌面隔离，不影响主桌面操作。

原理:
  - 创建/切换到一个独立虚拟桌面 (Desktop 2)
  - 把元宝窗口移到该桌面
  - 在新桌面上执行 pyautogui 自动化
  - 自动切回主桌面

用法:
  py yuanbao_bg_runner.py "请搜索：xxx"           # 单次查询
  py yuanbao_bg_runner.py --batch questions.json  # 批量
  py yuanbao_bg_runner.py --daemon                # 守护模式，从队列取任务
"""

import ctypes
import time
import random
import json
import sys
import os
import subprocess
import threading
from pathlib import Path
from datetime import datetime, date

# COM CLSID for VirtualDesktopManager
CLSID_VirtualDesktopManager = "{AA509086-5CA9-4C25-8F95-589D6C07BDFA}"
IID_IVirtualDesktopManager = "{A5CD92FF-29BE-454C-8D04-D82879FB3F1B}"

# ── Virtual Desktop helpers ────────────────────────────────────

class VirtualDesktop:
    """Manage Windows 10 virtual desktops via COM."""
    
    def __init__(self):
        try:
            import comtypes.client
            self.vdm = comtypes.client.CreateObject(
                CLSID_VirtualDesktopManager,
                interface=IID_IVirtualDesktopManager
            )
            self._available = True
        except Exception as e:
            print(f"[VD] COM not available: {e}", file=sys.stderr)
            print("[VD] Falling back to direct pyautogui mode", file=sys.stderr)
            self._available = False
    
    def move_window_to_current(self, hwnd):
        """Pin window to current virtual desktop."""
        if not self._available:
            return
        try:
            self.vdm.MoveWindowToDesktop(hwnd)
        except:
            pass
    
    def is_available(self):
        return self._available


def switch_virtual_desktop(direction='right'):
    """Switch virtual desktop via keyboard shortcut."""
    if direction == 'right':
        pyautogui.hotkey('win', 'ctrl', 'right')
    elif direction == 'left':
        pyautogui.hotkey('win', 'ctrl', 'left')
    time.sleep(0.5)


def new_virtual_desktop():
    """Create new virtual desktop."""
    pyautogui.hotkey('win', 'ctrl', 'd')
    time.sleep(0.8)


def move_window_to_desktop(hwnd, desktop_index=None):
    """Try to move window to a specific virtual desktop.
    
    Uses keyboard shortcut approach: 
    Win+Tab → context menu → Move to → pick desktop
    """
    # Note: full automation of "Move to desktop" is fragile
    # For now, we use the approach: create desktop, move window there via COM
    pass


# ── Safety limits ──────────────────────────────────────────────

MIN_INTERVAL = 90
MAX_DAILY = 30
DAILY_LOG = Path(os.environ.get('TEMP', '/tmp')) / 'yuanbao_daily_log.json'
WINDOW_TITLE = '元宝'


class YuanbaoBackground:
    """Run 元宝 automation in background virtual desktop."""
    
    def __init__(self, use_virtual_desktop=True):
        self.use_vd = use_virtual_desktop and VirtualDesktop().is_available()
        self.vd = VirtualDesktop() if use_virtual_desktop else None
        self.window = self._find_window()
        self.query_count = self._read_daily_count()
        
        if self.use_vd:
            print("[BG] 虚拟桌面模式已启用", file=sys.stderr)
        else:
            print("[BG] 直接模式（元宝在第二屏）", file=sys.stderr)
    
    def _find_window(self):
        import pygetwindow as gw
        for w in gw.getWindowsWithTitle(WINDOW_TITLE):
            return w
        raise RuntimeError(f'未找到元宝窗口')
    
    def _read_daily_count(self):
        today = date.today().isoformat()
        if DAILY_LOG.exists():
            log = json.loads(DAILY_LOG.read_text())
            return log.get(today, 0)
        return 0
    
    def _record_query(self):
        today = date.today().isoformat()
        if DAILY_LOG.exists():
            log = json.loads(DAILY_LOG.read_text())
        else:
            log = {}
        log[today] = log.get(today, 0) + 1
        DAILY_LOG.write_text(json.dumps(log))
        self.query_count = log[today]
    
    def _run_query(self, question: str, timeout: int = 60) -> dict:
        """Execute one query against 元宝.
        
        Steps:
        1. If virtual desktop: switch to isolated desktop
        2. Activate 元宝 window
        3. New chat → type → send → wait
        4. Screenshot response
        5. Switch back to main desktop
        """
        if self.query_count >= MAX_DAILY:
            raise RuntimeError(f'今日已达上限 {MAX_DAILY}')
        
        import pyautogui
        import pyperclip
        
        # ── Enter isolated environment ──
        if self.use_vd:
            new_virtual_desktop()
            # Move 元宝 to this desktop (via COM if available)
            if self.vd:
                self.vd.move_window_to_current(self.window._hWnd)
        
        try:
            yb = self.window
            hwnd = yb._hWnd
            
            # Ensure visible (not minimized)
            if ctypes.windll.user32.IsIconic(hwnd):
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                time.sleep(0.3)
            
            # Activate window (only needed on this desktop)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(random.uniform(0.3, 0.7))
            
            # ── New chat ──
            x = yb.left + int(yb.width * (0.07 + random.uniform(-0.02, 0.02)))
            y = yb.top + int(yb.height * (0.03 + random.uniform(-0.01, 0.01)))
            pyautogui.moveTo(x + random.randint(-5, 5), y + random.randint(-5, 5), 
                           duration=random.uniform(0.1, 0.3))
            pyautogui.click()
            time.sleep(random.uniform(1.0, 2.0))
            
            # ── Click input ──
            ix = yb.left + int(yb.width * (0.55 + random.uniform(-0.05, 0.05)))
            iy = yb.top + int(yb.height * (0.93 + random.uniform(-0.02, 0.01)))
            pyautogui.moveTo(ix + random.randint(-5, 5), iy + random.randint(-5, 5),
                           duration=random.uniform(0.1, 0.2))
            pyautogui.click()
            time.sleep(random.uniform(0.2, 0.4))
            
            # ── Type question ──
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.08)
            pyperclip.copy(question)
            time.sleep(random.uniform(0.05, 0.15))
            
            # 随机粘贴方式
            if random.random() < 0.4:
                half = len(question) // 2
                pyperclip.copy(question[:half])
                pyautogui.hotkey('ctrl', 'v')
                time.sleep(random.uniform(0.2, 0.5))
                pyperclip.copy(question[half:])
                pyautogui.hotkey('ctrl', 'v')
            else:
                pyautogui.hotkey('ctrl', 'v')
            
            # 发送前随机停顿（模拟检查文字）
            time.sleep(random.uniform(0.3, 1.5))
            
            # ── Send ──
            pyautogui.press('enter')
            
            # ── Wait for response ──
            # 简单等待，不像素检测（省资源）
            wait_time = min(timeout, 15 + len(question) * 0.5)
            time.sleep(wait_time)
            
            # ── Screenshot ──
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            ss_path = str(Path(os.environ.get('TEMP', '/tmp')) / f'yuanbao_bg_{ts}.png')
            img = pyautogui.screenshot(region=(yb.left, yb.top, yb.width, yb.height))
            img.save(ss_path)
            
            self._record_query()
            
            return {
                'success': True,
                'screenshot_path': ss_path,
                'timestamp': datetime.now().isoformat(),
                'question': question,
                'count_today': self.query_count,
            }
        
        finally:
            # ── Return to main desktop ──
            if self.use_vd:
                switch_virtual_desktop('left')
    
    def ask(self, question, timeout=60):
        """Public API: ask one question."""
        return self._run_query(question, timeout)
    
    def ask_batch(self, questions, interval=None):
        """Batch with rate limiting."""
        results = []
        for i, q in enumerate(questions):
            print(f'[{i+1}/{len(questions)}] {q[:60]}...', file=sys.stderr)
            try:
                result = self.ask(q)
                results.append(result)
                print(f'  ✅ #{result["count_today"]}/30', file=sys.stderr)
            except RuntimeError as e:
                print(f'  ❌ {e}', file=sys.stderr)
                results.append({'success': False, 'error': str(e), 'question': q})
                break
            
            if i < len(questions) - 1:
                wait = interval or random.randint(MIN_INTERVAL, MIN_INTERVAL + 60)
                print(f'  ⏳ {wait}s...', file=sys.stderr)
                time.sleep(wait)
        
        return results


# ── CLI ────────────────────────────────────────────────────────

if __name__ == '__main__':
    import pyautogui  # lazy import
    
    if len(sys.argv) < 2:
        print('Usage: py yuanbao_bg_runner.py "你的问题"')
        print('       py yuanbao_bg_runner.py --batch questions.json')
        print('       py yuanbao_bg_runner.py --daemon  # watch queue')
        sys.exit(1)
    
    runner = YuanbaoBackground(use_virtual_desktop=False)  # 先不用VD，验证基础功能
    
    if sys.argv[1] == '--batch' and len(sys.argv) > 2:
        with open(sys.argv[2], encoding='utf-8') as f:
            questions = json.load(f)
        results = runner.ask_batch(questions)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    
    elif sys.argv[1] == '--daemon':
        print('[daemon] Watching queue...', file=sys.stderr)
        # TODO: watch a queue file
        while True:
            time.sleep(60)
    
    else:
        question = sys.argv[1]
        result = runner.ask(question)
        print(json.dumps(result, ensure_ascii=False, indent=2))
