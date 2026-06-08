# DeepSeekTUI 接手提示

> 2026-05-23 lifecycle note: this prompt is an active sidecar/reference prompt, not the latest Atlas serving-candidate authority. The 03:18 strict-public/private-repair counts below predate the 2026-05-22 23:48 DJ-complete activity-aware participant-delta v2 candidate. Before acting, read `docs/current-runtime.md`, `docs/DOCUMENTATION_INDEX.md`, `docs/threads/T6_deepseektui_ldr_sidecar_20260522.md`, and `reports/ATLAS_DJ_GRAPH_COMPLETION_CANDIDATE_20260522.md`. Do not deploy or promote anything from this prompt directly.

你是 WSL2 里的 DeepSeekTUI。请把这份交接当作 Codex 对 Atlas 全量修复工作的事实同步，不要把自己当生产控制器。

先读：

```text
/mnt/c/code/githubstar/wechathtmldownload/docs/atlas-deepseektui-handoff-20260522/ATLAS_FULL_RUN_REPAIR_TO_DEEPSEEK_20260522.md
/mnt/c/code/githubstar/wechathtmldownload/docs/ATLAS_FULL_RUN_AND_REPAIR_WORKLOG_20260522.md
/mnt/c/code/githubstar/wechathtmldownload/docs/ATLAS_SERVING_READ_MODEL_PRODUCTION_RUN_20260522.md
/mnt/c/code/githubstar/wechathtmldownload/docs/ATLAS_FULL_REPAIR_PRIVATE_CANDIDATE_20260522.md
```

当前事实：

- 03:18 包里的可公开部署候选是 `reports/atlas_serving_read_model_20260522/atlas_serving.sqlite`；12:14 V2 候选是 `reports/atlas_serving_recovered_public_v2_20260522/atlas_serving.sqlite`。
- 当前最新本地 DJ-first public-safe serving candidate 需以 `reports/ATLAS_DJ_GRAPH_COMPLETION_CANDIDATE_20260522.md` 为准：`reports/atlas_serving_activity_participant_candidate_139123_publicsafe_djcomplete_v2_20260522-2335/atlas_serving.sqlite`。
- 不可直接部署的是 `reports/atlas_serving_repair_full_private_20260522/atlas_serving.sqlite`。
- Atlas 的主目标是 DJ-first 中国地下电子音乐关系网，不是文章列表。
- 重点实体是 DJ / artist / person；活动、场地、厂牌、公开账号、来源文章都是围绕 DJ 的证据层。
- 用户最关心的是：某个 DJ 的历史演出、经常同台的人、常去的俱乐部、厂牌/crew、公开账号、mixtape/作品、证据链。

你的下一步建议：

1. 只做读档和方案建议，除非用户明确让你写文件。
2. 优先比较 strict public 与 aggressive-private 的差异。
3. 找出 private-only 里最可能安全提升到 strict 的 deterministic 规则。
4. 不要动 `.env`、cookie、token。
5. 不要把 raw URL / raw HTML path / raw JSON / article UID 暴露给 public frontend。
6. 不要建议用大额付费 LLM 重跑全量；先用现有产物、规则、抽检和本地便宜模型。

一句话记忆：

Atlas 的价值在 DJ 关系网络和历史演出，不在把所有抽取实体堆到图上。
