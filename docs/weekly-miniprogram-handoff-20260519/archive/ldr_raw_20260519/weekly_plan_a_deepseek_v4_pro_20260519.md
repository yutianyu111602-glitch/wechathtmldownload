# WeChat Artifact Research

```json
{
  "generated_at": "2026-05-19T20:50:16",
  "role": "research_candidate_generator",
  "confirmed_truth": false,
  "next_gate": "HOLD_FOR_HERMES_DECISION",
  "forbidden_actions": [
    "write_mem0",
    "write_qdrant",
    "write_neo4j",
    "write_openhuman",
    "trigger_openclaw",
    "start_stage7"
  ],
  "model": "deepseek-v4-pro",
  "endpoint": "https://api.deepseek.com",
  "strategy": "direct",
  "source_dir": "/source_pack/weekly_plan_deepresearch_20260519",
  "source_doc_count": 10,
  "sources_used": [
    {
      "title": "01_PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md",
      "link": "/source_pack/weekly_plan_deepresearch_20260519/01_PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md",
      "snippet": "# 计划一：周活小程序识别准确率优化\n\nUpdated: 2026-05-19  \nScope: HUAIDJ weekly mini-program only  \nStatus: **设计稿**（未实施）\n\n## 1. 目标与原则\n\n| 原则 | 含义 |\n|------|------|\n| 宁可空，不可错 | 保持大众产品信任 |\n| 可证明才展示 | 每条字段可指回 evidence（正文或 `ocr:img_*`） |\n| 分层置信 | show / show_with_hint / hide |\n| 评测驱动 | 无 golden set 不宣称「更准」 |\n\n### 北极星指标（建议）\n\n| 指标 | 当前粗估 | 12 周目标（示例） |\n|------|----------|-------------------|\n| 已发布活动有 lineup 且 strict 通过 | ~39%（40/103） | 55–65% |\n| lineup 精确率（golden） | 未测 | ≥92% |\n| lineup 召回率（golden） | 未测 | ≥75% |\n| 时间/地址精确率 | Flash date 0.73–0.90 | ≥90%（有 OCR 子集） |\n| backend raw URL hits | 51 | 0 |\n\n## 2. 现状诊断\n\n### 漏斗（示意）\n\nPrefetch ~8800 → Pack ~1500 → OCR 实跑少（大量 skip）→ DeepSeek → API 过滤 → 发布 ~103 → 有 lineup ~40\n\n### 损失点\n\n| 阶段 | 问题 |\n|------|------|\n| 召回 | outside_date_window、blocked 账号 |\n| OCR | 覆盖低；仅前 N 图；preflight 阻断 |\n| DeepSeek | unsupported lineup 被 merge 砍；lineup_weak_evidence |\n| repair | bio gate、event",
      "full_content": "# 计划一：周活小程序识别准确率优化\n\nUpdated: 2026-05-19  \nScope: HUAIDJ weekly mini-program only  \nStatus: **设计稿**（未实施）\n\n## 1. 目标与原则\n\n| 原则 | 含义 |\n|------|------|\n| 宁可空，不可错 | 保持大众产品信任 |\n| 可证明才展示 | 每条字段可指回 evidence（正文或 `ocr:img_*`） |\n| 分层置信 | show / show_with_hint / hide |\n| 评测驱动 | 无 golden set 不宣称「更准」 |\n\n### 北极星指标（建议）\n\n| 指标 | 当前粗估 | 12 周目标（示例） |\n|------|----------|-------------------|\n| 已发布活动有 lineup 且 strict 通过 | ~39%（40/103） | 55–65% |\n| lineup 精确率（golden） | 未测 | ≥92% |\n| lineup 召回率（golden） | 未测 | ≥75% |\n| 时间/地址精确率 | Flash date 0.73–0.90 | ≥90%（有 OCR 子集） |\n| backend raw URL hits | 51 | 0 |\n\n## 2. 现状诊断\n\n### 漏斗（示意）\n\nPrefetch ~8800 → Pack ~1500 → OCR 实跑少（大量 skip）→ DeepSeek → API 过滤 → 发布 ~103 → 有 lineup ~40\n\n### 损失点\n\n| 阶段 | 问题 |\n|------|------|\n| 召回 | outside_date_window、blocked 账号 |\n| OCR | 覆盖低；仅前 N 图；preflight 阻断 |\n| DeepSeek | unsupported lineup 被 merge 砍；lineup_weak_evidence |\n| repair | bio gate、event_context 过严 → **假阴性** |\n| API | `dj_bio_lines: []` 写死 |\n| 展示 | format.js 再过滤 |\n\n**结论**：需要 **证据链 + 分字段置信 + golden 闭环**，不是单纯加强 prompt。\n\n## 3. 目标架构\n\n```\nL0 源: HTML + 海报 → OCR → source_evidence.md\nL1 确定性: 日期 regex、registry、lineup 候选（w/DJ 邻域）\nL2 模型: Flash 全量 + Pro 风险行 → JSON + field_evidence_refs\nL3 裁决: merge → repair → audit → published + display_tier\n```\n\n### 置信对象（概念）\n\n```yaml\nfield: lineup_artists\nconfidence: 0.86\ntier: show | show_with_hint | hide\nevidence:\n  - { type: ocr, image_id: img_abc, quote: \"...\" }\n  - { type: body, quote: \"w/ Artist A\" }\n```\n\n## 4. 分字段策略\n\n### 4.1 日期\n\n- Regex + 标题范围 + 窗口校验；冲突日期禁止 dedupe 合并\n- Golden：start/end 误差 0 天为对\n\n### 4.2 Lineup（核心）\n\n| 子策略 | 说明 |\n|--------|------|\n| B1 海报结构化 OCR | lineup 区 / 日期区 / 地址区分块 |\n| B2 Regex 候选器 | LLM 只做裁决，不发明 |\n| B3 event_context 评分制 | 替代硬清空阈值 |\n| B4 Bio gate 按行打分 | 保留巡演/专场 cue |\n| B5 Pro 触发扩面 | 有候选但 Flash 空 → Pro |\n| B6 聚合子活动 | 子文 lineup 禁止继承父 marketing |\n\n### 4.3 Bio / DJ 图\n\n- 自动 bio：**仅** registry `bio_manual` 或图谱 verified\n- DJ 图：poster 裁剪 + `image_id` 溯源\n- API 层 `dj_bio_lines` 解锁需产品批准 + verified 管道\n\n### 4.4 场地 / 风格 / 票价\n\n- registry 优先；OCR 地址 garbage 过滤\n- 风格仅显式字段 + 词典；票价 regex\n\n## 5. OCR + LLM 准确性判定\n\n### 三层验证\n\n| 层 | 方法 |\n|----|------|\n| L-A 硬门 | audit strict、duplicate 0、source URL |\n| L-B 软分 | confidence → tier |\n| L-C 金标 | 每周 50–100 条人工标注 |\n\n### 度量\n\n```\nprecision = |shown ∩ gold| / |shown|\nrecall    = |shown ∩ gold| / |gold|\nhard_error = gold 明确否决仍展示 → 一票否决\n```\n\n### OCR 门\n\n| 信号 | 动作 |\n|------|------|\n| 低置信 + 图多文少 | needs_ocr_review，不发布 |\n| OCR vs 正文时间冲突 | Pro → 仍冲突则 hide time |\n\n## 6. 路线图\n\n| 阶段 | 周期 | 交付 |\n|------|------|------|\n| P0 度量 | 2 周 | Golden 80 条 + baseline 报告 |\n| P1 证据 | 3 周 | field_evidence_refs 强制；OCR A/B |\n| P2 候选+裁决 | 4 周 | Regex 候选器；event_context 评分 |\n| P3 展示 | 3 周 | tier UI；verified bio |\n| P4 闭环 | 持续 | 每周人工复核 → registry |\n\n## 7. 明确不做\n\n- LLM 自由 bio\n- 无 evidence lineup 展示\n- 放松 duplicate / source URL 硬门\n\n## 8. 依赖文件\n\n- `enrich_weekly_activity_pack_with_deepseek.py`\n- `archive_old/enrich_weekly_activity_pack_with_poster_ocr.py`\n- `archive_old/build_weekly_activity_miniprogram_api.py`\n- `repair_weekly_lineup_address_time_fields.py`\n- `audit_weekly_lineup_address_time.py`\n- `evaluate_weekly_deepseek_prompt_matrix.py`\n",
      "rank": 1,
      "index": "1"
    },
    {
      "title": "07_weekly_deepseek_prompt_matrix_20260518_FINDINGS.md",
      "link": "/source_pack/weekly_plan_deepresearch_20260519/07_weekly_deepseek_prompt_matrix_20260518_FINDINGS.md",
      "snippet": "# Weekly DeepSeek Prompt Matrix Findings 2026-05-18\n\n## Scope\n\n本轮只验证公众号活动抽取质量，不上传、不覆盖线上 current release。目标是找到“精准黄页式抽取”的最优模型/思考/提示词组合，并补掉当前数据样本中暴露的日期与 lineup 风险。\n\n当前样本来自：\n\n- current release: `services/weekly_activity_cloudrun/data/current_release/current.json`\n- recommendation pack: `D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_AGGREGATE_20260517`\n- 15 天窗口 probe: `tools\\stage7_rewrite\\reports\\weekly_api_rebuild_probe_20260518`\n- bounded local article exports: `D:\\DDownload\\OIL油`, `D:\\DDownload\\loopy Club`, `D:\\DDownload\\EXIT Shanghai`\n\n## Auth And Provider State\n\n- DeepSeek API key: present in Windows environment, not printed.\n- DeepSeek models verified by API: `deepseek-v4-flash`, `deepseek-v4-pro`.\n- OpenAI OAuth: `codex login status` reports `Logged in using ChatGPT`.\n- Programmatic OpenAI API token/base URL: not present in environment, so this harne",
      "full_content": "# Weekly DeepSeek Prompt Matrix Findings 2026-05-18\n\n## Scope\n\n本轮只验证公众号活动抽取质量，不上传、不覆盖线上 current release。目标是找到“精准黄页式抽取”的最优模型/思考/提示词组合，并补掉当前数据样本中暴露的日期与 lineup 风险。\n\n当前样本来自：\n\n- current release: `services/weekly_activity_cloudrun/data/current_release/current.json`\n- recommendation pack: `D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_AGGREGATE_20260517`\n- 15 天窗口 probe: `tools\\stage7_rewrite\\reports\\weekly_api_rebuild_probe_20260518`\n- bounded local article exports: `D:\\DDownload\\OIL油`, `D:\\DDownload\\loopy Club`, `D:\\DDownload\\EXIT Shanghai`\n\n## Auth And Provider State\n\n- DeepSeek API key: present in Windows environment, not printed.\n- DeepSeek models verified by API: `deepseek-v4-flash`, `deepseek-v4-pro`.\n- OpenAI OAuth: `codex login status` reports `Logged in using ChatGPT`.\n- Programmatic OpenAI API token/base URL: not present in environment, so this harness did not compare raw OpenAI API output. Codex OAuth is available for Codex-side work, not as a reusable Python API credential in this evaluator.\n\n## Experiment Design\n\nSample categories:\n\n- `title_date_mismatch`: title/date evidence conflict or historical date-shift bug class.\n- `lineup_noise`: lineup contains prose/bio/platform text risk.\n- `image_heavy`: text is weak and poster/OCR quality decides publishability.\n- `aggregate_child`: monthly/weekly aggregation articles and child event extraction.\n- `complete_control`: normal complete event control group.\n\nModel matrix:\n\n- `deepseek-v4-flash`, thinking disabled.\n- `deepseek-v4-flash`, thinking enabled.\n- `deepseek-v4-pro`, thinking disabled.\n- `deepseek-v4-pro`, thinking enabled.\n\nPrompt variants:\n\n- `baseline_v1`\n- `yellowpage_strict_v2`\n- `yellowpage_gate_v3`\n\nProduction scoring emphasizes: exact source-grounded date, no out-of-window publish, no guessed lineup, evidence quote is source text, JSON compliance, and latency.\n\n## Results\n\nRound 1, 5 samples x 2 prompts x 4 model combinations:\n\n- Best raw score before hard gate: `baseline_v1 + flash_no_thinking`, avg `0.8920`, JSON `5/5`, avg latency `3.21s`.\n- Best strict prompt in round 1: `yellowpage_strict_v2 + pro_no_thinking`, avg `0.8920`, JSON `5/5`, avg latency `12.25s`.\n- Thinking-enabled variants had unstable JSON: empty response / unterminated JSON appeared in both Flash and Pro.\n\nRound 2, 10 samples x `yellowpage_gate_v3` x 4 model combinations:\n\n| Rank | Combination | JSON | Avg Score | Date | Lineup | Evidence | Avg Latency |\n| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n| 1 | `flash_no_thinking` | 10/10 | 0.9106 | 0.90 | 1.00 | 0.94 | 3.10s |\n| 2 | `pro_no_thinking` | 10/10 | 0.8582 | 0.80 | 1.00 | 0.88 | 15.75s |\n| 3 | `flash_thinking` | 8/10 | 0.7580 | 0.80 | 0.80 | 0.50 | 15.26s |\n| 4 | `pro_thinking` | 7/10 | 0.6860 | 0.70 | 0.70 | 0.60 | 61.04s |\n\nRound 3, 15 samples x `yellowpage_gate_v3` x 4 model combinations:\n\n| Rank | Combination | JSON | Avg Score | Date | Lineup | Evidence | Avg Latency |\n| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n| 1 | `pro_no_thinking` | 15/15 | 0.8337 | 0.93 | 0.95 | 0.89 | 17.06s |\n| 2 | `flash_thinking` | 12/15 | 0.7627 | 0.80 | 0.80 | 0.53 | 15.96s |\n| 3 | `flash_no_thinking` | 15/15 | 0.7623 | 0.73 | 1.00 | 0.77 | 3.35s |\n| 4 | `pro_thinking` | 10/15 | 0.5971 | 0.60 | 0.67 | 0.36 | 53.97s |\n\nDDownload local article round, 10 bounded local exports x `yellowpage_gate_v3` x 4 model combinations:\n\n| Rank | Combination | JSON | Avg Score | Date | Lineup | Evidence | Avg Latency |\n| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n| 1 | `flash_no_thinking` | 10/10 | 0.8642 | 0.97 | 1.00 | 0.44 | 4.26s |\n| 2 | `flash_thinking` | 9/10 | 0.8372 | 0.80 | 0.90 | 0.78 | 13.46s |\n| 3 | `pro_no_thinking` | 10/10 | 0.8246 | 0.91 | 1.00 | 0.80 | 17.32s |\n| 4 | `pro_thinking` | 5/10 | 0.4312 | 0.47 | 0.40 | 0.34 | 69.66s |\n\nUpdated conclusion:\n\n- For broad, high-throughput article screening and default materialization, use `deepseek-v4-flash` with thinking disabled and `yellowpage_gate_v3`.\n- For quality-critical rows, use `deepseek-v4-pro` with thinking disabled as an adjudicator or primary extraction pass when latency/cost is acceptable.\n- Thinking-enabled output is still not production-safe for JSON materialization: it is slower and JSON compliance repeatedly drops, especially on aggregation/image-heavy samples.\n- The reliable production answer is two-stage extraction: Flash no-thinking for every article, then Pro no-thinking for rows that are publishable or risky.\n\nPipeline integration added:\n\n- New script: `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_deepseek.py`.\n- Default lane: `deepseek-v4-flash`, `thinking={\"type\":\"disabled\"}`, `response_format={\"type\":\"json_object\"}`.\n- Risk/adjudication lane: `deepseek-v4-pro`, also thinking disabled.\n- Risk flags currently include aggregation child/body rows, review/publish-blocked rows, cross-source conflicts, source-evidence rows missing time/address, and image-heavy weak-text rows.\n- Merge policy reuses the strict weekly source-grounding rules: model output cannot add unsupported time, address, lineup, DJ bio, venue bio, distance, or marketing prose.\n\n## Recommended Prompt Policy\n\nUse `yellowpage_gate_v3` as the production prompt family:\n\n- Only source-grounded fields may be emitted.\n- Date must be recognized before window filtering; never shift old dates to today, weekend, or window start.\n- Aggregation articles must be split into child events; parent rows should not publish as a single event.\n- Lineup only accepts names adjacent to lineup cues such as DJ, 阵容, 嘉宾, w/, with, present, live, set.\n- Bio, intro, organizer, ticketing, platform copy, title fragments, and unsupported artist names are not lineup.\n- Unknown time/address/lineup must stay null or empty and be marked uncertain.\n- Evidence quote must be a continuous source quote, not a rewrite.\n\n## Pipeline Fixes Made In This Pass\n\n- Fixed publication date gate in `build_weekly_activity_miniprogram_api.py`: primary/title date controls publishability, so an old event cannot be shifted into the current 15-day window by later unrelated evidence dates.\n- Added missing wrapper `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py` so the active pipeline path resolves without depending on archive fallback.\n- Added DeepSeek prompt matrix evaluator `tools/stage7_rewrite/scripts/evaluate_weekly_deepseek_prompt_matrix.py`.\n- Added bounded DDownload article evaluator `tools/stage7_rewrite/scripts/evaluate_ddownload_deepseek_article_samples.py`.\n  - It only reads explicit article/account dirs and skips secret-looking filenames.\n  - It prevents body history dates from polluting expected event dates.\n  - It prefers article `create_time` over folder name for relative titles such as `今晚`.\n  - It penalizes local article responses that over-extract unsupported extra dates.\n- Added online DeepSeek weekly enrichment/adjudication entry `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_deepseek.py`.\n  - It replaces the old local GPT-OSS enrichment lane for production use.\n  - It defaults to Flash no-thinking and routes risky rows to Pro no-thinking.\n  - It writes a summary with model counts and risk-flag counts without storing or printing the API key.\n  - It filters pure artist/venue biography lines out of `description_original_lines`; source-backed event-detail lines may remain, but unsupported bio fields are not merged.\n- Added conservative lineup repair for:\n  - bio/education/prose tokens such as `介绍 Rayne ·乐手` and `面向爱好者开展合成器教学与科普`;\n  - malformed/truncated tokens such as `Jesse Kanda (A`;\n  - unsupported lineup is cleared and front-end should show source-view hint.\n\n## Rebuild Probe After Fixes\n\nCommand target: `2026-05-18` through `2026-06-01`, max items `10000`.\n\nObserved:\n\n- Source rows loaded: `1063`\n- Published probe items: `25`\n- Outside target window: `992`\n- Publish blocked: `44`\n- Missing time warning: `7`\n- Missing address: `0`\n- Duplicate clusters: `0`\n- Cross-source conflict clusters: `0`\n- Published schema validation: OK\n- Suspicious lineup after repair: `0`\n- Extra heuristic lineup noise after repair: `0`\n\nThe low item count is mainly because the current source pack is date-stale for a 2026-05-18 15-day window. To increase count, the upstream crawler/extractor must rerun against fresh followed accounts, including weekday events and aggregation child links.\n\n## Verification\n\nUnit and regression checks:\n\n```powershell\npython -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_evaluate_weekly_deepseek_prompt_matrix tools.stage7_rewrite.tests.test_repair_weekly_lineup_address_time_fields tools.stage7_rewrite.tests.test_weekly_activity_deepseek_enrichment -v\n```\n\nResult: relevant weekly tests passed.\n\nAdditional local article evaluator checks:\n\n```powershell\npython -m unittest tools.stage7_rewrite.tests.test_evaluate_ddownload_deepseek_article_samples -v\npython -m py_compile tools\\stage7_rewrite\\scripts\\evaluate_ddownload_deepseek_article_samples.py\n```\n\nResult: DDownload evaluator tests passed; syntax check passed.\n\nRelease probe checks:\n\n```powershell\npython tools\\stage7_rewrite\\scripts\\audit_weekly_cross_source_conflicts.py --input tools\\stage7_rewrite\\reports\\weekly_api_rebuild_probe_20260518\\current.json --strict\npython tools\\stage7_rewrite\\scripts\\audit_weekly_lineup_address_time.py --api-dir tools\\stage7_rewrite\\reports\\weekly_api_rebuild_probe_20260518\npython tools\\stage7_rewrite\\scripts\\archive_old\\validate_weekly_event_published.py tools\\stage7_rewrite\\reports\\weekly_api_rebuild_probe_20260518\\current.json\n```\n\nResult: no duplicates, no cross-source conflicts, published schema OK, address/time diff OK, suspicious lineup `0`.\n\nDeepSeek integration regression:\n\n```powershell\npython -m py_compile tools\\stage7_rewrite\\scripts\\enrich_weekly_activity_pack_with_deepseek.py tools\\stage7_rewrite\\scripts\\expand_weekly_aggregate_articles.py tools\\stage7_rewrite\\script",
      "rank": 7,
      "index": "2"
    },
    {
      "title": "04_DELIVERABLE_URL_TRACE_51.md",
      "link": "/source_pack/weekly_plan_deepresearch_20260519/04_DELIVERABLE_URL_TRACE_51.md",
      "snippet": "# 交付物：后端 51 条 URL 溯源设计与实测\n\nUpdated: 2026-05-19  \nPackage: `D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519`\n\n## 1. 扫描方法\n\n与 `huaidj-weekly-release-guardian\\scripts\\check_weekly_release_guard.ps1` 探针一致：\n\n- 原始字段：`description_original_lines`, `dj_bio_lines`, `summary`, `description`\n- 正则：`https?://`, `mmbiz.qpic`, `qpic.cn`, `wx_fmt=`, `from=appmsg`, `#imgIndex=`\n- 可见层：`compactItem` 后 `descriptionLines` / `bioLines`\n\n## 2. 实测结果\n\n| 指标 | 值 |\n|------|-----|\n| 发布条数 | 103 |\n| rawHits | **51** |\n| visibleHits | **0** |\n| 涉及字段 | **仅** `description_original_lines` |\n| 涉及活动数 | **23** / 103 (22.3%) |\n| URL 形态 | 全部为 `mmbiz.qpic.cn` 整行 CDN |\n\n## 3. 高发活动（每 id 最多 3 行）\n\n| event id | 行数 |\n|----------|------|\n| tangtangtang:5e86d5854dc6bcf9 | 3 |\n| tomtwo:2142667973a0bac1 | 3 |\n| dirty_house:ce92df09b77cbf74 | 3 |\n| nu_lab:3f015c131135ead2 | 3 |\n| dong:09c85265248aaa22 |",
      "full_content": "# 交付物：后端 51 条 URL 溯源设计与实测\n\nUpdated: 2026-05-19  \nPackage: `D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519`\n\n## 1. 扫描方法\n\n与 `huaidj-weekly-release-guardian\\scripts\\check_weekly_release_guard.ps1` 探针一致：\n\n- 原始字段：`description_original_lines`, `dj_bio_lines`, `summary`, `description`\n- 正则：`https?://`, `mmbiz.qpic`, `qpic.cn`, `wx_fmt=`, `from=appmsg`, `#imgIndex=`\n- 可见层：`compactItem` 后 `descriptionLines` / `bioLines`\n\n## 2. 实测结果\n\n| 指标 | 值 |\n|------|-----|\n| 发布条数 | 103 |\n| rawHits | **51** |\n| visibleHits | **0** |\n| 涉及字段 | **仅** `description_original_lines` |\n| 涉及活动数 | **23** / 103 (22.3%) |\n| URL 形态 | 全部为 `mmbiz.qpic.cn` 整行 CDN |\n\n## 3. 高发活动（每 id 最多 3 行）\n\n| event id | 行数 |\n|----------|------|\n| tangtangtang:5e86d5854dc6bcf9 | 3 |\n| tomtwo:2142667973a0bac1 | 3 |\n| dirty_house:ce92df09b77cbf74 | 3 |\n| nu_lab:3f015c131135ead2 | 3 |\n| dong:09c85265248aaa22 | 3 |\n| potent:32fabb508702db79 | 3 |\n| account_f07ee3e4a5:e9de7868aa948e97 | 3 |\n| dirty_house:4adbc111e3a859ef | 3 |\n| nuts:363cacac977044b8 | 3 |\n| 另有 14 个 id 各 1–2 行 | |\n\n完整行级列表：`C:\\Users\\pc\\.cursor\\projects\\empty-window\\url-hits-20260519.json`\n\n## 4. 根因链\n\n```\nOCR/正文拆行 → DeepSeek pack → build API 写入 description_original_lines\n  → 未剥离 URL → format.js 展示层过滤 → 用户不可见\n```\n\n- 非 source_map 问题（missing 0/0）\n- 非前端漏过滤（单测通过）\n\n## 5. 清洗设计（待实施）\n\n| 决策 | 建议 |\n|------|------|\n| 位置 | `archive_old/build_weekly_activity_miniprogram_api.py` 写入前 |\n| 规则 | 与 `format.js` DISPLAY_URL_RE 同构，删行 |\n| 保留 | cover_image_url、poster API、source hash |\n| 验收 | guardian `backendRawHits=0` 升为硬门 |\n\n## 6. 复现命令\n\n```powershell\npowershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\pc\\.codex\\skills\\huaidj-weekly-release-guardian\\scripts\\check_weekly_release_guard.ps1 -CurrentReleaseDir D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519\n```\n",
      "rank": 4,
      "index": "3"
    },
    {
      "title": "08_weekly_pipeline_loss_chain_idfix_20260518.md",
      "link": "/source_pack/weekly_plan_deepresearch_20260519/08_weekly_pipeline_loss_chain_idfix_20260518.md",
      "snippet": "# Weekly Pipeline Loss Chain Audit\n\n- generated_at: `2026-05-18T23:07:33`\n- window: `2026-05-18` .. `2026-06-01`\n- registry active: `122`\n- prefetch rows: `8819`\n- queue rows: `3898`\n- pack candidates/review: `1544` / `350`\n- OCR fetched/skipped/images: `94` / `1631` / `726`\n- aggregate child publish/review: `56` / `113`\n- published items: `104`\n\n## Findings\n- `info` `ACCOUNTS_BLOCKED_BEFORE_PUBLISH`: 49 active accounts reached pack but published 0 items\n\n## API Filtered Counts\n```json\n{\n  \"missing_address_warning\": 9,\n  \"missing_source_date\": 106,\n  \"missing_time_warning\": 72,\n  \"outside_date_window\": 1613,\n  \"publish_blocked\": 42\n}\n```\n\n## Account Coverage\n\n```json\n{\n  \"status_counts\": {\n    \"blocked_before_publish\": 49,\n    \"published\": 40,\n    \"no_post_in_article_cache_window\": 27,\n    \"dropped_before_pack\": 6\n  },\n  \"city_status_counts\": {\n    \"beijing\": {\n      \"published\": 8,\n    ",
      "full_content": "# Weekly Pipeline Loss Chain Audit\n\n- generated_at: `2026-05-18T23:07:33`\n- window: `2026-05-18` .. `2026-06-01`\n- registry active: `122`\n- prefetch rows: `8819`\n- queue rows: `3898`\n- pack candidates/review: `1544` / `350`\n- OCR fetched/skipped/images: `94` / `1631` / `726`\n- aggregate child publish/review: `56` / `113`\n- published items: `104`\n\n## Findings\n- `info` `ACCOUNTS_BLOCKED_BEFORE_PUBLISH`: 49 active accounts reached pack but published 0 items\n\n## API Filtered Counts\n```json\n{\n  \"missing_address_warning\": 9,\n  \"missing_source_date\": 106,\n  \"missing_time_warning\": 72,\n  \"outside_date_window\": 1613,\n  \"publish_blocked\": 42\n}\n```\n\n## Account Coverage\n\n```json\n{\n  \"status_counts\": {\n    \"blocked_before_publish\": 49,\n    \"published\": 40,\n    \"no_post_in_article_cache_window\": 27,\n    \"dropped_before_pack\": 6\n  },\n  \"city_status_counts\": {\n    \"beijing\": {\n      \"published\": 8,\n      \"blocked_before_publish\": 3,\n      \"no_post_in_article_cache_window\": 2,\n      \"dropped_before_pack\": 2\n    },\n    \"changchun\": {\n      \"published\": 1,\n      \"blocked_before_publish\": 1\n    },\n    \"changsha\": {\n      \"blocked_before_publish\": 2,\n      \"no_post_in_article_cache_window\": 1\n    },\n    \"chengdu\": {\n      \"blocked_before_publish\": 5,\n      \"published\": 4,\n      \"no_post_in_article_cache_window\": 3\n    },\n    \"chongqing\": {\n      \"published\": 4,\n      \"blocked_before_publish\": 2,\n      \"no_post_in_article_cache_window\": 1\n    },\n    \"dali\": {\n      \"blocked_before_publish\": 1\n    },\n    \"dalian\": {\n      \"blocked_before_publish\": 1\n    },\n    \"daqing\": {\n      \"blocked_before_publish\": 1\n    },\n    \"fuzhou\": {\n      \"published\": 1\n    },\n    \"guangzhou\": {\n      \"published\": 4,\n      \"dropped_before_pack\": 3,\n      \"no_post_in_article_cache_window\": 3,\n      \"blocked_before_publish\": 2\n    },\n    \"guiyang\": {\n      \"no_post_in_article_cache_window\": 1,\n      \"blocked_before_publish\": 1\n    },\n    \"hangzhou\": {\n      \"published\": 2,\n      \"dropped_before_pack\": 1,\n      \"blocked_before_publish\": 1\n    },\n    \"hongkong\": {\n      \"no_post_in_article_cache_window\": 1\n    },\n    \"jinan\": {\n      \"blocked_before_publish\": 1\n    },\n    \"kunming\": {\n      \"blocked_before_publish\": 2\n    },\n    \"lanzhou\": {\n      \"no_post_in_article_cache_window\": 2,\n      \"blocked_before_publish\": 1\n    },\n    \"lhasa\": {\n      \"no_post_in_article_cache_window\": 1\n    },\n    \"nanjing\": {\n      \"blocked_before_publish\": 1\n    },\n    \"nanning\": {\n      \"no_post_in_article_cache_window\": 1,\n      \"blocked_before_publish\": 1\n    },\n    \"qingdao\": {\n      \"blocked_before_publish\": 2\n    },\n    \"sanya\": {\n      \"blocked_before_publish\": 1\n    },\n    \"shanghai\": {\n      \"blocked_before_publish\": 10,\n      \"published\": 10,\n      \"no_post_in_article_cache_window\": 5\n    },\n    \"shenyang\": {\n      \"blocked_before_publish\": 2\n    },\n    \"shenzhen\": {\n      \"blocked_before_publish\": 3,\n      \"published\": 2\n    },\n    \"suzhou\": {\n      \"published\": 1,\n      \"blocked_before_publish\": 1\n    },\n    \"taipei\": {\n      \"no_post_in_article_cache_window\": 2\n    },\n    \"tianjin\": {\n      \"published\": 1\n    },\n    \"unknown\": {\n      \"published\": 1\n    },\n    \"urumqi\": {\n      \"blocked_before_publish\": 1\n    },\n    \"weifang\": {\n      \"no_post_in_article_cache_window\": 1\n    },\n    \"wuhan\": {\n      \"no_post_in_article_cache_window\": 2\n    },\n    \"xiamen\": {\n      \"published\": 1,\n      \"blocked_before_publish\": 1\n    },\n    \"xian\": {\n      \"blocked_before_publish\": 2\n    },\n    \"zhuhai\": {\n      \"no_post_in_article_cache_window\": 1\n    }\n  },\n  \"problem_accounts_sample\": [\n    {\n      \"account_id\": \"account_99e49497f6\",\n      \"account_name\": \"莫须有工厂\",\n      \"city_key\": \"beijing\",\n      \"sync_priority\": 10,\n      \"prefetch_count\": 2,\n      \"exporter_count\": 2,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"minos_club\",\n      \"account_name\": \"MINOS CLUB\",\n      \"city_key\": \"guangzhou\",\n      \"sync_priority\": 10,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"alldayonair\",\n      \"account_name\": \"全日在线俱乐部ALLDAYONAIR\",\n      \"city_key\": \"guiyang\",\n      \"sync_priority\": 10,\n      \"prefetch_count\": 32,\n      \"exporter_count\": 32,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"socialroom\",\n      \"account_name\": \"SOCIALROOM 康楽室\",\n      \"city_key\": \"hongkong\",\n      \"sync_priority\": 10,\n      \"prefetch_count\": 3,\n      \"exporter_count\": 3,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"wuhanprison\",\n      \"account_name\": \"WuhanPrison\",\n      \"city_key\": \"wuhan\",\n      \"sync_priority\": 10,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"blip\",\n      \"account_name\": \"Blip昙花一现\",\n      \"city_key\": \"chengdu\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"nuts_club\",\n      \"account_name\": \"坚果俱乐部 Nuts club\",\n      \"city_key\": \"chongqing\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 10,\n      \"exporter_count\": 10,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"244punkgroup\",\n      \"account_name\": \"244PunkGroup\",\n      \"city_key\": \"guangzhou\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"powderblack_pub\",\n      \"account_name\": \"POWDERBLACK末 PUB\",\n      \"city_key\": \"lanzhou\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 20,\n      \"exporter_count\": 20,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"powderblackdancefloor\",\n      \"account_name\": \"PowderBlackDanceFloor\",\n      \"city_key\": \"lanzhou\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"18_area18\",\n      \"account_name\": \"18区 AREA18\",\n      \"city_key\": \"lhasa\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 5,\n      \"exporter_count\": 5,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"radio\",\n      \"account_name\": \"双频Radio\",\n      \"city_key\": \"nanning\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 7,\n      \"exporter_count\": 7,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"no8pawnshop\",\n      \"account_name\": \"No8Pawnshop\",\n      \"city_key\": \"taipei\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 73,\n      \"exporter_count\": 73,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"account_eae77d1173\",\n      \"account_name\": \"开心舞厅\",\n      \"city_key\": \"weifang\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 25,\n      \"exporter_count\": 25,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"loop_infinity\",\n      \"account_name\": \"Loop Infinity\",\n      \"city_key\": \"zhuhai\",\n      \"sync_priority\": 8,\n      \"prefetch_count\": 36,\n      \"exporter_count\": 36,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"river_changsha\",\n      \"account_name\": \"River Changsha\",\n      \"city_key\": \"changsha\",\n      \"sync_priority\": 5,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"dada_shanghai\",\n      \"account_name\": \"Dada Shanghai\",\n      \"city_key\": \"shanghai\",\n      \"sync_priority\": 5,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"elevator\",\n      \"account_name\": \"Elevator上海\",\n      \"city_key\": \"shanghai\",\n      \"sync_priority\": 5,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"the_box\",\n      \"account_name\": \"THE BOX 盒子黑胶\",\n      \"city_key\": \"beijing\",\n      \"sync_priority\": 1,\n      \"prefetch_count\": 80,\n      \"exporter_count\": 80,\n      \"queue_count\": 0,\n      \"pack_count\": 0,\n      \"published_count\": 0,\n      \"coverage_status\": \"no_post_in_article_cache_window\"\n    },\n    {\n      \"account_id\": \"cueclub\",\n      \"account_name\": \"CueClub\",\n      \"city_key\": \"chengdu\",\n      \"sync_priority\":",
      "rank": 8,
      "index": "4"
    },
    {
      "title": "03_NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md",
      "link": "/source_pack/weekly_plan_deepresearch_20260519/03_NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md",
      "snippet": "# NEXT AGENT HANDOFF — HUAIDJ 周活小程序（完整接手）\n\nGenerated: 2026-05-19  \nAgent session: 周活小程序专项接手（不含图鉴主线实现）  \nRepo path: `C:\\code\\githubstar\\wechathtmldownload`（**非 Git 根**）\n\n## 1. Main Problem\n\n周活小程序已具备 OpenClaw 日更 runbook 与 `weekly-api-033` / 103 条发布，但 **lineup/活动字段识别准确率**仍不足（大量空 lineup + 历史误报被保守门禁打掉），且 **后端 payload 仍有 51 处 CDN URL 行**（前端已隐藏）。下一 agent 应在**不破坏 0 hard_fail 发布门**前提下，按计划提升识别与实体展示，并观测首次无人值守 OpenClaw cron。\n\n## 2. Scope\n\n### In scope\n\n- `apps\\weekly_activity_miniprogram\\`（8 页 + utils + tests）\n- `services\\weekly_activity_cloudrun\\` 的 **`/api/v1/weekly/*`** 只读 API\n- `tools\\stage7_rewrite\\` 周活管线：queue → OCR → DeepSeek → build API → repair → audit → deploy → upload\n- `run_openclaw_weekly_daily_publish.ps1` 与 release guardian\n- 本目录下 PLAN_A / PLAN_B 与三份 DELIVERABLE\n\n### Out of scope（除非用户明确要求）\n\n- 电子音乐图鉴 93k/47k 主线、Neo4j/Qdrant 写入、Next1000\n- 微信提审（人工决策）\n- 无界 `D:\\` 扫描、读取 secret\n\n## 3. Thread",
      "full_content": "# NEXT AGENT HANDOFF — HUAIDJ 周活小程序（完整接手）\n\nGenerated: 2026-05-19  \nAgent session: 周活小程序专项接手（不含图鉴主线实现）  \nRepo path: `C:\\code\\githubstar\\wechathtmldownload`（**非 Git 根**）\n\n## 1. Main Problem\n\n周活小程序已具备 OpenClaw 日更 runbook 与 `weekly-api-033` / 103 条发布，但 **lineup/活动字段识别准确率**仍不足（大量空 lineup + 历史误报被保守门禁打掉），且 **后端 payload 仍有 51 处 CDN URL 行**（前端已隐藏）。下一 agent 应在**不破坏 0 hard_fail 发布门**前提下，按计划提升识别与实体展示，并观测首次无人值守 OpenClaw cron。\n\n## 2. Scope\n\n### In scope\n\n- `apps\\weekly_activity_miniprogram\\`（8 页 + utils + tests）\n- `services\\weekly_activity_cloudrun\\` 的 **`/api/v1/weekly/*`** 只读 API\n- `tools\\stage7_rewrite\\` 周活管线：queue → OCR → DeepSeek → build API → repair → audit → deploy → upload\n- `run_openclaw_weekly_daily_publish.ps1` 与 release guardian\n- 本目录下 PLAN_A / PLAN_B 与三份 DELIVERABLE\n\n### Out of scope（除非用户明确要求）\n\n- 电子音乐图鉴 93k/47k 主线、Neo4j/Qdrant 写入、Next1000\n- 微信提审（人工决策）\n- 无界 `D:\\` 扫描、读取 secret\n\n## 3. Thread Boundary（用户明确要求）\n\n**小程序是小程序，图谱是图谱。** 本线程默认只改/只论周活侧；图谱仅作为计划二中的 **实体解析与 verified 知识下行** 被引用，不在此线程展开图鉴管线实现。\n\n## 4. Current Reality（已验证 2026-05-19）\n\n### Confirmed\n\n| 层 | 状态 |\n|----|------|\n| 远端后端 | `weekly-api-033`，103 条，分页 reconcile 103/103，missing/extra 0/0 |\n| 本地 API 包 | `WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519` |\n| 小程序开发版 | `2026.05.19.8`，desc `每日自动源更新103条-runbook守卫通过` |\n| release guardian | ok=true；visibleHits=0；**backendRawHits=51** |\n| 小程序单测 | 24/24 pass |\n| daily queue | 存在，~7.8h 内刷新，8820 rows |\n| OpenClaw wrapper | 存在；dry-run + 手动全跑已通过；**定时首跑未观测** |\n\n### Hypotheses\n\n- lineup 空的多半是 **保守 repair + 弱 OCR 覆盖 + outside_date_window 漏斗**，不单是 LLM 质量\n- Linux cron 可能仍跑 `huaidj-weekly-openclaw-stable.sh`，**未必**已切到 Windows `run_openclaw_weekly_daily_publish.ps1`\n\n### Unverified\n\n- 真机全面 smoke（自动化远端检查已过）\n- 微信审核状态\n- cron 与 wrapper 一致性\n\n## 5. Architecture（周活-only）\n\n```\nDocker exporter → LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\n  → weekly_activity_next_week_pipeline.ps1\n  → WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD\n  → repair/audit/materialize\n  → bake/deploy → weekly-api-033\n  → 小程序 requestApi → format.compactItem → UI\n```\n\n四层状态必须分开：`本地包修复` / `CloudRun remote-effective` / `小程序已上传` / `微信已提审`。\n\n## 6. Key Code Map\n\n| 路径 | 职责 |\n|------|------|\n| `apps\\weekly_activity_miniprogram\\utils\\api.js` | 云托管→公网→静态→mock |\n| `apps\\weekly_activity_miniprogram\\utils\\format.js` | 展示契约、URL 过滤、compactItem |\n| `apps\\stage7_rewrite\\scripts\\enrich_weekly_activity_pack_with_deepseek.py` | Flash + Pro 风险二审 |\n| `scripts\\archive_old\\enrich_weekly_activity_pack_with_poster_ocr.py` | OCR → source_evidence |\n| `scripts\\archive_old\\build_weekly_activity_miniprogram_api.py` | 物化 current.json（**dj_bio_lines 恒 []**） |\n| `repair_weekly_lineup_address_time_fields.py` | lineup/地址/时间保守修复 |\n| `audit_weekly_lineup_address_time.py` | strict hard_fail |\n\n## 7. Known Issues（优先级）\n\n| ID | 严重度 | 问题 |\n|----|--------|------|\n| MP-1 | P0 | backend 51 URL 行（`description_original_lines`） |\n| MP-2 | P1 | ~61% 发布条无 lineup（audit missing_lineup 63/103） |\n| MP-3 | P1 | venue/artist 仅 limit=100 |\n| MP-4 | P2 | city→index 深链未接 |\n| MP-5 | P2 | cron 与 wrapper 一致性未确认 |\n| MP-6 | P3 | 文档漂移（INDEX 仍写 107/api-031） |\n\n## 8. Work Performed（本会话）\n\n- 全量理解周活小程序代码（~4.5k 行应用代码）、CloudRun weekly API、管线文档\n- 只读：release guardian、URL 51 扫描、远端 reconcile、24 单测\n- 产出：计划一/计划二、三份交付物、本接手包（Markdown + HTML）\n\n**未修改** 业务代码。\n\n## 9. Verification Status\n\n| 检查 | 结果 |\n|------|------|\n| guardian @ 20260519 包 | ok |\n| 远端 current+enrichment | 103/103 |\n| node --test tests/*.test.cjs | 24 pass |\n| DevTools E2E | 本机未 launch（非阻塞） |\n\n## 10. Next Best Entry\n\n### 立即（只读）\n\n```powershell\npowershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\pc\\.codex\\skills\\huaidj-weekly-release-guardian\\scripts\\check_weekly_release_guard.ps1 -CurrentReleaseDir D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519\n```\n\n### 按计划实施（用户批准后）\n\n1. **P0** Golden 集 + baseline（见 PLAN_A §1.6）\n2. **P0** OpenClaw 首跑观测（见 DELIVERABLE_OPENCLAW）\n3. **P0** URL 清洗设计评审 → 改 build（见 DELIVERABLE_URL_TRACE）\n4. **L0** 图谱契约（见 PLAN_B）— 与计划一并行\n\n### Dry-run wrapper（不写远端）\n\n```powershell\npowershell -ExecutionPolicy Bypass -File C:\\code\\githubstar\\wechathtmldownload\\tools\\stage7_rewrite\\run_openclaw_weekly_daily_publish.ps1 -DryRun -SkipBuild -ApiDir D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519 -PackDir D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_DEEPSEEK_20260519\n```\n\n## 11. Warnings / Pitfalls\n\n- 勿把图鉴 47k/Neo4j 进度当作周活条数\n- 勿因新包条数更多就 deploy（104→103 重复修复教训）\n- smoke 默认 limit=100 不足以证明全量条数\n- `missing_lineup` **不是** hard_fail；提召回需 golden 评测，不能单放宽 audit\n- `dj_bio_lines` 空是 **产品+代码双锁**；开 bio 必须走 verified 路径（计划二）\n\n## 12. Related Artifacts\n\n| 路径 | 说明 |\n|------|------|\n| `docs\\weekly-miniprogram-handoff-20260519\\` | 本接手包 |\n| `C:\\Users\\pc\\.cursor\\projects\\empty-window\\url-hits-20260519.json` | 51 行 URL 明细 |\n| `NEXT_AGENT_HANDOFF_20260519_OPENCLAW_DAILY_RELEASE.md` | 上游 OpenClaw 发布 handoff |\n\n## 13. HTML Companion\n\n- `docs\\weekly-miniprogram-handoff-20260519\\html\\NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.html`\n- 同目录下各 PLAN/DELIVERABLE 的 `.html`\n\n## 14. OpenHuman Import\n\n- imported: no（本会话未执行）\n",
      "rank": 3,
      "index": "5"
    },
    {
      "title": "05_DELIVERABLE_CODE_DOC_AUDIT.md",
      "link": "/source_pack/weekly_plan_deepresearch_20260519/05_DELIVERABLE_CODE_DOC_AUDIT.md",
      "snippet": "# 交付物：周活小程序代码与文档只读审计\n\nAudited: 2026-05-19  \nScope: mini-program + weekly CloudRun API + weekly docs（不含图鉴实现）\n\n## 1. 现场验证\n\n| 项 | 结果 |\n|----|------|\n| release guardian @ 20260519 包 | ok=true |\n| backendRawHits / visibleHits | 51 / 0 |\n| 远端 current + enrichment | 103 / 103 |\n| 小程序单测 | 24/24 pass |\n| DevTools E2E | 本机 cliPath 失败（非阻塞） |\n\n## 2. 代码地图（~4500 行应用代码）\n\n| 文件 | 行数 | 结论 |\n|------|------|------|\n| utils/api.js | 453 | 四级 fallback，强 |\n| utils/format.js | 542 | 展示契约，掩盖 51 URL |\n| pages/index/index.js | 462 | 全量分页；onLoad 无 query |\n| pages/venue/venue.js | 64 | limit=100，注释未实现分页 |\n| utils/posterPool.js | 109 | 48/24 海报池，有测 |\n| tests/*.cjs | ~1500 | 24 pass |\n\n无自定义组件；8 页面。\n\n## 3. CloudRun weekly API\n\n- 只读文件 API；`dataStore.dedupeItems` 服务端去重\n- 小程序用：current, items/:id, batch, source/:hash, poster/:id, cities, dates\n- Stage7 路由同服但小程序未调用\n\n## 4. 缺陷清单\n\n| ID | 严重度 | 问题 |\n|----|--------|------|\n| MP-",
      "full_content": "# 交付物：周活小程序代码与文档只读审计\n\nAudited: 2026-05-19  \nScope: mini-program + weekly CloudRun API + weekly docs（不含图鉴实现）\n\n## 1. 现场验证\n\n| 项 | 结果 |\n|----|------|\n| release guardian @ 20260519 包 | ok=true |\n| backendRawHits / visibleHits | 51 / 0 |\n| 远端 current + enrichment | 103 / 103 |\n| 小程序单测 | 24/24 pass |\n| DevTools E2E | 本机 cliPath 失败（非阻塞） |\n\n## 2. 代码地图（~4500 行应用代码）\n\n| 文件 | 行数 | 结论 |\n|------|------|------|\n| utils/api.js | 453 | 四级 fallback，强 |\n| utils/format.js | 542 | 展示契约，掩盖 51 URL |\n| pages/index/index.js | 462 | 全量分页；onLoad 无 query |\n| pages/venue/venue.js | 64 | limit=100，注释未实现分页 |\n| utils/posterPool.js | 109 | 48/24 海报池，有测 |\n| tests/*.cjs | ~1500 | 24 pass |\n\n无自定义组件；8 页面。\n\n## 3. CloudRun weekly API\n\n- 只读文件 API；`dataStore.dedupeItems` 服务端去重\n- 小程序用：current, items/:id, batch, source/:hash, poster/:id, cities, dates\n- Stage7 路由同服但小程序未调用\n\n## 4. 缺陷清单\n\n| ID | 严重度 | 问题 |\n|----|--------|------|\n| MP-1 | P0 | 51 URL 在 description_original_lines |\n| MP-2 | P1 | 63/103 missing_lineup |\n| MP-3 | P1 | venue/artist 仅 100 条 |\n| MP-4 | P2 | city→index 深链断裂 |\n| MP-5 | P2 | 三处去重可能漂移 |\n| MP-6 | P3 | miniprogram-ci 未入 package.json |\n| MP-7 | P3 | DevTools E2E 环境未就绪 |\n\n## 5. 文档审计\n\n### 权威\n\n- NEXT_AGENT_HANDOFF_20260519_OPENCLAW_DAILY_RELEASE.md\n- OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md\n- OPENCLAW_AUTOMATION.md（顶部口径）\n- SSOT.md weekly 专节\n- WEEKLY_ACTIVITY_PUBLISHED_SCHEMA_V1\n\n### 漂移\n\n| 文档 | 应为 |\n|------|------|\n| DOCUMENTATION_INDEX.md | api-033 / 103 |\n| current-runtime.md weekly 段 | 同上 |\n| weekly_miniprogram_final_project_summary | 103 非 107 |\n\n## 6. 管线契约\n\n| 门 | 构建 | 小程序 | 一致 |\n|----|------|--------|------|\n| 无 source URL | filter | READY only | ok |\n| needs_ocr_review | filter | 不展示 | ok |\n| URL in UI | 未清 build | format 滤 | **分裂** |\n| dj_bio | 恒 [] | 不展示 | 设计 |\n\n## 7. lineup 审计数据点\n\n- repair 20260519：`lineup_cleared` 34\n- audit materialized：`missing_lineup` 63\n- biofix2 历史：100 条中 16 有 lineup，hard_fail 0\n\n## 8. 建议下一动作（只读优先）\n\n1. guardian + 远端 reconcile（每日）\n2. 确认 cron 脚本与 wrapper 一致性\n3. 用户批准后：P0 golden（计划一）+ URL 清洗（本交付物）\n",
      "rank": 5,
      "index": "6"
    },
    {
      "title": "research_query_plan_a.md",
      "link": "/source_pack/weekly_plan_deepresearch_20260519/research_query_plan_a.md",
      "snippet": "# LDR 深度研究任务 — 计划一：周活小程序识别准确率\n\n角色：资深数据管线架构师 + OCR/LLM 评测工程师 + 微信小程序产品工程师。\n\n## 硬约束（必须遵守）\n\n1. **只根据 source_pack 内文件**回答；不得臆造运行结果、条数、部署版本。\n2. 当前权威事实（若 source 中有更新以 source 为准）：`weekly-api-033`，103 条，`2026-05-19..2026-06-02`；backendRawHits=51 URL；missing_lineup 约 63/103；visibleHits=0。\n3. 产品原则：**宁可空不可错**；无 evidence 不展示 lineup/bio；**不得**建议放松 duplicate/source URL 硬门。\n4. DeepSeek 生产策略（来自 matrix）：Flash no-thinking 全量 + Pro no-thinking 风险行；**禁止** thinking-enabled 用于 JSON 物化。\n5. 输出为 **candidate research**，最终需 HOLD_FOR_HERMES_DECISION；不得当作已实施变更。\n\n## 研究目标\n\n在现有 `PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md` 基础上，产出**可落地、可验收**的强化版实施计划 v2，重点：\n\n1. **字段级置信 schema**（YAML/JSON 示例）：`field`, `confidence`, `tier` (show/show_with_hint/hide), `evidence[]`, `provenance` (ocr/body/registry/atlas_verified)\n2. **Golden Set 规范**：80–120 条首批标注维度、标注界面/文件格式、每周增量流程、hard_error 定义\n3. **分阶段 OKR（P0–P4）**：每阶段 2–4 周；交付物、负责人角色、退出门禁、依赖脚本路",
      "full_content": "# LDR 深度研究任务 — 计划一：周活小程序识别准确率\n\n角色：资深数据管线架构师 + OCR/LLM 评测工程师 + 微信小程序产品工程师。\n\n## 硬约束（必须遵守）\n\n1. **只根据 source_pack 内文件**回答；不得臆造运行结果、条数、部署版本。\n2. 当前权威事实（若 source 中有更新以 source 为准）：`weekly-api-033`，103 条，`2026-05-19..2026-06-02`；backendRawHits=51 URL；missing_lineup 约 63/103；visibleHits=0。\n3. 产品原则：**宁可空不可错**；无 evidence 不展示 lineup/bio；**不得**建议放松 duplicate/source URL 硬门。\n4. DeepSeek 生产策略（来自 matrix）：Flash no-thinking 全量 + Pro no-thinking 风险行；**禁止** thinking-enabled 用于 JSON 物化。\n5. 输出为 **candidate research**，最终需 HOLD_FOR_HERMES_DECISION；不得当作已实施变更。\n\n## 研究目标\n\n在现有 `PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md` 基础上，产出**可落地、可验收**的强化版实施计划 v2，重点：\n\n1. **字段级置信 schema**（YAML/JSON 示例）：`field`, `confidence`, `tier` (show/show_with_hint/hide), `evidence[]`, `provenance` (ocr/body/registry/atlas_verified)\n2. **Golden Set 规范**：80–120 条首批标注维度、标注界面/文件格式、每周增量流程、hard_error 定义\n3. **分阶段 OKR（P0–P4）**：每阶段 2–4 周；交付物、负责人角色、退出门禁、依赖脚本路径\n4. **现有脚本映射表**：`enrich_weekly_activity_pack_with_deepseek.py`, `repair_weekly_lineup_address_time_fields.py`, `audit_weekly_lineup_address_time.py`, `build_weekly_activity_miniprogram_api.py`, `evaluate_weekly_deepseek_prompt_matrix.py` — 每项改什么、加什么测试\n5. **OCR+LLM 三层验证**细化：L-A 硬门 / L-B 软分 / L-C 金标；与 `yellowpage_gate_v3` 对齐\n6. **URL 51 债**：build 层清洗方案（不改 format.js 掩盖）\n7. **风险与不做清单**：明确拒绝的方案（LLM 自由 bio、向量猜 lineup 等）\n\n## 输出结构（Markdown）\n\n1. 执行摘要（5 条以内）\n2. 现状与根因（证据引用 source 文件名）\n3. 目标架构与数据流（可用 ASCII）\n4. 字段置信 schema（完整示例）\n5. Golden Set 规范\n6. 分阶段 OKR 表（含度量 baseline→目标）\n7. 脚本/模块改造清单（优先级 P0/P1/P2）\n8. 评测与回归命令（PowerShell/python 示例）\n9. 与计划二的接口点（仅契约，不展开图鉴实现）\n10. 待用户拍板决策表（≤5 项）\n\n请用**简体中文**撰写，技术术语可保留英文。篇幅充实但避免重复 handoff 全文。\n",
      "rank": 9,
      "index": "7"
    }
  ]
}
```

# 周活小程序识别准确率强化实施计划 v2（HOLD_FOR_HERMES_DECISION）

## 1. 执行摘要

- **核心目标**：在保持“宁可空不可错”与现有 0 hard_fail 门禁前提下，将已发布活动有 lineup 且通过 strict 的比例从 ~39%（40/103）提升至 55–65%，同时消除后端 51 条 CDN URL 行，建立可复现的字段置信分层与 Golden Set 评测闭环。
- **关键措施**：引入字段级置信 schema（show / show_with_hint / hide）与 evidence 溯源；实施 Golden Set 首批 80–120 条人工标注及每周增量；将 repair 阶段由硬清空改为评分制；在 build 层清洗 URL；深化 OCR+L A 硬门·L B 软分·L C 金标三层验证。
- **生产模型策略**：维持 DeepSeek Flash no‑thinking 全量 + Pro no‑thinking 风险行，禁止 thinking‑enabled 用于 JSON 物化 [2]。
- **时间线**：分 P0–P4 共 12 周，首两周产出 Golden Set 与 baseline 报告。
- **风险边界**：不放松 duplicate/source URL 硬门；不引入 LLM 自由 bio；不采用向量猜 lineup 等不可解释方案。

## 2. 现状与根因（证据引用）

### 2.1 当前数字

| 指标 | 数值 | 证据 |
|------|------|------|
| 已发布活动总数 | 103 | `weekly-api-033` [5] |
| 有 lineup（strict 通过） | ~40（约 39%） | [1] 北极星指标推算 |
| missing_lineup 审计计数 | 63/103 | [6] audit materialized |
| backendRawHits（URL） | 51（仅 `description_original_lines`） | [3] 实测结果 |
| visibleHits | 0 | [6] release guardian |
| 发布条数（管道审计另一次） | 104 | [4]（差异源于窗口/时间点，以 103 为准） |
| prefetch 入队 | 8819 | [4] |
| OCR 实跑/跳过 | 94 / 1631 | [4] |
| API 层过滤：outside_date_window | 1613 | [4] |
| blocked_before_publish 账号 | 49 | [4] |

### 2.2 根因链

- **lineup 大量缺失**（61%）：主因并非单纯 LLM 抽取能力不足，而是 **保守 repair 门 + OCR 覆盖率低 + 日期窗口漏斗** 三重叠加。DeepSeek 提取的 lineup 候选在 `repair_weekly_lineup_address_time_fields.py` 阶段被 `bio gate`、`event_context` 硬清空 [1][6]。同时海报 OCR 由于覆盖面窄、仅前 N 图、preflight 阻断，未能提供足够 evidence [1][4]。最终 publication 窗口又过滤了大量旧活动，导致基础集偏小。
- **后端 51 条 URL 行**：OCR/正文拆行后写入了 `description_original_lines`，未在 build 阶段剥离 CDN URL，仅在前端 `format.js` 过滤，造成后端冗余 [3]。
- **缺少置信分层**：当前 pipeline 只有二元判定（展示/不展示），无法对“有部分证据但不够强”的字段进行差异化处理（如 `show_with_hint`），导致大量 borderline 案例直接被藏匿 [1]。
- **无 Golden Set 评测**：没有人工标注的标准集，现有 `evaluate_weekly_deepseek_prompt_matrix.py` 仅基于离线文章分数，无法量化线上精准率、召回率 [2]。

## 3. 目标架构与数据流

```
L0 源       HTML + 海报 ──OCR──> source_evidence.md
                          │
