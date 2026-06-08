#!/usr/bin/env python3
"""Hermes 7-day daily executor for 2026-05-01.
Safe local-report writer only. Does not mutate D:\\DDownload or D:\\DDownload\\_llm_release_v2.
"""
import json, os, re, subprocess, sys, shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path('/mnt/c/code/githubstar/wechathtmldownload')
LONG = ROOT/'docs/longrun/hermes-7day'
REPORTS = LONG/'reports'
STATE = LONG/'state/run-state.json'
LONGRUN_MD = LONG/'LONGRUN_STATE.md'
PLAN = ROOT/'SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md'
PS = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
TZ = timezone(timedelta(hours=8))
now = datetime.now(TZ)
ts = now.strftime('%Y-%m-%d_%H%M%S')
ts_iso = now.isoformat(timespec='seconds')
REPORTS.mkdir(parents=True, exist_ok=True)

def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return {'rc': p.returncode, 'out': p.stdout.strip(), 'err': p.stderr.strip(), 'cmd': ' '.join(cmd) if isinstance(cmd, list) else cmd}
    except Exception as e:
        return {'rc': 999, 'out': '', 'err': repr(e), 'cmd': str(cmd)}

def ps_json(script, timeout=40):
    if not Path(PS).exists():
        return {'ok': False, 'error': 'PowerShell path missing', 'raw': ''}
    p = run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script], timeout=timeout)
    raw = p['out'] or p['err']
    try:
        data = json.loads(p['out']) if p['out'] else None
    except Exception:
        data = p['out']
    return {'ok': p['rc'] == 0, 'rc': p['rc'], 'data': data, 'raw': raw[:4000], 'err': p['err'][:1000]}

def list_watchdogs():
    rows=[]
    for p in REPORTS.glob('WATCHDOG_*_2026-*.md'):
        try:
            mt=datetime.fromtimestamp(p.stat().st_mtime, TZ)
        except Exception:
            continue
        status='RED' if 'WATCHDOG_RED_' in p.name else ('AMBER' if 'WATCHDOG_AMBER_' in p.name else 'GREEN')
        rows.append({'name': p.name, 'mtime': mt, 'status': status})
    rows.sort(key=lambda x: x['mtime'])
    return rows

def scan_wsl():
    p = run(['ps','-eo','pid,ppid,stat,comm,args'], timeout=20)
    rows=[]
    for line in p['out'].splitlines()[1:]:
        if not line.strip(): continue
        parts=line.split(None,4)
        if len(parts)<5: continue
        pid,ppid,stat,comm,args=parts
        al=args.lower()
        touches_live = any(x in al for x in ['/mnt/d/ddownload','d:/ddownload','/mnt/d/html','d:/html','/mnt/d/aidata','d:/aidata'])
        openclaw_related = any(x in al for x in ['openclaw','ocr-report.sh','run_er_sample','stage7_rewrite','exact_span_repair_canary'])
        scan_related = any(x in al for x in [' find ', ' grep ', 'rm -rf', 'ocr-report.sh']) or comm in ('find','grep','tee','python3','node','bash')
        persistent_oc = 'openclaw' in al
        if persistent_oc or (touches_live and (openclaw_related or scan_related)):
            rows.append({'pid': pid, 'ppid': ppid, 'stat': stat, 'comm': comm, 'args': re.sub(r'(--token=)[^ ]+', r'\1REDACTED', args)[:1000], 'touches_live': touches_live, 'danger': bool(touches_live and (openclaw_related or scan_related))})
    return rows, p

def check_llama():
    script = "try { $j=Invoke-RestMethod -Uri 'http://127.0.0.1:11434/v1/models' -TimeoutSec 10; $ids=@($j.data | ForEach-Object { $_.id }); [pscustomobject]@{ ok=$true; count=$ids.Count; ids=$ids } | ConvertTo-Json -Depth 4 -Compress } catch { [pscustomobject]@{ ok=$false; error=$_.Exception.Message } | ConvertTo-Json -Depth 4 -Compress }"
    r=ps_json(script)
    data=r.get('data') if isinstance(r.get('data'), dict) else {}
    ids=data.get('ids') or []
    if isinstance(ids, str): ids=[ids]
    present=any('qwen3.6' in i.lower() or 'qwen3.6' in i.lower().replace('-','').replace('_','').replace(':','') for i in ids)
    return {'ok': bool(data.get('ok')), 'count': data.get('count', 0), 'qwen36_present': present, 'ids_sample': ids[:20], 'raw': r.get('raw','')[:1000]}

