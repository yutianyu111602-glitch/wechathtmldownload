# HUAIDJ Sanji 1.1.x 全量公众号与活动增量稳定运行手册

状态日期：2026-08-05（Asia/Shanghai）

## 1. 目标与不可越过的边界

本运行线只接受 Sanji 1.1.x 原生「微信通道」：

- `source_mode=sanji_desktop_client`
- `source_contract=sanji_wechat_client.v1`
- `channel=wechat_client`
- `coverage_scope=broadcast_only`
- 后台 `appmsgpublish` 通道必须关闭
- `sanji_desktop_rss` 仅保留为旧调用方兼容别名，不能代表真实 RSS 抓取

全量活动发布必须依次证明：活动账号范围冻结、128/128 同步完成、凭证门禁通过、Sanji 数据库只读快照、原子 `generation.json`、Qwen/DeepSeek 结果、增量合并、质量门禁、CloudRun/CloudBase 回读，以及 AtlasV2 独立状态机证据。

以下操作不属于本运行线的默认权限：修改 FlClash/系统网络、绕过微信限流、启用旧 RSS/后台通道、上传小程序前端、提交审核或发布小程序。`UploadFrontend` 必须保持 `false`，除非另有明确授权。

## 2. 官方版本事实

- [v1.1.0](https://github.com/zoro-build/wechat/releases/tag/v1.1.0)：新增微信通道抓文章列表；凭证在同步弹窗内获取；无文章账号可使用公众号主页链接；已失效的公众号后台通道被禁用；证书信任失败会快速终止。
- [v1.1.1](https://github.com/zoro-build/wechat/releases/tag/v1.1.1)：同步默认范围收窄为最近一周，并调整微信限流提示。
- [v1.1.2](https://github.com/zoro-build/wechat/releases/tag/v1.1.2)：Windows `certutil` 改用 System32 绝对路径。

本机已核验安装 `C:\Program Files\sanji\sanji.exe` v1.1.2。官网安装与激活说明见 [wechat.zoro.build](https://wechat.zoro.build/guide/install-activate)。

## 3. 当前恢复断点

- 账号注册表：132 个。
- 活动账号：128 个。
- 停业/不再授权：4 个，保留停用原因，不进入同步范围。
- Sanji 与活动注册表：缺失 0、额外未注册 0。
- 周期：`sanji_client_20260805_evening_168h_active`。
- 完成：107/128；待继续：21。
- 第 108 个账号触发微信 `ret=-6 / client_rate_limited`。
- 断点账本：`F:\DevData\HuaidjRuntime\state\reports\sanji_v110_stable_20260805\sanji_client_20260805_evening_168h_active.json`。
- 账本已绑定活动账号顺序哈希、固定 `cutoff_ts`、Sanji 日志 SHA-256、严格前缀集合、限流事件和覆盖门禁；不含 cookie、token、证书或代理秘密值。

微信限流存在时必须硬停止。不要循环重试、不要 `resume`、不要切换旧接口。维护者提示同一微信账号通常需要约 24 小时冷却；若选择其他微信账号，必须由操作者明确决定，不能由任务自行切换。

## 4. 冷却后的单命令续跑

确认微信限流已解除、Sanji 捕获状态不再显示限流，并为剩余账号取得有效列表凭证后，从不可变 release 执行：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\stage7_rewrite\run_huaidj_sanji_daily_twice.ps1 `
  -Slot manual `
  -DeployBackend `
  -SanjiRefreshCutoffHours 168 `
  -SanjiSyncCycleId sanji_client_20260805_evening_168h_active `
  -SanjiCompletionLedgerPath F:\DevData\HuaidjRuntime\state\reports\sanji_v110_stable_20260805\sanji_client_20260805_evening_168h_active.json
```

不要传 `-UploadFrontend`。命令将跳过账本中已完成的 107 个账号，只处理剩余账号；任一新限流会再次硬停止并保留断点。

列表同步窗口固定为 168 小时；同步完成后的本地数据库快照与缺正文复查仍保留 31 天范围。两者用途不同，不能把 31 天快照误作 31 天微信列表请求。

## 5. 管线门禁顺序

1. 生成 `sanji_client_account_scope.v1`，要求 128 个活动账号全部在 Sanji，停用账号不进入范围。
2. 用固定周期、固定账号哈希和固定 `cutoff_ts` 顺序同步；账号间隔默认 15 秒。
3. 凭证缺失时只处理已就绪账号；全量发布必须最终达到 128/128。
4. 拉取文章正文与资源，复查 post-fetch 缺正文账本；未解决项大于 0 时停止。
5. 从 Sanji SQLite 在线备份生成不可变快照，写入 `generation.json`、文件哈希和语义计数。
6. Qwen-VL 默认 `qwen3_vl / qwen3.6-plus`、全图片、并发 4；DeepSeek 并发 4。未发布的 Qwen 版本不得进入正式运行。
7. 构建活动增量并与权威 `current_release` 合并，生成 `club_overviews.json`。
8. 发布前比较本地与线上完整活动 ID 集合及 SHA-256，不能只比较 `item_count`。
9. 事务式部署 CloudRun/CloudBase，逐项回读 manifest、current、detail、来源映射、俱乐部总览和健康端点。
10. AtlasV2 由独立 Hermes 状态机消费同一冻结 generation；周活动发布脚本不得伪造 Atlas 已导入。

## 6. 2026-08-05 发现的亮点

- Sanji 原生日志可以恢复可信断点：107 个完成集合严格等于活动范围前 107 个，第 108 个与限流账号一致。
- Sanji 内部执行顺序可能不同于注册表顺序，因此恢复必须验证“完成集合等于严格前缀”，不能强制比较日志顺序。
- 旧批次首次开始时间减 168 小时仍早于新账本截止时间，证明旧批次覆盖不窄于当前周期。
- 账号范围哈希和固定截止时间使跨日续跑不会因日期变化而扩大或缩小数据边界。
- 线上活动包完整分页得到 684 个唯一 ID；本地 July-28 包与线上 ID 集合 SHA-256 完全一致，可作为当前权威增量基线。
- 本地过期的 626 项 runtime 基线已被 684 项权威包替换；旧目录移入可恢复备份，没有删除。
- 新恢复器在部署前校验线上完整 ID 集合，堵住“数量相同但活动集合不同”的漂移。
- 公众号抓取、活动构建、CloudRun 发布、小程序前端上传、AtlasV2 导入是五个独立状态转换，任何一个成功都不能替代其他状态的回读证据。

## 7. 坑点与故障处置

- `last_status=ok`、包装脚本退出 0、后端 smoke 或单个 manifest 都不代表全量发布成功。
- 凭证约 30 分钟有效；取得凭证后应尽快同步。凭证就绪数量不能替代完成账本数量。
- `paused_error` 中含 `client_rate_limited`、`rate limit` 或 `ret=-6` 时禁止自动 resume。
- Sanji 日志不直接记录每个账号的 cutoff；日志恢复器用首次开始时间减请求小时数作为保守上界，并与账本 cutoff 比较。
- 干净 Git worktree 不包含真实 Atlas 大文件。全量 Node 测试必须使用 `scripts/testing/run_huaidj_full_tests_external.ps1` 的外置水化契约，不能把大文件写回 Git。
- 当前 July-28 活动包已超过 72 小时，完整外置测试会按设计阻断；必须先生成本轮新包。
- `npm ci` 下载 Electron 可能受当前网络链路影响而 `ECONNRESET`。不得为此修改 FlClash；使用已验证 release 依赖或 CI 清洁主机重跑。
- 线上基线当前缺少 `/readyz` 和 `/api/v1/weekly/club-overviews`，只有新包生成并通过门禁后才能部署补齐。

## 8. 恢复工具

- `build_sanji_client_account_scope.py`：生成活动账号冻结范围与哈希。
- `sanji_desktop_cdp_control.mjs`：Sanji 1.1.x CDP 控制、顺序同步、限流硬停、原子断点账本。
- `seed_sanji_completion_ledger_from_log.py`：从 Sanji JSONL 日志恢复严格前缀完成证据。
- `recover_weekly_authoritative_base.py`：按线上完整分页 ID 集合恢复/校验权威 `current_release`，旧目录可恢复备份。
- `run_sanji_desktop_recent_export.ps1`：同步、正文抓取、SQLite 快照与原子 generation。
- `run_huaidj_sanji_daily_twice.ps1`：全链路入口；支持跨日显式周期与账本续跑。

所有状态报告只记录路径、哈希、计数、阶段和脱敏错误；不得记录微信凭证、cookie、token、许可证或代理秘密。
