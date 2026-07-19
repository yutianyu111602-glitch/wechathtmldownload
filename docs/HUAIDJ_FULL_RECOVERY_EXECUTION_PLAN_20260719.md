# HUAIDJ 小程序与全量活动管线灾后恢复执行计划（2026-07-19）

## 已确认基线

- 灾后发现源：`F:\code\githubstar\wechathtmldownload`，巨大脏树，只读保护。
- 当前干净集成线：`codex/weekly-visibility-20260719`，起点 `0b97884db33c`。
- 上一个已验证调度水位：`0cf57941a19f`。
- 当前线上小程序声明版本：`2026.07.18.002`。
- Hermes Desktop/Gateway 已安装且运行；jobs 指向 `0cf5794`，实际旧子进程仍出现 `603775c`，存在三方漂移。
- Sanji 0.4.1 与 CDP 正常；当前 96 小时增量不是本轮所需 744 小时恢复全量。
- 公网 current 为当前窗口，cities/dates 仍为旧 package 索引，已复现城市数字远大于列表的问题。

## Phase 0：保护与权威冻结

任务：

- 等当前 Fast Watch 自然结束，核对 lock 正常释放。
- 为仅由 reflog/对象库保护的提交建立 `rescue/*` refs。
- 保存 worktree/branch/ref/reflog/fsck 清单，备份 Hermes jobs、launcher 和 HKCU 非敏感 tuple。
- 固化 source/integration/runtime/public 四层权威矩阵。

验收：无文件丢失；无生产写；无 live job 被中断；所有候选提交可达。

## Phase 1：本机开发与代码图环境

任务：

- 通过 FlClash 和现有 GitHub 凭证固定安装官方 Code Review Graph v2.3.7。
- 隔离 uv tool 环境，外置 `CRG_DATA_DIR`，备份并 diff Codex MCP 配置。
- 不启用云 embeddings，不启动长期 daemon，不向脏树写图数据库。
- 为干净集成线构建图并记录 stats、版本和安装来源。

验收：CLI/version/status 可用；其他 MCP 未被覆盖；新 Codex 进程所需重载被明确记录。

## Phase 2：全功能修复

工作包：

1. 统一 visible projection：current/package、城市/日期、精确日期、周末范围、海报和分页。
2. generation hot sync：重复页/ID、游标单调性、跨页 total/generatedAt、最终唯一数校验、config 最后切换。
3. 日期业务语义：本周末周五至周日；今晚只限 Asia/Shanghai 业务日；切换城市保留模式。
4. 多城市活动：`city_key/city_keys/cityKey/cityKeys` 使用同一归一函数和同一 facet 集合。
5. 分页与代际：601/2001 条、游标循环、页数上限、generation 漂移全部失败关闭。
6. 声音采集：修复变量错误和首次写目录；公开响应移除付款截图/审核敏感字段，补真实 E2E。
7. 客户端安全：移除 About 明文管理口令和不存在导航；统一显示构建/数据身份。
8. Atlas 小程序：静态 bundle 与在线 neighborhood/artist/path 增加 generation 握手或明确降级。
9. 外置数据 hydration：测试使用明确的 current/Atlas/column 身份，不把陈旧 6 月制品当当前生产。

验收：新增回归用例先复现再转绿；不以调小数字、截断数据或删除功能作为修复。

## Phase 3：全量本地与真实工具验收

测试层：

- Node/小程序、CloudRun、Python 全套测试零失败。
- 静态全链审计、secret scan、schema/quality/release guard 全绿。
- 故障注入：重复 ID、重复页、坏游标、游标循环、代际漂移、缺失制品、首次空目录、网络降级。
- 真实微信开发者工具 CLI：online、CloudBase、最后成功缓存和灾备 seed 四种加载状态。
- 渲染：首页、周末、今晚、多城市、详情、地图、Atlas、声音、采访；零运行时异常。

验收：报告外置保存；任何 fixture 污染均使证据无效。

## Phase 4：Git 集成与不可变发布

任务：