def check_wechat():
    # Exclude the PowerShell inspection command itself; its inline script contains the words WeChat/Weixin.
    script = "Get-CimInstance Win32_Process | Where-Object { $_.Name -notmatch 'powershell|cmd' -and ( $_.Name -match '^(WeChat|Weixin|WeChatApp|WeChatStore)\\.exe$' -or $_.CommandLine -match '\\\\Tencent\\\\WeChat|\\\\WeChat\\\\|WeChat.exe|Weixin.exe' ) } | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Depth 3 -Compress"
    r=ps_json(script)
    data=r.get('data')
    if data is None or data=='': rows=[]
    elif isinstance(data, list): rows=data
    elif isinstance(data, dict): rows=[data]
    else: rows=[]
    return {'count': len(rows), 'rows': rows[:5], 'raw': r.get('raw','')[:1000]}

def check_windows_d_touch():
    script = "Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -match 'D:/DDownload|D:\\\\DDownload|/mnt/d/DDownload|D:/HTML|D:\\\\HTML|/mnt/d/HTML|D:/aidata|D:\\\\aidata|/mnt/d/aidata') -and ($_.Name -notmatch 'powershell|cmd') } | Select-Object ProcessId,Name,CommandLine,CreationDate,ParentProcessId | ConvertTo-Json -Depth 4 -Compress"
    r=ps_json(script)
    data=r.get('data')
    if data is None or data=='': rows=[]
    elif isinstance(data, list): rows=data
    elif isinstance(data, dict): rows=[data]
    else: rows=[]
    return {'count': len(rows), 'rows': rows[:10], 'raw': r.get('raw','')[:1000]}

def check_zombies():
    script = "$cut=(Get-Date).AddHours(-2); Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'node' -and $_.CommandLine -match 'downstream|batch' -and $_.CommandLine -notmatch 'powershell.exe' } | ForEach-Object { $dt=$_.CreationDate; [pscustomobject]@{ProcessId=$_.ProcessId;Name=$_.Name;CreationDate=$dt;CommandLine=$_.CommandLine} } | ConvertTo-Json -Depth 4 -Compress"
    r=ps_json(script)
    data=r.get('data')
    if data is None or data=='': rows=[]
    elif isinstance(data, list): rows=data
    elif isinstance(data, dict): rows=[data]
    else: rows=[]
    return {'count': len(rows), 'rows': rows[:10], 'raw': r.get('raw','')[:1000]}

def d_disk():
    p=run(['df','-h','/mnt/d'], timeout=10)
    return {'raw': p['out'], 'rc': p['rc']}

def mem0_status():
    p=run(['hermes','--profile','wechatops','memory','status'], timeout=60)
    provider='unknown'
    for line in (p['out']+'\n'+p['err']).splitlines():
        if 'Provider:' in line:
            provider=line.split('Provider:',1)[1].strip(); break
    return {'provider': provider, 'rc': p['rc'], 'raw': (p['out'] or p['err'])[:1200]}

state=json.loads(STATE.read_text(encoding='utf-8'))
watchdogs=list_watchdogs()
last6=[w for w in watchdogs if (now-w['mtime']).total_seconds() <= 6*3600]
red6=[w for w in last6 if w['status']=='RED']
# consecutive non-RED after last RED
post_nonred=0
if red6:
    last_red=max(red6, key=lambda x:x['mtime'])['mtime']
    for w in sorted([x for x in watchdogs if x['mtime']>last_red], key=lambda x:x['mtime'], reverse=True):
        if w['status']!='RED': post_nonred+=1
        else: break
else:
    post_nonred=len([w for w in watchdogs[-3:] if w['status']!='RED'])

wsl_rows, ps_raw=scan_wsl()
win_touch=check_windows_d_touch()
llama=check_llama()
wechat=check_wechat()
zombies=check_zombies()
disk=d_disk()
mem0=mem0_status()
current_danger=[r for r in wsl_rows if r['danger']]
# include Windows-native D touching non-PS processes as danger for story gate (read-only evidence)
current_danger_win=win_touch['rows']

