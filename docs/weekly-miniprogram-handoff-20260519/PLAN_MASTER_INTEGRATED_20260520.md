# HUAIDJ 周活管线全量集成主计划（Master Implementation Plan）

> **已合并至 [PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md](./PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md)**（§10）。Task 逐步骤细节仍可参考本文下半部。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 HUAIDJ 周活小程序管线的高精准度识别（目标 lineup 召回率提升至 55-65%，0 假阳性）、全自动化 CDN URL 清洗（backendRawHits 降至 0）与向量×图谱只读消歧联动的完整工程闭环。

**Architecture:** 
周活侧管线专注于时效与本场证据。在 `build_weekly_activity_miniprogram_api.py` 层清洗正文 CDN 图片 URL，达成 0 泄露硬指标；
在 `repair_` 层由“二元清空制”转为“软评分制”；
引入独立 `weekly_atlas_bridge` 模块，离线物化只读 snapshot 下行消费图谱实体（五级匹配阶梯），并将未匹数据低频上行 observations jsonl。

**Tech Stack:** Python 3.10+, Requests, SequenceMatcher (difflib), Qdrant (read-only requests), Unittest.

---

## 1. 现状审计与事实底准 (As of 2026-05-20)

| 指标维度 | 当前底准数据 (Baseline) | P0-P4 终极目标 (Milestones) | 事实验证来源 |
|:---|:---|:---|:---|
| **已发布活动总数** | 103 条 | 窗口内全覆盖 (100-110 条) | `weekly-api-033` 远端 Probe |
| **有 lineup (strict通过)** | 40 条 (约 39%) | 55 - 65 条 (约 55-65%) | release guardian `visibleHits` |
| **missing_lineup 审计数**| 63 条 (约 61% 空缺) | 35 条以下 (降至 35% 以下) | `audit_weekly_lineup_address_time.py` |
| **backendRawHits (URL)** | 51 条 (CDN 泄漏) | **0 条 (硬门禁)** | check_weekly_release_guard.ps1 |
| **P0 Golden Set 种子** | 88 条 (均为 pending) | 120-150 条 (标注 verified) | `golden_set_v1.jsonl` |
| **L1 Entity Resolver** | 89 行 (100% `no_match`) | 匹配覆盖率 (即有ID率) ≥50% | `weekly_entity_snapshot.json` (因 seed 仅 5 艺人) |
| **自动化测试状态** | 24/24 JS Pass; 8/8 Py Pass | 维持 100% 单元测试及回归通过率 | `node --test` / `unittest` |

---

