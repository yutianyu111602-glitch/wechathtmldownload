# WSL2 DeepSeek TUI 接手报告 - 2026-06-03

## 1. 主问题

下一位 agent 需要接手 WSL2 DeepSeek TUI / CodeWhale 侧的本地代理运行面，先确认它是否在继续工作、是否有可消费 outbox/任务/日志，再决定是否给它新的继续提示；不要把 DeepSeek TUI 误当作 DB2/OpenClaw runtime release。

## 1.1 本线程职责

这条 Codex 线程是 DB2/OpenClaw 外链抓取长跑的控制面/接手整理线程，不是小程序前端 hotfix 线程，也不是生产 runtime 执行线程。它的职责是把 WSL2 DeepSeek TUI、OpenClaw、DB2 外链抓取、source-fetch gate、SkillOpt/worker 方向和当前 fail-closed 边界整理成可交接事实，让后续 agent 能直接从证据路径、禁止项和下一步 gate 接手。

本线程已经做过的事情：

- 只读核对 WSL2 DeepSeek TUI / CodeWhale 当前进程、版本、状态目录和报告入口。
- 只读核对 DB2/OpenClaw loop-state、wake decision、controller approval status 和 weekly/source-fetch gate 链。
- 把当前状态写成接手文档，供后续 agent 快速恢复上下文。

本线程没有做、也不代表已经允许的事情：

- 没有释放 DB2/OpenClaw runtime gate。
- 没有启动 Docker/worker/crawl/network/DeepSeek/API/DB/package/CloudBase/upload/release。
- 没有把 source-fetch blocker 当作通过。
- 没有读取凭据或 raw source URL。

## 2. 范围

- 角色：WSL2 DeepSeek TUI 运行面接手 agent。
- Windows 工作区：`C:\code\_codex_threads\做梦`。
- WSL2 运行状态：`\\wsl.localhost\Ubuntu\home\pc\.deepseek`，Linux 路径 `/home/pc/.deepseek`。
- 当前可执行动作：只读检查日志、任务、自动化、进程、outbox/报告状态；必要时产出给 DeepSeek TUI 的继续提示词。
- 当前禁止动作：不要读取 `.env`、token、cookie、API key、browser profile、SSH key、凭据文件；不要重启/杀进程/升级包，除非用户显式要求。
- 与 DB2/OpenClaw 的关系：DeepSeek TUI 可以是研究/侧车/提示生成者，但不能替代 DB2/OpenClaw 的 controller gate，也不能自行触发 Docker/worker/crawl/DB/package/CloudBase/upload/release。

## 3. 当前现实

### 已证实

- WSL2 当前发行版入口可用，内核报告为 WSL2 Linux。
- `deepseek-tui` 当前解析到 `/home/pc/.npm-global/bin/deepseek-tui`。
- `codewhale` 当前解析到 `/home/pc/.npm-global/bin/codewhale`。
- `claude-deepseek` 当前解析到 `/home/pc/.local/bin/claude-deepseek`。
- 进程中存在：
  - `node /home/pc/.npm-global/bin/deepseek-tui --config /home/pc/.codewhale/config.toml`
  - `/home/pc/.npm-global/lib/node_modules/codewhale/bin/downloads/codewhale-tui --config /home/pc/.codewhale/config.toml`
- 版本：
  - `deepseek-tui --version` 输出 CodeWhale wrapper `v0.8.49`，binary `v0.8.49`。
  - `codewhale --version` 输出 CodeWhale wrapper `v0.8.49`，binary `v0.8.49`。
  - `claude-deepseek --version` 输出 `2.1.160 (Claude Code)`。
- 配置文件 `/home/pc/.codewhale/config.toml` 存在，但本报告未读取其内容。
- `/home/pc/.deepseek` 下存在 `logs`、`tasks`、`automations`、`sessions`、`memory`、`pastes`、`skills`、`tool_outputs` 等目录。
- 最新可见 TUI 日志文件为 `/home/pc/.deepseek/logs/tui-2026-06-02-4182.log`，mtime 显示到 2026-06-03 12:00。
- `C:\code\_codex_threads\做梦\reports` 里最近有 DeepSeek 相关报告：
  - `deepseek-latest-db-pipeline-report-preflight-20260602.md`
  - `deepseek-selfwake-production-lanes-20260602.md`
  - `deepseek-deep-dream-sidecar-skillopt-20260602.md`
  - `deepseek-v4-pro-deep-sleep-skillopt-eval-20260602.md`

### 历史事实

