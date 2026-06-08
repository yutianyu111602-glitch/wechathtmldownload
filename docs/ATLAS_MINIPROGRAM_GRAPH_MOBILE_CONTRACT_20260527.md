# Atlas Mini Program Graph Mobile Contract

## Goal

Atlas 最终要进入微信小程序。小程序不承载桌面 3D 全图，默认承载一个可滑动、可点击、可解释的实体探索面板：搜索一个 DJ/俱乐部后，用户能看到历史活动、关系分、同一实体/别名、信息来源、音响系统证据，并能继续点进去漫游。

## Mobile First Flow

1. 搜索或点击实体名。
2. 请求 `GET /api/v1/stage7/graph/mobile-profile?q=...` 或 `?id=...`。
3. 首屏只渲染 `header`、`quickActions`、`sections[aliases/history/relationships/sound_system]`。
4. 每个 row/chip 都读自己的 `tap` 对象执行跳转，不在前端硬编码路由。
5. 用户点“关系漫游”时再请求 `navigation.graphSeedApi`，只拿 `limit=48&lod=focus` 的 bounded graph。
6. 用户点来源时打开 source evidence，不展示本地路径、raw DB、内部 candidate id。

## API

```text
GET /api/v1/stage7/graph/mobile-profile?q=Loopy
GET /api/v1/stage7/graph/mobile-profile?id=venue:all
```

Response schema: `stage7_atlas_api.graph_mobile_profile.v1`

When `ATLAS_ENTITY_MERGE_GROUPS_PATH` points to the DeepSeek merge sidecar, the backend applies a read-time canonical overlay:

- searching an alias returns the canonical entity first;
- opening an alias subject id returns the canonical profile;
- graph seed/subgraph starts from the canonical subject;
- profile sections aggregate across all merge-group members, so a canonical organizer/club brand can still show venue history, DJ relationship scores, source refs, and sound-system evidence from its venue aliases;
- the raw serving SQLite is not mutated.

Important fields:

- `header`: 手机首屏标题、类型、统计 chips。
- `quickActions`: 固定操作区，如关系漫游、同名搜索、看来源。
- `entityMerge`: DeepSeek 合并计划 sidecar，默认 `reportOnly: true`；展示为“同一实体 / 别名”，不能写回生产事实。
- `sections`: 小程序列表直接渲染的数据块。
- `sections[].items[].tap`: 每一行的点击动作，前端按 `action/apiPath/query/id/sourceRefId` 执行。
- `payloadPolicy`: 明确这是微信端 bounded focus，不允许全图导出。
- `retrieval.entityMergeSidecarEnabled` / `soundSystemSidecarEnabled`: 当前后端是否接入了可选 sidecar。
- `retrieval.entityMergePlan`: 后端 profile 使用的合并组摘要；用于调试/灰度，不作为用户可见“官方合并”文案。

## Sections

- `aliases`: 同一实体/别名 chips。例：Loopy、loopy Club、杭州 Loopy、LOOPY俱乐部。
- `history`: 历史活动 timeline。每条可点到 event detail。
- `relationships`: DJ/实体关系分列表。展示 `relationshipScore`，不要展示“同台次数”作为主指标。
- `organizations`: 主办/厂牌关系。
- `venues`: 常出现地点。
- `sound_system`: 俱乐部音响系统证据。展示 terms、confidence、source snippet；这是 venue attribute，不是实体合并依据。
- `sources`: 信息来源列表。每条可点击。

## Interaction Rules

- 手机端默认是列表和底部面板，不默认打开 3D/Canvas。
- 图谱只在用户点“关系漫游”后加载 bounded focus graph。
- 所有可点击元素由后端 `tap` 提供动作，前端不要猜 id。
- 多选关系探索在手机上做成“关系篮子”：用户把两个或多个实体加入篮子后，再请求 graph seed/expand 或后续 relation-path API。
- 搜索结果、别名、关系、来源、音响证据都必须可点。
- 音响系统是重要信息，但不能混入实体身份合并；`OIL Soundsystem` 这类 row 展示在 sound/evidence 或 review，不吞进 OIL 主实体。
- DeepSeek merge group 在正式 promotion gate 前只显示 `reportOnly` 候选，不标成“官方已合并”。

## Backend Files

- API route: `services\weekly_activity_cloudrun\src\server.mjs`
- DTO builder: `services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs`
- Entity merge sidecar env: `ATLAS_ENTITY_MERGE_GROUPS_PATH`
- Sound-system sidecar env: `ATLAS_VENUE_SOUND_SYSTEM_EVIDENCE_PATH`

## Current Verification

- `node --test services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs`
- `npm test` from `services\weekly_activity_cloudrun`
- `python tools\stage7_rewrite\scripts\validate_atlas_entity_merge_outputs.py --out-dir reports\atlas_entity_merge_validation_current`
