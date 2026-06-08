# Atlas 全量修复交接给 WSL2 DeepSeekTUI

updated_at: 2026-05-22 03:18 +08:00  
sender: Codex  
receiver: WSL2 DeepSeekTUI / `pc_deepseek_tui`  
repo: `C:\code\githubstar\wechathtmldownload`  
branch: `feature/weekly-integrated-bridge`

## Lifecycle note - 2026-05-23

This handoff remains active evidence for the Atlas full-run repair slice and for T6 DeepSeekTUI sidecar work, but it is no longer the latest serving-candidate authority by itself. It predates the later 2026-05-22 12:14 V2 public graph recovery and the 2026-05-22 23:48 DJ-complete activity-aware participant-delta v2 candidate.

For current Atlas serving decisions, read `docs\current-runtime.md`, `docs\DOCUMENTATION_INDEX.md`, and `reports\ATLAS_DJ_GRAPH_COMPLETION_CANDIDATE_20260522.md` first. The current latest local DJ-first public-safe candidate is `reports\atlas_serving_activity_participant_candidate_139123_publicsafe_djcomplete_v2_20260522-2335\atlas_serving.sqlite`. DeepSeekTUI remains a draft/research sidecar and this handoff does not authorize deploy, production pointer updates, graph/vector/database writes, CloudRun, mini-program upload/review, browser/provider runs, or secret reads.

## 1. Main problem

Atlas 不是普通文章图谱，而是“中国地下电子音乐 DJ 关系网络 + 历史演出档案”；当前最重要的工作是把本地 `atlas.sqlite` 里的活动、DJ、场地、厂牌和证据关系全量转成可搜索、可 3D 图谱浏览、同时可公开部署且不泄漏原始资产的 serving read model。

## 2. Scope

In scope:

- Atlas DJ-first serving read model。
- DJ 作为核心节点：历史演出、经常同台、常见场地、厂牌/crew、公开账号和证据链。
- 公开站点安全边界：绝不把原始 URL、公众号原文路径、raw HTML、raw JSON、article UID 直接放进前端公开库。
- 给 DeepSeekTUI 留一个可读、可继续研究的事实包。

Out of scope:

- 没有部署到 `huaidj.club`。
- 没有改 Cloudflare / Turnstile。
- 没有远程服务器写入。
- 没有用付费 LLM、没有重新爬公网、没有读 `.env` / cookie / token。
- 私有 aggressive repair 库不能直接上线。

## 3. Current reality

### Confirmed

- 严格公开 serving artifact 在本 03:18 交接切片中已生成；最新候选需见上方 lifecycle note：
  - `reports\atlas_serving_read_model_20260522\atlas_serving.sqlite`
  - 约 `1.72 GB`
  - raw events: `608,678`
  - public-safe performance events: `467,769`
  - DJ profiles: `51,593`
  - DJ-event edges: `1,104,301`
  - directed DJ relation edges: `611,140`
  - search docs: `547,374`
  - graph windows: `51,593`
- 已修复一个关键全量缺陷：旧 event id 只按 title/time/place 合并，导致大量事件被折叠。现在 event id 使用 `source + row_pk + evid + title/time/place` 哈希，避免 60 万 events 进入 serving 时被压成小集合。
- 已修复酒水/产品噪音：event-level product/alcohol gate 后，`wine_search_hits=0`。
- 严格公开库 schema 没有暴露 forbidden raw 字段：
  - `source_url`: `0`
  - `archive_raw_html_path`: `0`
  - `raw_json`: `0`
  - `article_uid`: `0`
  - `public_url_allowed != 0`: `0`
  - `mp.weixin/raw.html/D:/` hits: `0`
- MaFoL 严格公开验证：
  - `149` events
  - `108` collaborators
  - graph window exists
  - FTS5 搜索 spot check p50 `1.163ms`, max `42.303ms`
- 私有 aggressive repair candidate 已生成：
  - `reports\atlas_serving_repair_full_private_20260522\atlas_serving.sqlite`
  - 约 `2.08 GB`
  - performance events: `538,034`
  - DJ profiles: `55,791`
  - DJ-event edges: `1,415,016`
  - directed DJ relation edges: `772,998`
  - search docs: `623,336`
  - graph windows: `55,791`
  - 比严格公开库多 `70,265` events、`4,198` DJ profiles、`310,715` DJ-event edges、`161,858` relation edges。
- MaFoL 私有候选验证：
  - `196` events
  - `138` collaborators
- SHCR / BYYB / BAIHUI / CDCR 已按用户补充口径视作电台/媒体相关，不是普通噪音删除目标。

### Hypotheses

- aggressive-private 模式补回的关系里有真价值，但混有更高误伤风险；需要 review/promotion gate，把高置信规则提升到 strict public。
- 前端如果还接旧 graph surface，会继续出现“不是全量”的错觉；必须接新 serving read model。

### Unverified