- 审阅 weekly 与 pipeline 的 range-diff，吸收恢复线独有且仍有效的文档提交。
- 提交、secret scan、推送恢复分支，验证远端 SHA。
- 从新 SHA 创建干净 detached release；运行 release 内自检。
- 保留 `0cf5794` 作回滚，不把目录名与实际 HEAD 不符的树称为 immutable。

验收：build/release/remote 三方 SHA 一致；worktree clean；运行数据全部外置。

## Phase 5：Hermes 调度权威切换

任务：

- 等 live Fast Watch 终止后，备份当前 jobs/launcher/HKCU tuple。
- 一次性对齐新 release、现有 py311、外部 report root 和 FlClash 代理。
- installer `--apply` 一次，二次 dry-run 必须 no-change；contract audit 必须 0/0。
- 先跑 Fast Watch、health、package monitor 无付费 canary；仅在子进程仍继承旧路径时安静重载 Gateway。

验收：9 个 active jobs、7 个 launcher 和实际 child command 全来自新 release；唯一 wall-clock owner；legacy jobs 保持 paused。

## Phase 6：744 小时 Sanji 与模型候选

任务：

- 真实 Sanji Desktop refresh/export，覆盖 744 小时并生成 DB snapshot。
- 校验 missing HTML ledger/digest；逐项恢复抓取直至 unresolved=0。
- 固定 snapshot，先运行不部署的 QwenVL 海报直接理解和 DeepSeek 富化全量候选。
- 验证来源、日期、城市、海报、阵容、去重、最小条数、模型失败/回退和 current/package scope。

验收：任何 unresolved 或模型失败均阻断；续跑使用同一 snapshot，不无条件重复付费全量。

## Phase 7：后端与热数据发布

任务：

- 同一不可变 release 显式部署 CloudRun revision。
- 公网全分页回读 manifest/current/cities/dates/items，抽查城市、日期、周末和 package。
- 部署 `weeklyDataSync`，执行 generation hot sync，保存 syncId，再从 CloudBase 同代读回。
- 验证 facet 数等于对应全分页唯一列表数，current/package 差异有解释。

验收：CloudRun 与 CloudBase 身份、总数、城市、日期完全一致；旧代仍可回滚，新代失败不得激活。

## Phase 8：小程序上传、审核与公开验证

任务：

- 活动增量只走在线数据，不因数据变化默认上传前端。
- 本轮有前端修复，因此使用真实微信开发者工具 CLI 和干净 staging 上传新开发版本。
- 保存 seed SHA、Git SHA、CloudRun revision、CloudBase syncId、tool/SDK 版本和 upload-info。
- 分别记录提审、审核通过、公开发布和真机公开版回读。

验收：开发上传不冒充公开发布；公开版的日期、城市数字和列表在真机上一致。

## Phase 9：AtlasV2 派生候选

任务：

- Sanji 文章 lane 通过 missing HTML/OCR/DeepSeek/Qwen fallback 与候选验证。
- 活动 sidecar 使用稳定 event IDs 和 evidence refs 合并到派生 candidate。
- 执行 SQLite quick_check、表/行数、输入输出哈希、水位与 source namespace 验证。
- 保持 current serving pointer 不变，除非独立 serving materialization/promotion gate 全绿。

验收：活动导入得到 `source_namespace_only` 证据；不写 canonical relation tables，不自动合并 2416 个同名身份组。

## Phase 10：Git 整理、SSOT 与长期维护

任务：

- 主脏树和 DB2 大分叉先做可验证备份；生成 retained/archive/removal manifest。
- 只有无运行引用、提交受保护、worktree clean 的中间 release 才进入精确移除清单。
- 不执行 `git clean`/`reset --hard`；移除后重跑 refs/status/fsck。
- 更新 README、AGENTS、current-runtime、code map、API/CLI 文档、运行手册、Code Review Graph 图谱、HUAIDJ skill 和 Codex 长期记忆。

验收：新维护者只读当前 SSOT 即可定位源码、运行时、任务、数据、部署和回滚；所有状态可由报告复核。
