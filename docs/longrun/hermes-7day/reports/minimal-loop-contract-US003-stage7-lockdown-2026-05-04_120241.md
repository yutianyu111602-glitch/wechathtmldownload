## Minimal Loop: US-003 Stage7/93K lockdown gate
### 目标
整合 prompt-review #36，先验证 Stage7/93K writer/commander gate，再决定是否允许 no-capture US-003。
### 非目标
不 capture，不启动 downstream/OCR/graph，不 kill/restart/delete/repair，不修改 D:\DDownload\_llm_release_v2。
### 文件边界
只写 docs/longrun/hermes-7day/state 与 reports；只读进程表、llama-swap、磁盘、WeChat/mem0 状态。
### 执行命令
python3 /tmp/hermes_daily_executor_20260504.py
### 验收标准
start heartbeat、ledger、evidence、checkpoint、run-state heartbeat 均落盘；若 writer/commander active 则 RED 停止。
### 停止条件
writer_count>0 或 commander_count>0；disk<50GB；数据损坏迹象。
### 风险
OpenClaw-derived commander 可能继续自动 relaunch Stage7/93K writers；需 human quarantine。