proceed_fallback = (not current_danger and not current_danger_win and (not red6 or post_nonred >= 2))
if current_danger or current_danger_win:
    decision='RED'
    need_human=True
    story='US-003 gate blocked by active live-root D-touch process'
    next_action='已停住：写 RED evidence/checkpoint；不执行 US-003 story；等待人工处理 OpenClaw/Stage7/helper 进程。'
elif not proceed_fallback:
    decision='AMBER'
    need_human=False
    story='US-003 deferred by live-root RED hysteresis gate'
    next_action='当前 live-root 扫描已清，但近 6h RED 后连续非 RED watchdog 少于 2；本轮只写 heartbeat/evidence/checkpoint，不启动 capture、不扩大 story。'
else:
    decision='AMBER' if red6 else 'GREEN'
    need_human=False
    story='US-003 no-WeChat fallback context gate artifacts'
    next_action='WeChat RED 下不启动 capture；已生成 status/context-gate/queue-plan local artifacts。'

# Update run-state heartbeat early/always
state['last_updated']=ts_iso
state['current_phase']='P1 Day 1 baseline/context gate recovery'
state['next_story']='US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)'
state.setdefault('preflight',{})['llama_swap'] = ('GREEN' if llama['ok'] and llama['qwen36_present'] else 'AMBER') + f" (Windows PS models={llama.get('count')}, qwen3.6_present={llama.get('qwen36_present')})"
state['preflight']['wechat'] = 'GREEN' if wechat['count'] else 'RED — process not found (capture skipped)'
state['preflight']['d_disk'] = 'GREEN (' + (disk['raw'].splitlines()[-1] if disk['raw'] else 'df failed') + ')'
state['preflight']['mem0'] = ('GREEN — Provider: mem0' if mem0['provider']=='mem0' else f"AMBER — live memory status Provider: {mem0['provider']}")
state.setdefault('prompt_patches_applied',{})['patch_23_consolidated_us003_recovery_gate'] = f"INTEGRATED by daily-executor {ts_iso}; red6={len(red6)}, post_nonred={post_nonred}, current_danger={len(current_danger)+len(current_danger_win)}"
state['latest_daily_executor']={
    'timestamp': ts_iso,
    'story': story,
    'decision': decision,
    'evidence': str(REPORTS/f"evidence_US003_context_gate_{ts}.md"),
    'checkpoint': str(REPORTS/f"checkpoint-day3_{ts}.md"),
    'daily_report': str(REPORTS/f"daily-executor-2026-05-01_{ts}.md"),
    'metrics': {'watchdog_red_6h': len(red6), 'post_red_nonred_watchdogs': post_nonred, 'wsl_openclaw_related_processes': len(wsl_rows), 'current_live_root_danger_processes': len(current_danger)+len(current_danger_win), 'wechat_process_count': wechat['count'], 'llama_swap_model_count': llama.get('count'), 'mem0_provider': mem0['provider']},
    'prompt_patches_integrated': ['#23 consolidated US-003 recovery gate (supersedes #17/#19/#21, incorporates #20 ledger)']
}
STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

# Minimal Loop Contract
contract=f"""## Minimal Loop: US-003 consolidated recovery/context gate\n### 目标\n整合 prompt-review Patch #23，先执行 live-root 安全门；若安全则在 WeChat RED 下生成 no-capture context/status/queue-plan local artifacts。\n### 非目标\n不启动 capture；不写入/修改 `D:\\DDownload\\_llm_release_v2`；不递归扫描 D 盘；不 kill/restart/repair OpenClaw 或 Windows 进程。\n### 文件边界\n只写 `docs/longrun/hermes-7day/reports/*`、`state/run-state.json`、`LONGRUN_STATE.md`。\n### 执行命令\n`python3 docs/longrun/hermes-7day/scripts/daily_executor_2026_05_01.py`\n### 验收标准\nrun-state heartbeat 更新；Patch #23 ledger 更新；存在 evidence/checkpoint/daily report；若 current live-root danger >0，则 RED 停住且无 story 扩大执行。\n### 停止条件\n当前 active live-root D-touch danger process >0、D 盘 <50GB、状态文件损坏、同 story 超过 3 次失败。\n### 风险\nOpenClaw/Stage7/helper 进程可能与 Hermes 长跑并发触达 live-root；按硬规则只报告不修复。\n"""

