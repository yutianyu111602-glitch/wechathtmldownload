# WeeklyAtlasEntityContract v1.0（L0 草案）

Status: P0 契约稿 — 计划二 L0，与计划一 Golden 并行  
Scope: 周活侧只读消费；图谱侧生产写入不在周活线程

## 版本

| 字段 | 值 |
|------|-----|
| `contract_version` | `1.0.0` |
| `schema_version` | `weekly_atlas_entity.v1` |
| `breaking_change_policy` | 新增可选字段 → MINOR；重命名/删除 → MAJOR + 双写 ≥2 周 |

## 分工

| 系统 | 负责 |
|------|------|
| 周活 | 这一场：日期、本场 lineup 证据、发布窗口 |
| 图谱 | 是谁：canonical ID、别名、verified bio/图 |
| 联动 | Entity Linking，不重复 full 图谱抽取 |

## 下行：图谱 → 周活（`weekly_entity_snapshot.json`）

物化于 API build 之前，只读挂载。

```json
{
  "contract_version": "1.0.0",
  "generated_at": "2026-05-19T12:00:00Z",
  "artist_profiles": [
    {
      "artist_id": "atlas:entity:abc123",
      "canonical_name": "Doon Kanda",
      "verified": true,
      "bio_manual": "…",
      "avatar_url": "https://…",
      "source": "atlas_verified",
      "last_updated": "2026-05-01"
    }
  ],
  "lineup_resolved": [
    {
      "event_id": "venue:hash",
      "raw": "Doon Kanda",
      "artist_id": "atlas:entity:abc123",
      "match_score": 0.98,
      "match_method": "alias_exact",
      "verified": true,
      "candidates": null
    }
  ],
  "venue_resolved": [
    {
      "event_id": "venue:hash",
      "venue_id": "atlas:venue:xyz",
      "canonical_name": "loopy Club",
      "match_score": 0.95,
      "verified": true
    }
  ]
}
```

**禁止下行**：未验证边、向量猜同台、历史 lineup 猜本场。

## 上行：周活 → 图谱（`weekly_entity_observations.jsonl`）

每周 publish 后追加；图谱 ingest 为 observation，**不直写 production**。

```json
{
  "observation_id": "obs_20260519_venue_hash",
  "event_id": "loopy:abc",
  "observed_at": "2026-05-19T20:00:00Z",
  "window": { "start": "2026-05-19", "end": "2026-06-02" },
  "lineup_raw": ["Artist A"],
  "lineup_evidence": [{ "type": "ocr", "image_id": "img_x", "quote": "…" }],
  "venue_raw": "loopy Club",
  "source_url_hash": "sha256:…",
  "publish_package": "WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519"
}
```

## Resolver 阶梯（摘要）

| 阶 | 方法 | 自动展示 |
|----|------|----------|
| 1 | registry exact | 是 |
| 2 | alias exact ≥0.98 | 是 |
| 3 | fuzzy 唯一 ≥0.92 | 是 |
| 4 | fuzzy 多候选 | 否（hint only） |
| 5 | 向量 top-1 | 否（review only） |
| 6 | 无匹配 | 保留 raw，`artist_id=null` |

## 模块边界（周活）

```
tools/stage7_rewrite/weekly_atlas_bridge/
  load_snapshot.py      # 读 snapshot
  apply_to_items.py     # 写 artist_profiles / lineup_resolved（仅 verified）
  export_observations.py
```

## 与计划一 Golden 对齐

- Golden 行可选 `gold.artist_id` map，用于 resolver precision/recall（L1）。
- `dj_bio_lines` 解锁条件：仅 `verified` + 产品批准（计划一 P3）。

## 待拍板

1. snapshot 刷新频率：每日 build 前 vs 每周
2. fuzzy 阈值 0.92 是否按城市分桶
3. 向量候选是否进入 observation 上行（推荐：是，但不进展示）
