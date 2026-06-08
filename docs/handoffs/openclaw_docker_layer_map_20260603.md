# OpenClaw Docker Layer Map (VSA-20)

时间: 2026-06-03

## 分层

- L0: control plane (skills/db2ctl, no heavy scripts)
- L1: source exporter
- L2: source queue/cache
- L3: OCR
- L4: extraction/coordinate gate runtime contracts
- L5: map verify
- L6: package merge
- L7: deploy/upload wrapper (explicit gate only)

## 原则

1. skill 只做控制面，不承载大脚本。
2. worker runtime 通过 compose profile 执行。
3. 所有执行层默认 no-network/no-write，需显式 release 才可开启。