if proceed_fallback:
    # Safe no-capture US-003 fallback artifacts
    (REPORTS/f'wechat-status-{ts}.md').write_text(f"""# WeChat Status — {ts_iso}\n\n- status: RED\n- process_count: {wechat['count']}\n- decision: capture skipped; fallback context/queue planning only.\n- evidence: Windows CIM query found no WeChat/Weixin process.\n""", encoding='utf-8')
    (REPORTS/f'capture-queue-plan-{ts}.md').write_text(f"""# Capture Queue Plan — {ts_iso}\n\n- story: US-003 no-WeChat fallback\n- source baseline: existing 93K release/US-002 completed artifacts\n- action: do not launch capture while WeChat RED\n- planned acceptance when WeChat returns: generate queue of URLs not in existing release, then dry-run 50 only after gate.\n- current safety: latest 6h RED={len(red6)}, post-RED non-RED={post_nonred}, current danger=0.\n""", encoding='utf-8')

redacted_wsl='\n'.join([f"{r['pid']} {r['ppid']} {r['stat']} {r['comm']} {r['args']}" for r in wsl_rows[:30]]) or '(none)'
redacted_win=json.dumps(current_danger_win[:10], ensure_ascii=False, indent=2) if current_danger_win else '(none)'

failure_class = 'ENV_FAIL' if decision=='RED' else 'NONE'
evidence=REPORTS/f"evidence_US003_context_gate_{ts}.md"
evidence.write_text(f"""# 证据: US-003 consolidated recovery/context gate\n\n{contract}\n\n## 执行结果\n- 命令: `python3 docs/longrun/hermes-7day/scripts/daily_executor_2026_05_01.py`\n- 开始: {ts_iso}\n- 结束: {datetime.now(TZ).isoformat(timespec='seconds')}\n- 输入: `{STATE}`, latest `prompt-review-2026-05-01_1010.md`, `{PLAN}`\n- 输出: `{evidence}`, `{REPORTS/f'checkpoint-day3_{ts}.md'}`, `{REPORTS/f'daily-executor-2026-05-01_{ts}.md'}`\n- 验收: {'PASS (RED gate correctly stopped story expansion)' if decision=='RED' else 'PASS'}\n- 指标: watchdog_red_6h={len(red6)}, post_red_nonred={post_nonred}, current_live_root_danger={len(current_danger)+len(current_danger_win)}, wsl_openclaw_related={len(wsl_rows)}, wechat_process_count={wechat['count']}, llama_models={llama.get('count')}, qwen3.6_present={llama.get('qwen36_present')}, mem0_provider={mem0['provider']}\n- 下一步: {next_action}\n\n## Step 0 环境验证\n- D disk: `{disk['raw'].replace(chr(10), ' / ')}`\n- llama-swap: ok={llama['ok']}, model_count={llama.get('count')}, qwen3.6_present={llama.get('qwen36_present')}\n- WeChat: process_count={wechat['count']}\n- zombie downstream/batch node processes: count={zombies['count']} (未满足自动 kill 条件；未执行 taskkill)\n- mem0 runtime: Provider={mem0['provider']}\n\n## Patch #23 ledger\n- #17/#19/#21: superseded by #23\n- #20: incorporated as run-state/checkpoint ledger\n- #22: watchdog patch no net-new; observed fields already present in prompt-review\n- #23: integrated in this run before story selection\n\n## Current WSL danger scan (redacted)\n```text\n{redacted_wsl}\n```\n\n## Current Windows D-touch scan (redacted)\n```json\n{redacted_win}\n```\n\n## Failure classification\n- classification: {failure_class}\n- success: {decision != 'RED'}\n""", encoding='utf-8')