- 记忆中旧接手记录显示：真实运行状态在 `/home/pc/.deepseek`；旧的 stale `running` 任务 JSON 不能证明 agent 活着，必须联合 `ps`、log tail、queue/runtime state、报告计数判断。
- 旧记录还显示曾出现 `path_escape` warning，路径涉及 `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite`；若再次出现，应作为运行时路径边界问题，而不是业务 pipeline 失败直接处理。
- 旧的 DeepSeek outbox 审核规则：先跑 `C:\code\scripts\dream-deepseek-outbox-preflight.ps1`，它会分类 `PASS_READY_FOR_CODEX_REVIEW`、`REJECT_PREFLIGHT_FAILED`、`WAIT_INCOMPLETE_RECENT_PAIR`、`SKIP_ALREADY_MARKED`、`DEEPSEEK_OUTBOX_NO_REVIEWABLE_PACKET`。

### 未证实

- 当前 TUI 是否正在执行有价值任务，仅靠进程存在不能证明。
- 最新日志内容没有在本报告中 tail 读取；下一位 agent 应按只读方式检查关键错误、最近任务 ID、是否卡在 UI/网络/路径边界。
- 当前 automations 的具体 prompt/config 没有读取；只确认了 automation/run 文件存在。
- 当前是否有新 outbox packet 可被 Codex 消费未复核；需要先跑 preflight。

## 4. 接手后第一轮只读检查

在 PowerShell 中执行：

```powershell
wsl.exe -e sh -lc "ps -eo pid,comm,args | grep -Ei 'deepseek|codewhale|claude-deepseek' | grep -v grep || true"
wsl.exe -e sh -lc "deepseek-tui --version 2>/dev/null || true; codewhale --version 2>/dev/null || true; claude-deepseek --version 2>/dev/null || true"
wsl.exe -e sh -lc "find /home/pc/.deepseek/logs -maxdepth 2 -type f -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' 2>/dev/null | sort | tail -30"
wsl.exe -e sh -lc "find /home/pc/.deepseek/tasks -maxdepth 3 -type f -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' 2>/dev/null | sort | tail -40"
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\scripts\dream-deepseek-outbox-preflight.ps1
```

只读检查后按结果分支：

- `PASS_READY_FOR_CODEX_REVIEW`：只读消费 packet，要求每条 JSONL 记录有 `codex_verification_needed: true` 和证据路径字段；缺证据路径就拒绝。
- `REJECT_PREFLIGHT_FAILED`：写短报告说明拒绝原因，不从缺字段中推断事实。
- `WAIT_INCOMPLETE_RECENT_PAIR`：等待完整配对，不补造文件。
- `SKIP_ALREADY_MARKED` / `DEEPSEEK_OUTBOX_NO_REVIEWABLE_PACKET`：短状态停止。
- TUI 进程存在但日志无进展：先 tail 最新日志和最近任务 JSON，再判断是 UI 空闲、路径问题、JSONL parse 问题、还是真正业务 blocker。

## 5. 给 DeepSeek TUI 的继续提示词模板

仅在用户要求继续推动 DeepSeek TUI 时使用。不要把它当作 DB2 runtime gate。

```text
你是 WSL2 DeepSeek TUI / CodeWhale 侧车。请只读检查 /home/pc/.deepseek 当前运行状态、最近日志、最近任务和 outbox 状态。

边界：
- 不读 .env、token、cookie、API key、browser profile、SSH key、凭据文件。
- 不启动 DB2/OpenClaw Docker worker，不跑 crawl/network/DB/package/CloudBase/upload/release。
- 若发现与 wechathtmldownload/DB2/OpenClaw 相关的产物，只输出 evidence-backed 摘要、路径和下一步建议，不生成 controller release。

任务：
1. 报告当前进程、版本、最新日志文件、最近任务文件。
2. 如果有 outbox packet，确认每条记录是否有 codex_verification_needed=true 和 evidence/path 字段。
3. 如果无可消费 packet，输出 idle/no-op。
4. 如果发现 path_escape、JSONL parse failure、stale running task，把它们分类为 runtime issue，不要当作业务 pipeline 通过。
```

## 6. 禁止误判

- 进程存在不等于任务完成。
- `running` 任务 JSON 不等于 agent 活着。
- TUI 研究/提示词结果不等于 DB2/OpenClaw release artifact。
- 任何涉及微信、CloudBase、DB、上传、发布、DeepSeek API 的动作都必须回到主控 gate，不能由 TUI 侧车自行释放。

## 7. 本报告生成时的核对命令

- `wsl.exe -e sh -lc "ps -eo pid,comm,args | grep -Ei 'deepseek|codewhale|claude-deepseek' | grep -v grep || true"`
- `wsl.exe -e sh -lc "deepseek-tui --version 2>/dev/null || true; codewhale --version 2>/dev/null || true; claude-deepseek --version 2>/dev/null || true"`
- `wsl.exe -e sh -lc "find /home/pc/.deepseek/logs -maxdepth 2 ... | tail -30"`
- `Get-ChildItem C:\code\_codex_threads\做梦\reports -File -Filter '*DeepSeek*'`
