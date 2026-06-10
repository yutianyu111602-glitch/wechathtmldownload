# Atlas ↔ 小程序 场地归一化契约 v1

> **契约目的**: 定义 `venue_name` 和 `venue_id` 的生成/归一化规则，保证 Atlas 数据库和小程序前端对同一场地的引用一致。
> **适用范围**: `atlas_miniapp.sqlite` 的 `dj_event`、`dj_venue` 表，以及 `export_atlas_miniapp_json.py` 导出的 `atlas_index.json.gz`。

---

## 1. 场地唯一标识 (venue_id)

### 算法
```
venue_id = "venue:" + SHA1("venue_name\x1f")[:16]
```

其中 `venue_name` 是**归一化后**的名称（见 §2）。

### 规则
- **一个归一化后的 venue_name 对应且仅对应一个 venue_id**
- venue_id 在 `dj_event`、`dj_venue`、`venue_by_name` 中全局一致
- 前端通过 `venue_id` 查询场地事件，通过 `venue_by_name` 按名称反查

---

## 2. 场地名归一化规则 (venue_name → canonical)

以下规则**按顺序**执行：

### 2.1 精确别名映射 (whitelist)
已知同一场地的不同写法 → 映射到 canonical 名：

| 原始名称 | Canonical 名称 |
|----------|---------------|
| `OIL油` | `OIL` |
| `OIL CLUB` | `OIL` |
| `JAR这儿` | `JAR` |
| `ALL俱乐部` | `ALL` |
| `/\|\|` | `ALL` |
| `FOUNDATION俱乐部` | `FOUNDATION` |
| `Elevator上海` | `Elevator` |
| `Heim Shanghai` | `Heim` |
| `VERVO国际独立电音俱乐部` + 全部变体 | `VERVO` |
| `Dada Bar Beijing` | `Dada Beijing` |
| `Dada Bar Shanghai` | `Dada Shanghai` |
| `TAGChengdu` + `.TAG` 变体 | `TAG` |
| `BO LIVE(福田店)` | `BO LIVE` |
| `WuhanPrison` | `WuhanPrison` |
| `ZhaoDai` | `ZhaoDai` |
| `Cs Bar` | `C's Bar` |
| `Echo Bay` | `EchoBay` |
| `SOLO Beijing` | `SOLO Beijing` |
| `EXIT Shanghai` | `EXIT Shanghai` |
| `club between` | `club between` |

### 2.2 去城市前缀
形如 `{城市名} {场地名}` → 去掉城市前缀：
- `昆明 VERVO` → `VERVO`
- `上海 Dada Shanghai` → `Dada Shanghai`
- `成都 .TAG` → `TAG`

### 2.3 去城市后缀（括号）
形如 `{场地名}({城市})` → 去掉括号部分：
- `VERVO(昆明)` → `VERVO`
- `ALL(上海)` → `ALL`

### 2.4 去推断标注
包含以下关键词的括号内容全部去掉：
`(推测)` `(未明确)` `(推测为昆明)` `(未公布)` `(待定)` `(待确认)` `(TBC)` `(TBD)`

### 2.5 场地名含斜杠/或 → 取第一个
- `Dada Shanghai / Dada Beijing` → `Dada Shanghai`
- `THE BLACK ROOM / VERVO` → `THE BLACK ROOM`
- `Canto Club 或 Dada Shanghai` → `Canto Club`

### 2.6 去 @ 和 . 前缀
- `@DADA SHANGHAI` → `DADA SHANGHAI`
- `.TAGChengdu` → `TAGChengdu`

### 2.7 去地址后缀
冒号后的地址信息去掉：
- `Dada Shanghai: 幸福路115号 近法华镇路` → `Dada Shanghai`

### 2.8 去楼层/房间后缀
- `VERVO ROOM2` → `VERVO`
- `ALL俱乐部 一楼` → `ALL俱乐部`

### 2.9 Trim + 规范化空白
- 去掉首尾空格
- 多个连续空格合并为一个

---

## 3. 导出契约 (export_atlas_miniapp_json.py)

导出的 JSON 中：
- `events[].v` = 归一化后的 `venue_name`
- `dj_venues[].vn` = 归一化后的 `venue_name`
- `venue_events` key = `venue_id`（归一化后重新计算）
- `venue_by_name` key = `norm_key(归一化后的 venue_name)` → `[venue_id, ...]`

---

## 4. 小程序端契约

### 4.1 场地查找
- 前端通过 `venue_id` 精确匹配场地
- `venue_by_name` 用于：用户输入场地名 → 反查 `venue_id` → 查场地事件
- 归一化逻辑**不在小程序端重复**，由数据导出时保证一致性

### 4.2 venue 页面数据
从 `venue_events[venue_id]` 取活动列表，从 `venue_by_name[norm_name]` 取 venue_id 列表。

---

## 5. 实施步骤

1. **`normalize_venue_names.py`**: 按 §2 规则更新 `dj_event.venue_name`，按 §1 重算 `venue_id`
2. **`normalize_atlas_entities.py` Step 7**: 从 `dj_event` 重算 `same_event_count`
3. **`export_atlas_miniapp_json.py`**: 导出时再做一次 `norm_venue()` 兜底
4. **验证**: 导出后检查 venue_id 一致性，对比源数据和小程序展示

---

## 6. 不变式 (Invariants)

- [ ] 每个归一化后的 `venue_name` 只有一个 `venue_id`
- [ ] `same_event_count` = 两个 DJ 在 `dj_event` 表中共享的 DISTINCT `event_id` 数量
- [ ] `dj_venue` 的 `venue_name` 与 `dj_event` 中的归一化名一致
- [ ] 导出 JSON 中不再出现 "OIL油"、"JAR这儿"、"Dada Bar Beijing" 等未归一化名