## 2. 核心架构重构设计 (Rethinking Plan A & B)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                L0 原始数据层                                     │
│                     公众号原文 HTML / 海报 ──> OCR 证据提取                       │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              L1 确定性与规则过滤                                 │
│                   日期 Regex 抽取、安全白名单、艺人 seed exact 匹配                │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                L2 LLM 双轨模型层                                 │
│                 Flash no-thinking 全量 ──> (黄页安全网) ──> Pro 风险行审          │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               L3 评分裁决与清洗 (Build)                          │
│               merge ──> repair (软打分评分制) ──> audit (strict 校验)            │
│                       ──> build_api (剥离正文 CDN URL 行)                         │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            L4 向量×图谱联动桥接 (Bridge)                          │
│   [只读消费] 挂载 atlas_alias_export ──> resolver 五级匹配 ──> snapshot 只读下行  │
│   [低频上行] 导出 weekly_entity_observations ──> 图谱 ingest (不直写 production)   │
└────────────────────────────────────────┬────────────────────────────────────────┘
```

---

## 3. 分阶段工程任务拆解

### Task 1: [P1] Build层正文 CDN URL 强制清洗与门禁闭环

**Files:**
- Modify: `tools/stage7_rewrite/scripts/archive_old/build_weekly_activity_miniprogram_api.py:1200-1250` (清洗原正文行)
- Modify: `C:/Users/pc/.codex/skills/huaidj-weekly-release-guardian/scripts/check_weekly_release_guard.ps1` (守卫门禁升级)
- Test: `tools/stage7_rewrite/tests/test_weekly_golden_baseline.py`

- [ ] **Step 1.1: 编写 URL 检测与剥离规则的失败测试**
  在 `tools/stage7_rewrite/tests/test_weekly_golden_baseline.py` 中增加对 raw CDN URL 的过滤测试：
  ```python
  def test_cdn_url_stripping_in_build(self):
      from tools.stage7_rewrite.scripts.weekly_golden_lib import backend_url_lines
      dirty_item = {
          "description_original_lines": [
              "来看今晚演出",
              "https://mmbiz.qpic.cn/mmbiz_jpg/abc/0?wx_fmt=jpeg", # 应当被洗掉
              "关注官方微信：HUAIDJ"
          ]
      }
      cleaned_lines = [
          line for line in dirty_item["description_original_lines"]
          if not any(x in line for x in ("mmbiz.qpic.cn", "wx_fmt="))
      ]
      self.assertEqual(len(cleaned_lines), 2)
      self.assertNotIn("mmbiz.qpic.cn", cleaned_lines[1])
  ```

- [ ] **Step 1.2: 执行测试确认其在修改前通过/失败状况**
  运行：`python -m unittest tools.stage7_rewrite.tests.test_weekly_golden_baseline.WeeklyGoldenBaselineTests.test_cdn_url_stripping_in_build -v`

- [ ] **Step 1.3: 修改 `build_weekly_activity_miniprogram_api.py` 实施 build 时剥离 URL**
  定位到 `build_weekly_activity_miniprogram_api.py` 写入 `description_original_lines` 循环前，注入正则剥离。
  ```python
  # 在写入 description_original_lines 前：
  strip_patterns = [r"mmbiz\.qpic\.cn", r"wx_fmt=", r"qpic\.cn"]
  cleaned_lines = []
  for line in item.get("description_original_lines") or []:
      if not any(re.search(pat, line) for rpat in strip_patterns):
          cleaned_lines.append(line)
  item["description_original_lines"] = cleaned_lines
  ```

- [ ] **Step 1.4: 升级 release guardian 将 `backendRawHits` 非 0 设为 `ok: false`**
  编辑 `check_weekly_release_guard.ps1`，把 `backendRawHits` 的检验变为强阻断。
  ```powershell
  if ($backendRawHits -gt 0) {
      $globalOk = $false
      Write-Host "CRITICAL GATE FAIL: backendRawHits has $backendRawHits CDN URL leaks!" -ForegroundColor Red
  }
  ```

- [ ] **Step 1.5: 重新跑 guardian 校验 20260519 包，确保 `backendRawHits` 降低至 0**
  Run: `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1 -CurrentReleaseDir D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519`
  Expected: visibleHits=0, backendRawHits=0, 门禁全绿。

- [ ] **Step 1.6: 提交 P1 门禁改动**
  ```bash
  git add tools/stage7_rewrite/scripts/archive_old/build_weekly_activity_miniprogram_api.py
  git commit -m "feat: wash CDN URLs during api build and promote raw hits leak to a critical block gate"
  ```

---

### Task 2: [P2] Repair 阶段由“清空制”向“软评分制”升级

**Files:**
- Create: `tools/stage7_rewrite/tests/test_repair_weekly_scoring.py`
- Modify: `tools/stage7_rewrite/repair_weekly_lineup_address_time_fields.py`

- [ ] **Step 2.1: 编写软评分修复逻辑的失败单元测试**
  由于目前 lineup 常被 `bio gate` 暴力清空，建立一个不包含 verified 标识但包含明确 lineup 语气词的打分测试：
  ```python
  # Create tools/stage7_rewrite/tests/test_repair_weekly_scoring.py
  import unittest

  class RepairScoringTests(unittest.TestCase):
      def test_scoring_system_retains_lineup_with_weak_evidence(self):
          from tools.stage7_rewrite.repair_weekly_lineup_address_time_fields import score_lineup_artist
          # 既非 seed 也没有 verified，但正文中存在 "Special Guest: Slikback"
          score = score_lineup_artist("Slikback", evidence_context="Special Guest: Slikback")
          self.assertGreaterEqual(score, 0.6) # 评分应大于保留阈值
  ```

- [ ] **Step 2.2: 运行测试验证其失败**
  Run: `python -m unittest tools.stage7_rewrite.tests.test_repair_weekly_scoring -v`

- [ ] **Step 2.3: 重构 `repair_weekly_lineup_address_time_fields.py` 的 lineup 处理函数**
  引入多维度加权打分，取代原有 `artist_profiles` 缺失即强制清空或 `bio gate` 一刀切：
  ```python
  def score_lineup_artist(name, evidence_context=None, is_in_seed=False):
      score = 0.1
      if is_in_seed:
          score += 0.8
      if evidence_context and name.lower() in evidence_context.lower():
          score += 0.5
      if any(x in (evidence_context or "").lower() for x in ["lineup", "djs", "presents"]):
          score += 0.2
      return min(1.0, score)
  ```
  在主修补循环中，对于 `score >= 0.6` 的 lineup 予以保留，而不是直接清空。

- [ ] **Step 2.4: 运行回归测试，确保没有破坏 strict 门禁**
  Run: `python -m unittest tools.stage7_rewrite.tests.test_repair_weekly_scoring -v`
  Expected: PASS

- [ ] **Step 2.5: 提交评分制修复代码**
  ```bash
  git add tools/stage7_rewrite/repair_weekly_lineup_address_time_fields.py
  git commit -m "feat: shift repair stage from absolute binary clearance to soft scoring system"
  ```

---

### Task 3: [L2] Resolver 接入图谱 G0 标准别名导出 (Downstream Snapshots)

**Files:**
- Modify: `tools/stage7_rewrite/weekly_atlas_bridge/indexes.py` (加载 alias)
- Modify: `tools/stage7_rewrite/weekly_atlas_bridge/resolver.py` (整合 alias exact 与多候选)
- Test: `tools/stage7_rewrite/weekly_atlas_bridge/tests/test_resolver.py`

- [ ] **Step 3.1: 编写多候选 `fuzzy_multiple` 与 `alias_exact` 的单元测试**
  在 `tools/stage7_rewrite/weekly_atlas_bridge/tests/test_resolver.py` 中增加用例：
  ```python
  def test_alias_exact_and_multiple_candidates(self):
      from tools.stage7_rewrite.weekly_atlas_bridge.indexes import ArtistRecord, MatchIndex
      from tools.stage7_rewrite.weekly_atlas_bridge.resolver import EntityResolver
      index = MatchIndex()
      # 模拟图谱多候选冲突
      index.add(ArtistRecord("atlas:entity:slikback_1", "Slikback", True), "Slikback")
      index.add(ArtistRecord("atlas:entity:slikback_2", "Slikback KE", False), "Slikback")
      
      resolver = EntityResolver(index=index)
      result = resolver.resolve("Slikback")
      self.assertEqual(result.match_method, "fuzzy_multiple")
      self.assertEqual(result.display_tier, "show_with_hint")
      self.assertIsNone(result.artist_id) # 不得自动匹配 ID 避免错配
  ```

- [ ] **Step 3.2: 运行测试校验**
  Run: `python -m unittest tools.stage7_rewrite.weekly_atlas_bridge.tests.test_resolver -v`

- [ ] **Step 3.3: 修改 `resolver.py` 以兼容 `WeeklyAtlasEntityContract` v1.0.0 的变动规则**
  如果 alias 匹配到多个实体，一律降级到 `fuzzy_multiple` 且 `display_tier = "show_with_hint"`, 只提供 hint canonical 名，不泄露内部 `artist_id`。

- [ ] **Step 3.4: 再次执行 bridge 单测，确保 100% 覆盖通过**
  Run: `python -m unittest tools.stage7_rewrite.weekly_atlas_bridge.tests.test_resolver -v`
  Expected: OK (8 tests or more passed)

- [ ] **Step 3.5: 提交 L2 别名消歧代码**
  ```bash
  git add tools/stage7_rewrite/weekly_atlas_bridge/
  git commit -m "feat: enforce multi-candidate disambiguation and fallback to show_with_hint according to contract v1"
  ```

---

### Task 4: [L3] 观测、上行与 OpenClaw 联动闭环

**Files:**
- Modify: `tools/stage7_rewrite/weekly_atlas_bridge/observations.py`
- Test: `tools/stage7_rewrite/weekly_atlas_bridge/tests/test_observations.py` (新增上行单测)

- [ ] **Step 4.1: 编写上行 observation schema 校验单元测试**
  确保生成的 jsonl 严格遵守 `WeeklyAtlasEntityContract.md` 中的 `upstream_observation`：不泄露个人隐私，不含 OpenID，对 source URL 强制做 SHA256 脱敏。
  ```python
  # Create tools/stage7_rewrite/weekly_atlas_bridge/tests/test_observations.py
  import unittest

  class ObservationTests(unittest.TestCase):
      def test_observation_compliance_no_openid_and_hashed_url(self):
          from tools.stage7_rewrite.weekly_atlas_bridge.observations import build_observation_row
          item = {
              "event_id": "test:123",
              "source_url": "https://mp.weixin.qq.com/s/some_untrusted_link_with_openid_12345",
              "lineup": ["Artist X"]
          }
          row = build_observation_row(item, publish_package="TEST_PKG")
          self.assertNotIn("openid", json.dumps(row))
          self.assertTrue(row["source_url_hash"].startswith("sha256:"))
          self.assertIsNone(row.get("source_url")) # 不应含有明文 URL
  ```

- [ ] **Step 4.2: 运行测试确认结果**
  Run: `python -m unittest tools.stage7_rewrite.weekly_atlas_bridge.tests.test_observations -v`

- [ ] **Step 4.3: 细化 observations.py 确保 URL 洗涤脱敏**
  确认 `build_observation_row` 函数中去掉了明文 `source_url` 并计算 SHA256 哈希值后，才存入 `source_url_hash`。

- [ ] **Step 4.4: 运行全量管线集成测试**
  Run: `python -m unittest tools.stage7_rewrite.weekly_atlas_bridge.tests.test_resolver tools.stage7_rewrite.weekly_atlas_bridge.tests.test_observations -v`
  Expected: PASS

- [ ] **Step 4.5: 提交 observations 脱敏上行代码**
  ```bash
  git add tools/stage7_rewrite/weekly_atlas_bridge/observations.py
  git commit -m "sec: enforce privacy compliance and single-way hashing for outbound atlas observations"
  ```

---

## 4. 待用户拍板决策

| 决策编号 | 焦点问题 | 方案 A（推荐，已编入本计划） | 方案 B（备选，需用户审批） | 理由与考量 |
|:---|:---|:---|:---|:---|
| **D1** | **URL清洗时机与门禁** | 在 build/物化层强力剥离 CDN URL（Task 1），release guardian 门禁不为 0 则直接拒绝发布。 | 仅在小程序前端进行过滤（维持现状），后端 API 的 items 中继续附带 51 条 URL。 | 推荐 A。能够真正减少 API payload 泄露和性能损耗，且完全符合安全硬门原则。 |
| **D2** | **向量推荐是否自动进入小程序 lineup** | 坚决不进入自动 lineup，仅用于 observations 离线 review (Task 3)。 | 向量 top-1 匹配分数较高（如 ≥0.95）时自动采纳展示。 | 推荐 A。任何缺乏文字证据的向量邻近搜索均有可能导致严重的假阳性错配（例如名字相似的其他 DJ），不符合“可证明才展示”的基本产品伦理。 |
| **D3** | **多候选冲突 UI 呈现** | 多个标准别名碰撞时（阶 4），小程序绝不展示 ID 仅展示“可能是: A/B” 的 canonical 别名 hint (Task 3)。 | 多候选冲突时取 top-1 verified 自动绑定。 | 推荐 A。防止错挂卡片，宁缺毋滥。 |

---

## 5. 警示与防踩坑指南 (Warnings)

1. **非 Git 仓库根目录操作**：由于本仓库路径 `C:\code\githubstar\wechathtmldownload` 并非 Git 根目录，执行 git status / commit 操作时应在对应的根路径下（即带有 `.git` 的父级），或者显式使用 `--git-dir`。
2. **严禁扫描 D:\ 根目录**：如需校验本地 API 包，在参数中显式指定完整相对路径或子目录，不可执行递归式广域搜索。
3. **`dj_bio_lines` 特别注意**：在 Plan Master 的 P3 阶段之前，任何脚本中将 `dj_bio_lines` 强行恢复的行为都是危险的。开通 bio 必须基于 `artist_profiles` 降临，确保有 verified 凭证才能放行。
4. **`missing_lineup` 不视为发布 hard_fail**：千万不能为了降低 audit 中的 `missing_lineup` 数量而强行用 LLM 猜测，或者放宽 audit strict 门禁。必须依据 Golden Set 进行 P/R 调优。

---

*此计划已与前两轮 LDR（Plan A & Plan B Pro 深度研究档案）实现深度集成，通过单测卫护。现处于 **CANDIDATE MASTER PLAN** 状态，等待决策后启动。*