- 公开站点 API 还没有切到新的 `atlas_serving.sqlite`。
- 3D 图谱网页还没有完成第二轮 UI/性能自测。
- 私有候选库里的新增关系还没有人工抽检足够样本。

## 4. Work performed

Changed / added:

- `tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
- `tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py`
- `docs\ATLAS_FULL_RUN_AND_REPAIR_WORKLOG_20260522.md`
- `docs\ATLAS_SERVING_READ_MODEL_PRODUCTION_RUN_20260522.md`
- `docs\ATLAS_FULL_REPAIR_PRIVATE_CANDIDATE_20260522.md`
- `docs\ATLAS_DJ_GRAPH_SAVEPOINT_AND_PLAN_20260522.md`
- `docs\current-runtime.md`
- `docs\DOCUMENTATION_INDEX.md`

Important generated artifacts:

- Public-safe DB: `reports\atlas_serving_read_model_20260522\atlas_serving.sqlite`
- Public-safe manifest: `reports\atlas_serving_read_model_20260522\manifest.json`
- Public-safe summary: `reports\atlas_serving_read_model_20260522\summary.md`
- Private repair DB: `reports\atlas_serving_repair_full_private_20260522\atlas_serving.sqlite`
- Private repair manifest: `reports\atlas_serving_repair_full_private_20260522\manifest.json`
- Private repair summary: `reports\atlas_serving_repair_full_private_20260522\summary.md`
- Git backup before this handoff: `C:\code\.git-workspace-backups\wechathtmldownload\20260522-031119`

## 5. Verification status

Passed:

- `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
- `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py -q`
- strict public full build completed.
- private aggressive repair full build completed.
- docs neat closeout ran; remaining MkDocs warnings are pre-existing documentation structure warnings.

Not run:

- No deploy.
- No Cloudflare/Turnstile change.
- No public API switch.
- No browser UI retest after final DB production.

## 6. Current blocker

The next blocker is product/promotion judgment, not a small bug:

- Strict public DB is the only current deployable candidate.
- Private repair DB has more coverage but is not public-safe enough to deploy directly.
- Need a review/promotion loop that samples the private-only recovered DJ/event/venue edges, promotes safe deterministic rules into strict mode, then rebuilds strict public DB.

## 7. Next best entry

Open these first:

1. `docs\ATLAS_FULL_RUN_AND_REPAIR_WORKLOG_20260522.md`
2. `docs\ATLAS_SERVING_READ_MODEL_PRODUCTION_RUN_20260522.md`
3. `docs\ATLAS_FULL_REPAIR_PRIVATE_CANDIDATE_20260522.md`
4. `tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`

Then inspect the two manifests:

```powershell
Get-Content reports\atlas_serving_read_model_20260522\manifest.json
Get-Content reports\atlas_serving_repair_full_private_20260522\manifest.json
```

If DeepSeekTUI continues work, the highest-value slice is:

1. Compare strict public vs aggressive-private rows.
2. Find private-only additions with strong evidence and low noise.
3. Write a deterministic promotion rule.
4. Add a test.
5. Rebuild strict public DB.
6. Confirm no forbidden raw field and no wine/product noise.

## 8. Warnings / pitfalls

- Do not judge “fullness” from the old graph surface. The old surface had only about `158,490` unique graph events and will undercount.
- Do not deploy `reports\atlas_serving_repair_full_private_20260522\atlas_serving.sqlite`.
- Do not expose raw source URLs, local archive paths, raw HTML, raw JSON, or article UID to public frontend.
- Do not remove SHCR / BYYB / BAIHUI / CDCR as noise; user clarified these are radio/media entities.
- Do not use expensive LLM for simple deterministic backfill unless a targeted review queue justifies it.
- DeepSeekTUI is draft/research sidecar here, not production controller.

## 9. OpenHuman import status

imported: no  
reason: this handoff is specifically for WSL2 DeepSeekTUI / `pc_deepseek_tui`; no OpenHuman import was requested in this closeout.

## 10. HTML companion artifact status

html_path: `docs\atlas-deepseektui-handoff-20260522\INDEX.html`  
opened: no  
reason: generated as a static companion for fast review; no browser opening was needed for this handoff.

## 11. WSL2 readable paths

Windows canonical:

```text
C:\code\githubstar\wechathtmldownload\docs\atlas-deepseektui-handoff-20260522\ATLAS_FULL_RUN_REPAIR_TO_DEEPSEEK_20260522.md
```

WSL view of the same repo:

```text
/mnt/c/code/githubstar/wechathtmldownload/docs/atlas-deepseektui-handoff-20260522/ATLAS_FULL_RUN_REPAIR_TO_DEEPSEEK_20260522.md
```

Additional WSL home copy target:

```text
/home/pc/codex-handoffs/ATLAS_FULL_RUN_REPAIR_TO_DEEPSEEK_20260522.md
```
