# Unified T0 Queue

Updated: 2026-05-28 04:15 CST

## Last Session Summary (2026-05-28 T0 Diagnostic)

- Q5 advanced: City write execution prepared. Article bridge resolved 61,264/61,266 venue->city candidates (37,548 ready write rows). Write script built and dry-run validated. Awaiting --confirm token execution.
- Critical correction: Article publish_time coverage is 84.75% (117,906/139,123), NOT 0.73% as previously reported. This re-opens T6 year-context for re-evaluation.
- Source/raw DB FTS5 entity_fts index malformed (known issue, non-blocking for city writes).
- All other queues unchanged. huaidj.club upload remains disabled.

T0 is the single coordinator. Full Atlas production completion is now user-authorized, including DB, graph, vector, and public state mutation when the lane has explicit target provenance, rollback/prewrite evidence, minimal write scope, postwrite readback/public smoke, and SSOT closeout. Earlier report-only caution is superseded by `reports\ATLAS_T0_FULL_PRODUCTION_THREAD_DISPATCH_20260526.md`, but secret/cookie/.env/browser-store/password-store reads, 9router/OpenRouter/subscription-routed providers, destructive Git, and unbounded D: scans remain forbidden.

Goal: uninterrupted completion during user travel. If one queue item blocks, T0 records the blocker and immediately advances the next safe queue item.

| Queue | Work Item | Lane | Initial Action |
| --- | --- | --- | --- |
| Q1 | 统一文档、SSOT 和交接入口 | T7 | Keep routers and handoff continuity current after every verified T1-T6 advance. |
| Q2 | 抓公众号文章和维护账号清单 | T1 | Run no-secret source/cache/artifact recovery; do not read credentials. |
| Q3 | 更新小程序后端活动源并找逻辑漏洞 | T2/T3 | Resolve weekly package-root drift, deploy backend if gates pass, upload mini-program only if compatibility requires it. |
| Q4 | 把周活数据安全接到 Atlas 图谱 | T4 | Bind the current derived candidate DB as explicit target provenance if schema/rollback checks pass. |
| Q5 | 补齐 Atlas DJ 图谱字段并完成可视化搜索库 | T5/T6 | Execute source/raw DB write chain, serving rebuild, graph/search/visual smokes, then graph/vector/public promotion with postwrite evidence. |
| Q6 | 监督 DeepSeekTUI/LDR 抓取外链和头像候选 | T6 | Run source/OCR, identity, outlink/avatar/profile evidence recovery; direct DeepSeek only through existing direct runtime credentials. |
| Q7 | 做梦 | deep-dream/T7 | Run Deep Dream docs/code truth reconciliation and verified memory/report closeout. |

## Current Dependency Order

1. Q1 can run any time and after every verified lane output.
2. Q2 feeds Q3 and Q4 when fresh source evidence is needed.
3. Q3 backend package feeds mini-program production state and can feed Q4 Atlas activity source.
4. Q4 now has a Q6 source/raw mapping probe with `8` report-only ready rows and `1` direct explicit target DB path.
5. **Q5 (ACTIVE)**: City write execution ready. Article bridge resolved 61,264/61,266 venue->city candidates. 37,548 ready write rows prepared. Write script at `tools/stage7_rewrite/scripts/run_atlas_t5_city_write_from_article_bridge.py` ready for `--confirm CONFIRM_EXECUTE_CITY_WRITE_ARTICLE_BRIDGE_37548`. Serving overlay + search refresh follow after successful write.
6. **Q5/Q6**: T6 year-context needs re-evaluation. Article publish_time coverage corrected to 84.75% (117,906/139,123). Previously blocked 1,366 rows may now be resolvable. Source/raw DB FTS5 entity_fts index malformed (non-blocking).
7. Q6 delivered DJ completion overlay rollup with 5 work orders: T7 SSOT drift (P0), social overlay persistence (P1), avatar/media recovery (P2), time/city/venue gap (P3 -- city part ready), graph UI contract smoke (P4).
8. Q7 Deep Dream runs in parallel only as docs/code truth reconciliation; T7 consumes verified outputs.

## Lock Rule

- One primary queue item is selected per automation run.
- Additional independent lane-local checks may run in the same automation run if they do not edit shared SSOT files or touch the same outputs.
- Do not let two lanes edit the same SSOT or current-runtime surface.
- T1-T6 write only lane-local status/report/handoff until T7 consumes them.

## Autonomy Rule

- Do not pause for ordinary ambiguity when a safe local check, test, candidate build, report, or handoff can move the work forward.
- Do not pause only because the action is production-effective: user has now authorized production DB/vector/graph/public mutation. Still require rollback/postwrite evidence for production mutation, and still stop before credential/session secret handling, destructive Git, 9router/subscription-routed providers, or unbounded D: scans.
