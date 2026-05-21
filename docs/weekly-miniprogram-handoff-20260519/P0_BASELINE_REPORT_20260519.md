# P0 Weekly Baseline Report

Generated: 2026-05-21T03:48:00+00:00

## Release metrics (current.json)

| 指标 | 值 |
|------|-----|
| 发布条数 | 158 |
| 有 lineup | 100 (63.3%) |
| missing_lineup（粗算） | 58 |
| backend URL 行数 | 0 |
| 含 URL 活动数 | 0 (0.0%) |
| 城市数 | 24 |

## Golden set

| 项 | 值 |
|----|-----|
| 金标条数 | 88 |
| pending | 68 |
| verified | 20 |

### Stratum

- `lineup_present`: 22
- `missing_lineup`: 48
- `url_backend`: 18

## Scored metrics (verified only)

- lineup precision (mean): 1.0
- lineup recall (mean): 1.0
- hard_error_rate: 0.0

## P0 exit gate

- [ ] Golden ≥80 条（已引导）
- [ ] 人工 verified ≥80 且 inter-annotator 待做
- [ ] baseline 报告 review 通过

## Next

1. 人工填写 `gold.*`，将 `annotation_status` 改为 `verified`
2. 重跑本脚本更新 P/R
3. P1：URL build 清洗 + field_evidence
