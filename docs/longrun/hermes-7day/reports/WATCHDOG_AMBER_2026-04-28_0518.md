<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 🟡 WATCHDOG AMBER REPORT — 2026-04-28 05:18 +08

## 综合判定：AMBER（llama-swap 已恢复但 WSL 侧不可达，非阻断）

## 升级路径
```
02:32 preflight  → AMBER (llama-swap 超时, llama-server LISTENING)
03:38 watchdog   → AMBER (llama-swap 超时, llama-server LISTENING) — 2nd failure
04:14 watchdog   → RED   (llama-swap 超时, llama-server GONE)     — 3rd failure ⚠️
05:18 watchdog   → AMBER (llama-server 重启恢复, Windows 侧可达, WSL curl 不可达)
```

## 详细检查

| 检查项 | 状态 | 详情 |
|--------|------|------|
| run-state.json | ✅ GREEN | running, P0 Day 0 Setup, US-000/US-001 完成 |
| D盘剩余空间 | ✅ GREEN | 8.4TB / 15TB (43%) |
| llama-swap:11434 (WSL) | ⚠️ AMBER | curl exit 7 (WSL2 网络隔离) |
| llama-swap:11434 (Win) | ✅ GREEN | HTTP 200, models: Qwen3.6-27B, bge-m3:latest |
| llama-server.exe | ✅ GREEN | PID 43864, 启动于 04:33 (自动恢复!) |
| llama-swap.exe | ✅ GREEN | PID 30772, 运行中, 端口 LISTENING |
| checkpoint 新鲜度 | ⚠️ AMBER | ~64min (last 04:14, now 05:18) |
| 危险进程扫描 | ✅ GREEN | 无递归扫描 |
| 输出目录 | ✅ GREEN | 0 字节 (Day0 预期) |
| WeChat 进程 | ⚠️ AMBER | 未运行 |

## 关键发现：llama-server 自动恢复

**恢复时间线：**
```
03:38  PID 50800 (llama-server.exe) LISTENING 但 HTTP 无响应
04:14  PID 50800 消失 — RED 判定
04:33  PID 43864 (llama-server.exe) NEW — 自动重启! 🟢
05:18  PID 43864 仍在运行, PID 30772 (llama-swap) 仍在运行
```

Windows PowerShell `Invoke-WebRequest` 确认：
- `http://127.0.0.1:11434/v1/models` → HTTP 200
- 返回模型：Qwen3.6-27B, bge-m3:latest
- 服务**正常运行**

## WSL curl 失败原因

WSL2 使用独立网络命名空间，`127.0.0.1` 在 WSL 中指向 WSL 自身的回环接口，不指向 Windows 主机。Windows 服务需要经由 WSL2 虚拟网桥访问（如 `10.255.255.254`），但安全策略阻止了来自 cron 的原始 IP 请求。

**影响**：WSL cron 任务中的 curl 健康检查会持续报告 AMBER，但服务本身健康。

## 硬规则检查
- ✅ 无 D:\DDownload 写入/修改
- ✅ 无 git reset/clean/删除
- ✅ 无 Docker prune/删除
- ✅ 无禁止进程
- ✅ 本报告仅写入 reports/ 目录

## REVIEW LOOP（反思层）

### Mini Review
llama-server 在 04:14 ~ 04:33 之间自动恢复（PID 50800 → PID 43864），Windows 侧完全正常。当前唯一异常是 WSL2 网络隔离导致 WSL curl 无法访问 Windows localhost 服务。Day0 进展顺利（US-000/US-001 完成），无 new stories 被阻塞。

### 需要调整的事项
- **健康检查方式**：WSL cron 的 curl 检查应改用 Windows PowerShell `Invoke-WebRequest` 命令（已验证有效），避免 WSL2 网络隔离误报
- **RED 降级条件**：llama-server 进程恢复后应从 RED 降级为 AMBER（当前已执行）
- **自动恢复记录**：记录 llama-swap 的自动重启行为，为 future 故障模式分析积累数据

## 决策
- **decision: AMBER**
- **need_human: false**（服务已自动恢复，非阻断）
- **action**: 继续监控，关注 llama-server 稳定性
- **下次 watchdog**: ~05:48 +08