L1 确定性   日期 regex、registry 候选、DJ 邻域
                          │
L2 模型     Flash no-thinking (全量)
                │ 风险行 → Pro no-thinking (yellowpage_gate_v3)
                │ 输出 field_evidence_refs + confidence
                          │
L3 裁决     merge → repair(评分制) → audit(strict)
                │
             build API (清洗 URL) → tier 注入
                │
             CloudRun 只读 /api/v1/weekly/*
                │
             小程序 format.compactItem → UI (分层展示)
```

- **核心改变**：L2 模型输出增加 `confidence` 与 `evidence[]`；L3 repair 从清除改为保留软分；build 增加 URL 过滤器。
- **不变的硬门**：duplicate 0，source URL 硬门，missing_lineup 本身不设置为 hard_fail [1][5]。

## 4. 字段级置信 schema

### 4.1 通用结构

物品化时每条活动字段均附置信对象（JSON），示例：

```json
{
  "itemId": "some-club:event-hash",
  "lineup_artists": {
    "confidence": 0.86,
    "tier": "show",
    "evidence": [
      {
        "type": "ocr",
        "image_id": "img_abc",
        "quote": "DJ LINEUP: A, B, C"
      },
      {
        "type": "body",
        "quote": "w/ Artist A, Artist B"
      }
    ],
    "provenance": "ocr+body"
  },
  "event_time": {
    "confidence": 0.95,
    "tier": "show",
    "evidence": [
      {
        "type": "body",
        "quote": "2026-06-01 22:00"
      }
    ],
    "provenance": "body"
  },
  "address": {
    "confidence": 0.40,
    "tier": "hide",
    "evidence": [],
    "provenance": "none"
  }
}
```

### 4.2 字段定义

| 字段 | 置信度来源 | 三层 tier 判定 |
|------|-----------|----------------|
| `event_time` / `event_date` | regex + 窗口校验 + 非冲突 | confidence≥0.8 → show；0.5‑0.8 → show_with_hint；<0.5 → hide |
| `lineup_artists` | OCR 海报区块 + body cue + registry 邻域 | evidence 非空且无冲突 → show；仅 body cue 或部分匹配 → show_with_hint；无 evidence 或明确否决 → hide [1] |
| `address` | registry 优先 + OCR 地址过滤 | registry/atlas verified → show；OCR 低置信→ hide |
| `bio` / `dj_bio_lines` | 仅 `registry bio_manual` 或 atlas verified | 缺一不可展示（当前恒 [] 不变，需计划二解锁）[5] |
| `venue_name` | 同 address 逻辑 | 有 registry/cue → show；纯 OCR 猜测 → hide |

**provenance 枚举**：`ocr` | `body` | `registry` | `atlas_verified` | `merged` | `none`

## 5. Golden Set 规范

### 5.1 首批构建

- **规模**：80–120 条已发布/候选活动，覆盖 4–5 个城市、有/无 lineup、纯文字/图重/聚合子等类型，确保`title_date_mismatch`、`lineup_noise`、`image_heavy`、`aggregate_child` 四类样本均衡 [1][2]。
- **标注维度**：
  - 活动日期/时间（start/end，误差 0 天为正确）
  - lineup 集合（人名列表）
  - 地址/场地名称
  - 是否应该展示（全局判定：show / show_with_hint / hide）
  - hard_error 标记：若管线 output 明确与标注相悖且展示，计为 hard_error（一票否决该版本）[1]。
- **标注界面/格式**：使用 JSON Lines 文件（`golden_set_v1.jsonl`），每条包含活动 ID、原始文本摘要（脱敏）、标注字段、标注人、时间戳。配备简易 Web 标注工具或 Excel 导入。
- **增流**：每周从当周已发布 & 被过滤活动中随机抽取 20‑30 条补充，并复注，维持总数 120‑150 条，防止过时。

### 5.2 度量闭环

每阶段结束后，跑以下度量：

```
precision = |shown ∩ gold_lineup| / |shown|
recall    = |shown ∩ gold_lineup| / |gold_lineup|
hard_error_rate = (hard_error 活动数) / (gold 总数)
```

目标：精准率 ≥92%，召回率 ≥75% [1]。

## 6. 分阶段 OKR 表

| 阶段 | 周期 | 交付物 | 负责人角色 | 度量 baseline → 目标 | 退出门禁 | 依赖脚本 |
|------|------|--------|------------|----------------------|----------|----------|
| **P0 度量** | 2 周 | Golden Set 80 条、baseline 报告（精准/召回/URL 计数） | 数据标注负责人 + 评测工程师 | 未测 → 精准≥92%? 召回≥75%? | Golden Set inter‑annotator agreement >90%；baseline 报告通过 review | `evaluate_weekly_deepseek_prompt_matrix.py`（扩展金标评测） |
| **P1 证据** | 3 周 | DeepSeek 输出增加 `field_evidence_refs` 与 `confidence`；OCR 覆盖率提升试点；URL 清洗生产上线 | OCR 管道工程师 + 后端 | OCR 实跑从 94/1631 提升到 ≥200 活动有 OCR；backendRawHits 51→0 | 所有模型输出必须包含 `evidence` 且 schema 校验通过；guardian 中 `backendRawHits=0` 升为硬门 [3] | `enrich_weekly_activity_pack_with_deepseek.py`、build 脚本、ocr 脚本 |
| **P2 候选+裁决** | 4 周 | repair 评分制替代硬清空；event_context 评分化；regex 候选器；Pro 风险扩面（有候选但 Flash 空） | 管线工程师 + 产品 | missing_lineup 从 63 降至 ≤45；lineup 精准率≥90%（P0 金标） | repair 改动后不引入 hard_error；audit strict 通过 | `repair_weekly_lineup_address_time_fields.py`、`audit_weekly_lineup_address_time.py`、`enrich_weekly_activity_pack_with_deepseek.py` |
| **P3 展示** | 3 周 | 小程序端根据 tier 展示 `show` / `show_with_hint` / `hide`；verified bio 接口（需计划二下行） | 前端工程师 + 后端 | 有 show_with_hint 的活动≥30%；无硬错 | 前端新 tier 展示通过 UI review；不影响旧版 0 hard_fail | `format.js`、`build_weekly_activity_miniprogram_api.py`、api 层 |
| **P4 闭环** | 持续 | 每周金标增量 + 人工复核 → registry 修正；OCRed 结果回流优化 [1] | 管线 + 图谱团队 | 每周 recall 增速 ≥2% | 无回退，连续 4 周 recall 不降 | 全部 |

**说明**：所有基线数据来自 [1]、[3]、[4]、[6]；目标值基于 [1] 北极星建议适度调整。

## 7. 脚本/模块改造清单

| 脚本 | 优先级 | 改动内容 | 新增测试 |
|------|--------|----------|----------|
| `enrich_weekly_activity_pack_with_deepseek.py` | P1 | 在 `yellowpage_gate_v3` 输出基础上，添加 `confidence` 计算（基于 evidence 密度/类型）与 `evidence[]` 字段；保留 Flash 主干，Pro 风险行不变 [2] | 单元测试：confidence 范围、evidence schema；集成测试：golden 回归 |
| `repair_weekly_lineup_address_time_fields.py` | P2 | 移除 `lineup_cleared` 全局清除；改为按行评分，保留评分 ≥0.6 的 lineup；bio gate 改为降级而非清除 [1] | 测试评分逻辑边界；回归已修复的假阴性案例 |
| `audit_weekly_lineup_address_time.py` | P2 | 纳入 golden set 比对逻辑，输出 hard_error 标记；保留 strict 硬门，增加缺失 lineup 的统计但不成硬 fail [1] | 金标一致性测试；无重复冲突测试 |
| `archive_old/build_weekly_activity_miniprogram_api.py` | P1 | 写入 `description_original_lines` 前增加 URL 清洗（移除 `mmbiz.qpic.cn` 等 CDN 行），规则与 `format.js` DISPLAY_URL_RE 同构 [3] | 验证清洗后 rawHits=0；不误删 cover_image_url |
| `evaluate_weekly_deepseek_prompt_matrix.py` | P0 | 扩展为可接收 golden set 文件，输出精准/召回分字段报告 | 金标评测 cli 测试；对比不同 prompt 效果 |
| `check_weekly_release_guard.ps1` | P1 | 新增门禁：`backendRawHits` 必须为 0 否则阻止发布 [3] | — |

## 8. 评测与回归命令

### 8.1 Golden Set 评测

```powershell
# 运行对 golden_set_v1.jsonl 的评测
python tools\stage7_rewrite\scripts\evaluate_weekly_deepseek_prompt_matrix.py `
  --golden-file D:\downstream_results\golden\golden_set_v1.jsonl `
  --prompt yellowpage_gate_v3 `
  --models deepseek-v4-flash deepseek-v4-pro `
  --output reports\golden_baseline_202605XX.json
```

### 8.2 全量回归（包含 URL 清洗验证）

```powershell
# 运行 guardian，backendRawHits 必须为 0
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1 `
  -CurrentReleaseDir D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD

# Python 单元测试（管线）
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api `
  tools.stage7_rewrite.tests.test_repair_weekly_lineup_address_time_fields `
  tools.stage7_rewrite.tests.test_weekly_activity_deepseek_enrichment -v
```

### 8.3 小程序端回归

```powershell
cd apps\weekly_activity_miniprogram
node --test tests/*.test.cjs
```

## 9. 与计划二的接口点

当前计划一专注于周活管线识别与展示层。与计划二（电子音乐图鉴）的耦合仅限以下契约，具体实现不在本计划展开 [5]：

| 契约点 | 周活侧需求 | 计划二提供 |
|--------|------------|------------|
| Verified artist bio | 需 `dj_bio_lines` 展示，但必须来自可信源 | 提供 Atlas verified bio 下行接口（JSON），含 `artist_id`、`bio_manual`、`image_url`、验证时间戳 |
| Artist name 解析 | 周活 lineup 识别后需确认人名是否存在 | 计划二提供 artist name resolution API（匹配 known alias → canonical id） |
| Venue 信息增强 | `show` tier 地址可附场地描述 | 计划二按 `venue_id` 或 `account_id` 返回 registry 中的场地详情 |
| Golden Set 共享 | 标注中部分边界案例需复盘 | 计划二提供图谱中已知的 DJ 名单以辅助标注一致性 |

**接口格式示例**（计划二需实现）：
`GET /atlas/verify/artist?name=Anyma` → `{ "canonical_id": "...", "verified": true, "bio_manual": "...", "source": "resident_advisor,beatport", "last_updated": "..." }`

周活侧在获取 verified bio 后，将在 API 构建时填充 `dj_bio_lines`（需产品批准）[1][5]。

## 10. 待用户拍板决策表

| 决策项 | 选项 A（推荐） | 选项 B | 依赖/风险 |
|--------|---------------|--------|-----------|
| 1. **URL 清洗位置** | 在 build 层（Python）清洗，与前端规则同步，gate 为 0 [3] | 仅维持前端过滤，不处理后端 | 推荐 A：可降低 payload 浪费，且后端不再携带冗余 |
| 2. **repair 评分制实施强度** | 先试点 2 城市，观察 1 周 golden 回归后全量 | 直接全量推 | 推荐 A：保守，避免一次引入大量硬错误 |
| 3. **OCR 投入力度** | 牺牲部分非优先账号，集中海报 OCR 给 top 50 账号 | 对所有文章无差别 OCR | 推荐 A：有限算力下提升高价值活动证据 [4] |
| 4. **show_with_hint 的 UI 形态** | 前端在 lineup 空缺处显示“部分艺人待确认，查看原文”，并指向 source 页 | 直接降级到 hide（维持现状） | 需产品与设计评审；推荐 A 可在不误导前提下提升信息量 |
| 5. **bio 展示解锁时机** | 待计划二 verified 接口可用且通过 2 周回测后开放 | 解锁但允许直接展示 DeepSeek 生成的 bio | 禁止 B，因为违原则 [1]；推荐 A 符合图谱下行策略 [5] |

---

*此文档为候选研究，所有变更需经用户审批后进入实施，当前状态：**HOLD_FOR_HERMES_DECISION**。*
