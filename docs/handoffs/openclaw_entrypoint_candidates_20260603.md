# OpenClaw Entrypoint Candidates (VSA-21)

时间: 2026-06-03

## 候选归类

1. L2 source queue/cache runner
- 输入: source-fetch allowlist queue
- 输出: runtime summary + blockers + acceptance packet
- 日志: runtime stdout/stderr + json summary

2. L4 coordinate write gate runner
- 输入: approved coordinate rows + controller release
- 输出: write/readback/rollback artifacts
- 日志: write transaction logs + readback rows

3. L6 package merge runner
- 输入: validated delta package rows
- 输出: merged package + verification report
- 日志: merge report + parity check

## 统一约束

- retry/checkpoint/lease/kill-switch 必须存在。
- 默认 no-secret/no-profile/no-public-release。
