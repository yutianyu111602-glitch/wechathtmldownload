# Atlas Entity Merge Pipeline — 2026-06-07/08

## 背景

Atlas 图谱数据库从多个来源累积了 59,322 个实体（53,555 DJ + 5,767 场地/主办方），存在严重的同名变体问题。同一个俱乐部"Dada Bar Beijing"可能有 `Dada Bar Beijing`、`DADA BEIJING`、`dadabarbeijing`、`Dada北京` 等多个 subject_id。

## 执行过程

### Phase 1: DeepSeek Flash 实体消歧

**模型选择**：经过对比，deepseek-v4-flash 比 v4-pro 性价比高 4 倍（~$15 vs ~$100），且对于规则驱动的 JSON 分类任务（merge/split/review）质量没有显著差异。

**管道**：
```
1. build_atlas_entity_merge_deepseek_queue.py → 构建 22,273 个候选合并集群
2. run_atlas_entity_merge_deepseek.py → DeepSeek Flash 对每个集群裁决 merge/split/review
   参数: --model deepseek-v4-flash --concurrency 6/10 --prompt-profile sound_aware_v1
3. 产出 entity_merge_llm_decisions.jsonl
```

**系统提示要点**：
- DJ/个人与俱乐部/厂牌默认不能合并（除非明确证据）
- 场地 venue 与 organizer/club brand 可合并为同一 entity，标记 mixed_type_merge
- 同城同名变体合并；不同城市同名连锁（如 Dada Beijing vs Dada Kunming）保持拆分
- 音响系统、设备名不能与俱乐部/DJ 合并
- 不确定的标记 review，不强行 merge

**断点续跑**：22,273 个集群通过 `--resume` 分多次续跑完成，每次超时或 API 错误自动从 checkpoint 恢复。

### Phase 2: 合并应用

**方案演进**：
1. ~~直接 SQLite UPDATE~~ → 2.2GB DB 单行写入太慢（~2000行/10分钟）
2. ~~批量事务 UPDATE~~ → 516K 行的 `performance_event` 表更新过慢
3. **最终：两层架构**
   - `search_document` 表：直接 SQLite UPDATE (16,927 条 subject_id + 9,293 条 display_name)
   - `performance_event` / 其他表：merge_map.json 查询时映射

```
查询时：
  subject_id = merge_map.get(raw_subject_id, raw_subject_id)
  display_name = merge_map.get_name(canonical_id) || raw_name
```

## 结果

### 数据
| 指标 | 合并前 | 合并后 | 减少 |
|------|--------|--------|------|
| DJ | 53,555 | 45,215 | -8,340 (15.6%) |
| 场地/主办 | 5,767 | 3,275 | -2,492 (43.2%) |
| search_docs | 590,927 | 590,927 | (不变，subject_id 重映射) |
| performance_events | 508,049 | 508,049 | (不变，venue_id 重映射) |

### 决策分布
| 决策 | 数量 | 占比 |
|------|------|------|
| merge | 11,369 | 51.9% |
| split | 8,060 | 36.8% |
| review | 2,415 | 11.0% |
| error | 16 | 0.1% |

### 风险标记
| 标记 | 数量 | 含义 |
|------|------|------|
| mixed_type_merge | 3,177 | 场地+主办品牌合并 |
| mixed_subject_types | 515 | DJ+其他类型混合合并 |
| short_alias_key | 63 | 短名称匹配 |
| large_cluster | 8 | 大集群（>20 elements） |

### 花费
**总计 ~$15-20 USD**

| 项目 | 估算 |
|------|------|
| 模型 | deepseek-v4-flash |
| 调用次数 | 21,860 |
| 输入 tokens | ~109M ($15) |
| 输出 tokens | ~6.5M ($2) |

### 典型案例
| 俱乐部 | 合并数 | 示例变体 |
|--------|--------|----------|
| Club Celia Shanghai | 26 | Celia、Celia Club、上海Celia... |
| DONG 洞 | 25 | DONG、dong、DONG 洞、杭州dong... |
| 招待所 ZhaoDai | 20 | ZhaoDai、招待、招待所... |
| OIL 深圳 | 多个 | OIL、OIL油、OIL CLUB、深圳OIL... |
| Dada Bar Beijing | 多个 | Dada、DADA、dadabarbeijing... |
| VERVO | 多个 | VERVO Club、VERVO俱乐部、昆明VERVO... |

**正确拒绝的合并**：
- Dada 北京/上海/昆明：保持独立城市实体 ✅
- DJ BO ≠ BO LIVE 俱乐部 ✅
- 音响系统不应与俱乐部合并 ✅

## 经验教训

### 1. v4-flash 足够，不需要 v4-pro
规则驱动的 JSON 分类任务（merge/split/review），v4-flash 质量与 v4-pro 相当，费用仅 1/4。

### 2. 断点续跑是关键
22,273 个 API 调用不可能一口气完成。`--resume` + `--checkpoint-every 10` 确保中断后从上次位置继续，不重复花钱。

### 3. 对 2GB+ SQLite 不要做单行 UPDATE
对大表逐行更新极慢（2000行/10分钟）。Query-time merge map 是更优方案：
- 零写入时间（500KB JSON vs 2.2GB 修改）
- 可逆（删除 map 文件即可回滚）
- 查询时 O(1) 查 HashMap

### 4. 并发数 6 比 10 更稳定
DeepSeek API 在高并发下返回 `Remote end closed` 错误。降并发 + `--sleep-s 0.5` 大幅减少错误率。

### 5. 提前计算 token 花费
每次跑前估算：`集群数 × 平均 token 数 × 单价`。本次 22K 集群 × 5K tokens × $0.14/M = ~$15，实际吻合。

## 产物清单

| 文件 | 用途 |
|------|------|
| `entity_merge_llm_decisions.jsonl` | 全部 21,860 条决策 |
| `entity_merge_llm_errors.jsonl` | 16 条 API 错误 |
| `merge_map.json` | 16,927 条 subject_id 重映射 + 9,293 条名称更新 |
| `atlas_serving.sqlite` (merged) | 应用合并后的 2.2GB 图谱 DB |
| `post_merge_pipeline.ps1` | 完整 4 步管道脚本 |
| `quality_check.py` | 决策质量分析脚本 |