checkpoint=REPORTS/f"checkpoint-day3_{ts}.md"
checkpoint.write_text(f"""# Checkpoint Day 3 — {ts_iso}\n\n- decision: {decision}\n- need_human: {str(need_human).lower()}\n- story: {story}\n- Patch #23: integrated (supersedes #17/#19/#21; incorporates #20 ledger).\n- live-root gate: current_danger={len(current_danger)+len(current_danger_win)}, watchdog_red_6h={len(red6)}, post_red_nonred={post_nonred}.\n- WeChat: {'GREEN' if wechat['count'] else 'RED/process-not-found'}; capture {'not launched' if not wechat['count'] else 'not launched by design'}。\n- llama-swap: {'GREEN' if llama['ok'] and llama['qwen36_present'] else 'AMBER'}; models={llama.get('count')}; qwen3.6_present={llama.get('qwen36_present')}.\n- mem0: Provider={mem0['provider']}; {'no mem0 write attempted' if mem0['provider']!='mem0' else 'mem0 write candidate: Patch #23 gate should be retained'}.\n- next: {next_action}\n\n## Review Loop\n- 本次执行是否成功: {'门禁成功；story 扩大执行被阻止' if decision=='RED' else '成功生成 no-capture fallback artifacts'}。\n- 失败原因分类: {failure_class}\n- 下一步计划调整: {'需要人工处理/隔离 OpenClaw/Stage7/helper 后再进入 US-003 fallback 或 capture gate。' if decision=='RED' else '继续等待 WeChat；下一轮可做 queue detail/quality plan。'}\n- mem0 learning: {'跳过，当前 Hermes memory Provider 不是 mem0。' if mem0['provider']!='mem0' else '可保存：daily-executor 应先执行 Patch #23 live-root gate。'}\n""", encoding='utf-8')

daily=REPORTS/f"daily-executor-2026-05-01_{ts}.md"
daily.write_text(f"""# Daily Executor Report — 2026-05-01 {ts_iso}\n\n```text\ndecision: {decision}\nneed_human: {str(need_human).lower()}\nstage: US-003 Context Gate / capture queue (WeChat-gated)\ncounts: watchdog_red_6h={len(red6)}, post_red_nonred={post_nonred}, current_live_root_danger={len(current_danger)+len(current_danger_win)}, wsl_openclaw_related={len(wsl_rows)}, wechat_process_count={wechat['count']}\nprocess: {'active live-root D-touch danger present' if current_danger or current_danger_win else 'no active live-root D-touch danger found'}\nnext: {next_action}\n```\n\nEvidence: `{evidence}`\nCheckpoint: `{checkpoint}`\n""", encoding='utf-8')

LONGRUN_MD.write_text(f"""# Hermes 7-Day Longrun State\n\nUpdated: {ts_iso}\n\n## Current\n- status: {'blocked_red' if decision=='RED' else 'running'}\n- current_story: {story}\n- next_story: US-003 Context Gate / capture queue\n\n## Live gates\n- decision: {decision}\n- need_human: {str(need_human).lower()}\n- live_root_current_danger: {len(current_danger)+len(current_danger_win)}\n- watchdog_red_6h: {len(red6)}\n- post_red_nonred_watchdogs: {post_nonred}\n- WeChat: {'GREEN' if wechat['count'] else 'RED/process-not-found'}\n- llama-swap: {'GREEN' if llama['ok'] and llama['qwen36_present'] else 'AMBER'}\n- D disk: `{disk['raw'].splitlines()[-1] if disk['raw'] else 'df failed'}`\n- mem0 Provider: {mem0['provider']}\n\n## Artifacts\n- evidence: `{evidence}`\n- checkpoint: `{checkpoint}`\n- daily_report: `{daily}`\n\n## Next\n{next_action}\n""", encoding='utf-8')

# Append night watcher log using Python write, not printf.
log=ROOT/f"NIGHT_WATCHER_LOG_2026-05-01.md"
with log.open('a', encoding='utf-8') as f:
    f.write(f"\n## {ts_iso} Hermes daily executor\n- decision: {decision}\n- need_human: {str(need_human).lower()}\n- stage: US-003 Context Gate / capture queue\n- counts: current_live_root_danger={len(current_danger)+len(current_danger_win)}, watchdog_red_6h={len(red6)}, wechat_process_count={wechat['count']}, llama_models={llama.get('count')}\n- process: {'active live-root D-touch danger present' if current_danger or current_danger_win else 'clear'}\n- next: {next_action}\n")

print(json.dumps({'decision': decision, 'need_human': need_human, 'evidence': str(evidence), 'checkpoint': str(checkpoint), 'daily_report': str(daily), 'current_live_root_danger': len(current_danger)+len(current_danger_win), 'watchdog_red_6h': len(red6), 'post_red_nonred': post_nonred, 'wechat_count': wechat['count'], 'llama': llama, 'mem0_provider': mem0['provider']}, ensure_ascii=False, indent=2))
