# Atlas ↔ 小程序 数据契约 v2

> **最后更新**: 2026-05-29
> **状态**: 已写入记忆，后续会话自动加载

---

## 1. 不变式 (Invariants)

### 1.1 venue_id 不可变
- `venue_id` 一旦分配给一个场地，**永不改变**
- 归一化 `venue_name` 时，**不重算 venue_id**
- 同一场地的多个 `venue_name` 变体通过 `venue_name→venue_id` 映射来关联，而不是通过修改 `venue_id`

### 1.2 same_event_count 从 dj_event 实时计算
- `same_event_count` = 两个 DJ 在 `dj_event` 表中共享的 `COUNT(DISTINCT event_id)`
- **不作为静态字段存储**，每次导出时从 `dj_event` 实时 JOIN 计算
- 或者：在 entity merge 后必须重算

### 1.3 subject 表的 venue 记录
- `subject.display_name` 和 `subject.normalized_name` 用于展示
- 归一化时可以更新 display_name，但不改变 subject_id

---

## 2. 数据流

```
Docker 公众号下载器 (129账号)
  → LLM 提取 entities + events
  → atlas_miniapp.sqlite
    → normalize_atlas_entities.py (entity merge, same_event_count 重算)
    → normalize_venue_names.py (venue_name 归一化, 不改 venue_id)
    → export_atlas_miniapp_json.py (导出 JSON)
      → atlas_index.json.gz (16.5MB)
        → CloudRun 后端
          → 小程序前端
```

---

## 3. venue_name 归一化规则

### 3.1 原则
- **归一化 venue_name 用于展示，不改变 venue_id**
- 多个 venue_name → 同一个 canonical name 通过 `venue_by_name` 映射关联
- 如果已有 canonical venue_id，新变体映射到已有 ID

### 3.2 归一化步骤 (按顺序)

1. **精确别名映射** → canonical name（见别名表）
2. **去 @ / . 前缀**
3. **去括号标注**: `(推测)` `(未明确)` `(待定)` `(昆明)` 等
4. **去城市前缀**: `昆明 VERVO` → `VERVO`
5. **去斜杠组合**: `Dada Shanghai / Dada Beijing` → 取第一个
6. **去冒号地址**: `Dada Shanghai: 幸福路115号` → `Dada Shanghai`
7. **去楼层后缀**: `ROOM 2`, `大厅`, `MAIN ROOM`
8. **提取标注中的场地名**: `推测为VERVO所在地` → `VERVO`
9. **Trim 空白**

### 3.3 别名映射表

| 原始 | Canonical |
|------|-----------|
| OIL油, OIL CLUB, OIL油 Mainroom | OIL |
| JAR这儿 | JAR |
| ALL俱乐部, /\|\| | ALL |
| FOUNDATION俱乐部 | FOUNDATION |
| Elevator上海 | Elevator |
| Heim Shanghai | Heim |
| VERVO国际独立电音俱乐部 + 全部变体 | VERVO |
| Dada Bar Beijing | Dada Beijing |
| Dada Bar Shanghai | Dada Shanghai |
| TAGChengdu, .TAG + 变体 | TAG |
| BO LIVE(福田店) | BO LIVE |
| POTENT CLUB | POTENT |
| ZhaoDai, 招待 | ZhaoDai |

完整列表见 `normalize_venue_names.py` 的 `ALIAS_MAP`。

---

## 4. same_event_count 计算规则

### 4.1 算法
```sql
SELECT e1.dj_id, e2.dj_id, COUNT(DISTINCT e1.event_id) as same_event_count
FROM dj_event e1
JOIN dj_event e2 ON e1.event_id = e2.event_id AND e1.dj_id < e2.dj_id
GROUP BY e1.dj_id, e2.dj_id
```

### 4.2 执行时机
- 每次 `normalize_atlas_entities.py` 的 entity merge 之后
- 每次 `export_atlas_miniapp_json.py` 导出前（可选，作为验证）

---

## 5. 已知场地列表 (129 个 Docker 源)

### 5.1 核心场地 (高事件量)

| Canonical 名称 | venue_id | 城市 |
|---------------|----------|------|
| OIL | venue:7bf09a4d03e119b8 | 深圳 |
| Dada Beijing | venue:c4b3d7a230944517 | 北京 |
| BO LIVE | venue:5f1aa545df578532 | 深圳 |
| VERVO | venue:558cc9363a70d0a5 | 昆明 |
| Dada Kunming | venue:85b989a2228f24e2 | 昆明 |
| ALL | venue:443fc3ba5acaa1f1 | 上海 |
| C's Bar | venue:03fcaea15c7b7f98 | 上海 |
| Elevator | venue:f54bd02ec871d661 | 上海 |
| JAR | venue:a1fd19f9dd165a41 | 西安 |
| ZhaoDai | venue:8e6155f98e1f2bc7 | 北京 |
| TAG | venue:83158cd2a3e5e1bc | 成都 |
| AXIS | venue:04d89ab002f06bfd | 成都 |
| FOUNDATION | venue:4fee5dcb050e4091 | 南京 |
| POTENT | venue:25c89ab74db2df1e | 上海 |
| wigwam | venue:5442b5abff3d1308 | 上海 |
| Heim | venue:c9414ed97fcdc24d | 上海 |

### 5.2 新场地 (待加入)

| 名称 | 地址 | 城市 |
|------|------|------|
| 门洞商店 | 杭州市拱墅区湖墅南路439号氧气公寓1楼 | 杭州 |

---

## 6. 实施脚本

| 脚本 | 作用 | 是否修改 venue_id |
|------|------|------------------|
| `normalize_atlas_entities.py` | Entity merge + same_event_count 重算 | 否 |
| `normalize_venue_names.py` | venue_name 归一化 | **否** (仅改 display name) |
| `export_atlas_miniapp_json.py` | 导出 JSON | 否 (只读) |

---

## 7. 验证清单

- [ ] venue_id 在归一化前后不变
- [ ] same_event_count = 实际共享 event_id 数量
- [ ] venue_name 不再包含标注文字（推测/未明确等）
- [ ] 导出 JSON 中 OIL油→OIL, JAR这儿→JAR, TAGChengdu→TAG 等
- [ ] subject 表的 venue display_name 已归一化
- [ ] venue_by_name 的 key 使用归一化后的名称
