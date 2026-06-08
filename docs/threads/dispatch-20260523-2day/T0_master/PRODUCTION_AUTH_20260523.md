# Production Authorization

Updated: 2026-05-23 15:04 CST

User instruction: "在我出差的时间里全量指挥所有线程完成任务 ... 全部都可以执行生产 由你调度"

## Authorized Final Goals

1. Complete Atlas graph:
   -补齐 Atlas DJ 图谱需要的字段。
   -找回以前 DJ-first 地下音乐关系网络可视化图谱计划。
   -完成可展示的 DJ 图谱和搜索库。
   -允许通过 public-safe / staging / rollback gates 后执行 production promotion, Neo4j/Qdrant writes, and public pointer updates.

2. Update mini-program backend activity source and audit logic bugs:
   -更新小程序后端活动源。
   -查找后端/前端/数据包逻辑漏洞。
   -允许 CloudRun backend/resource deploy after guardian/tests/smoke pass.
   -允许 mini-program upload/review only if frontend/API compatibility evidence shows it is required and release checks pass.
   -Related thread: `codex://threads/019e4b34-6edd-73a1-80cd-5d527b5c89c3`.

3. 做梦:
   -Allow Deep Dream documentation/code truth reconciliation.
   -Allow verified durable memory writes to the configured dream backends.
   -Do not persist raw model output or unverified claims.

4. Supervise DeepSeekTUI/LDR outlink crawl:
   -Allow DeepSeekTUI/LDR sidecar to produce candidate outlink/avatar/profile evidence packages.
   -Allow bounded external API use when configured through environment variables and budget/evidence is logged.
   -Do not print or persist secrets.

## Still Not Authorized

- Reading or printing secrets, cookies, tokens, `.env`, SSH keys, browser credentials, or password stores.
- Destructive Git operations: reset, clean, checkout/restore destructive paths, force push, branch/worktree deletion.
- Recursive scan of `D:\`, `D:\DDownload`, or `D:\aidata` roots.
- Unverified production writes without staging evidence, rollback/pointer path, and post-write verification.

