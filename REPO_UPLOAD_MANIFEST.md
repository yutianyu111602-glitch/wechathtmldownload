# REPO_UPLOAD_MANIFEST

项目: wechat-ingest (wechathtmldownload)
生成日期: 2026-06-10
用途: 上传 GitHub 私人仓库前判断哪些文件应提交、哪些应排除

## 建议值说明

| 值 | 含义 |
|---|---|
| MUST_UPLOAD | 必须上传，项目核心代码 |
| SHOULD_UPLOAD | 建议上传，辅助接手 |
| DO_NOT_UPLOAD | 禁止上传，含敏感信息或大型制品 |
| EXTERNAL_ARTIFACT | 外部制品，记录在 EXTERNAL_ARTIFACTS_MANIFEST.md |
| NEED_HUMAN_REVIEW | 需人工确认后决定 |

## 资产清单

| 分类 | 路径 | 建议 | 理由 | 风险 |
|---|---|---|---|---|
| **核心源码** | | | | |
| TypeScript 源码 | src/ | MUST_UPLOAD | 管道核心代码 (23 子目录) | 低 |
| CLI 入口 | src/cli.ts, src/historyCli.ts | MUST_UPLOAD | 命令行入口 | 低 |
| 类型定义 | src/types.ts | MUST_UPLOAD | 共享类型 | 低 |
| 工具脚本 | tools/stage7_rewrite/scripts/ | MUST_UPLOAD | Stage7 Python 管道脚本 | 低 |
| 工具测试 | tools/stage7_rewrite/tests/ | MUST_UPLOAD | Stage7 测试 | 低 |
| 管道模块 | pipelines/ | MUST_UPLOAD | 管道配置 | 低 |
| 服务模块 | services/ | MUST_UPLOAD | CloudRun 服务 | 中 |
| **桌面应用** | | | | |
| Electron 主进程 | desktop/main.mjs | MUST_UPLOAD | 桌面应用入口 | 低 |
| PCUI 模块 | desktop/renderer.js | MUST_UPLOAD | 渲染进程 | 低 |
| **微信小程序** | | | | |
| 小程序页面 | apps/weekly_activity_miniprogram/pages/ | MUST_UPLOAD | 前端页面源码 | 低 |
| 小程序组件 | apps/weekly_activity_miniprogram/components/ | MUST_UPLOAD | 前端组件 | 低 |
| 小程序工具 | apps/weekly_activity_miniprogram/utils/ | MUST_UPLOAD | 工具函数 | 低 |
| 小程序服务 | apps/weekly_activity_miniprogram/services/ | MUST_UPLOAD | API 调用封装 | 低 |
| 小程序测试 | apps/weekly_activity_miniprogram/tests/ | MUST_UPLOAD | 129 个测试 | 低 |
| 小程序配置 | apps/weekly_activity_miniprogram/app.js/json/wxss | MUST_UPLOAD | 入口文件 | 低 |
| 小程序 project.config.json | apps/weekly_activity_miniprogram/project.config.json | NEED_HUMAN_REVIEW | 含开发者工具配置，可能含 appid | 高 |
| **配置与依赖** | | | | |
| package.json | package.json | MUST_UPLOAD | Node 依赖与脚本 | 低 |
| package-lock.json | package-lock.json | MUST_UPLOAD | 锁定依赖版本 | 低 |
| tsconfig.json | tsconfig.json | MUST_UPLOAD | TypeScript 配置 | 低 |
| mkdocs.yml | mkdocs.yml | SHOULD_UPLOAD | 文档站点配置 | 低 |
| cloudbaserc.json | cloudbaserc.json | NEED_HUMAN_REVIEW | 含 CloudBase envId | 中 |
| **文档** | | | | |
| README.md | README.md | MUST_UPLOAD | 项目入口说明 | 低 |
| AGENTS.md | AGENTS.md | MUST_UPLOAD | AI Agent 规则 | 低 |
| CHANGELOG.md | CHANGELOG.md | SHOULD_UPLOAD | 变更历史 | 低 |
| LONGRUN_STATE.md | LONGRUN_STATE.md | SHOULD_UPLOAD | 长跑状态 | 低 |
| docs/ 目录 | docs/ | MUST_UPLOAD | 项目文档 | 低 |
| **脚本** | | | | |
| scripts/ | scripts/ | MUST_UPLOAD | 辅助脚本 | 低 |
| prompts/ | prompts/ | SHOULD_UPLOAD | LLM Prompt 模板 | 低 |
| profiles/ | profiles/ | NEED_HUMAN_REVIEW | 运行配置，可能含路径 | 中 |
| **vendor** | | | | |
| vendor/ | vendor/ | NEED_HUMAN_REVIEW | 第三方 vendor 代码 | 中 |
| **禁止上传** | | | | |
| 环境变量 | .env, services/weekly_activity_cloudrun/.env | DO_NOT_UPLOAD | 含真实 DEEPSEEK_API_KEY | 极高 |
| 数据库文件 | reports/**/*.sqlite, *.db, *.sqlite3 | DO_NOT_UPLOAD | 大型数据文件 (数GB) | 极高 |
| 日志文件 | logs/, *.log, *.log.err | DO_NOT_UPLOAD | 运行时日志 | 高 |
| 编译产物 | dist/, build/, node_modules/ | DO_NOT_UPLOAD | 自动生成 | 低 |
| 临时文件 | tmp/, tmp-*, temp/, .cache/ | DO_NOT_UPLOAD | 临时文件 | 中 |
| IDE 配置 | .vscode/, .idea/ | DO_NOT_UPLOAD | 个人 IDE 配置 | 低 |
| Python 缓存 | __pycache__/, .pytest_cache/, .venv/ | DO_NOT_UPLOAD | Python 缓存 | 低 |
| 运行时状态 | *.pid, HEARTBEAT.json | DO_NOT_UPLOAD | 运行时文件 | 低 |
| **外部制品** | | | | |
| 大型 SQLite | reports/*/atlas_serving.sqlite | EXTERNAL_ARTIFACT | 1.6GB+ 地图数据库 | 低 |
| 合并数据库 | /tmp/atlas_merged.sqlite | EXTERNAL_ARTIFACT | 3.8GB 源数据库 | 低 |
| 报告目录 | reports/ (不含 sqlite) | SHOULD_UPLOAD | 历史报告证据 | 中 |
| 制品目录 | artifacts/ | NEED_HUMAN_REVIEW | 构建制品 | 中 |
| **历史移交文档** | | | | |
| HANDOFF 文件 | HANDOFF*.md, NEXT_AGENT_HANDOFF*.md | SHOULD_UPLOAD | 历史移交记录 | 低 |
| NIGHT_WATCHER | NIGHT_WATCHER_*.md, NIGHT_WATCHER_*.log | DO_NOT_UPLOAD | 日志文件过大 | 中 |
| **杂项** | | | | |
| audits/ | audits/ | SHOULD_UPLOAD | 审计记录 | 低 |
| runs/ | runs/ | DO_NOT_UPLOAD | 运行时数据 | 高 |
| .git/ | .git/ | DO_NOT_UPLOAD | Git 内部数据 | 低 |
| .gitignore | .gitignore | MUST_UPLOAD | Git 忽略规则 | 低 |
| .gitignore.proposed | .gitignore.proposed | MUST_UPLOAD | 建议忽略规则 | 低 |
| .env.example | .env.example | MUST_UPLOAD | 环境变量模板 | 低 |
| .understand-anything/ | .understand-anything/ | DO_NOT_UPLOAD | 代码理解缓存 | 低 |
| .codegraph/ | .codegraph/ | DO_NOT_UPLOAD | 代码图谱缓存 | 低 |

## 上传前检查清单

- [ ] .env 文件已排除
- [ ] 所有 .sqlite / .db 文件已排除
- [ ] node_modules/ 已排除
- [ ] dist/ build/ 已排除
- [ ] logs/ 和 *.log 已排除
- [ ] tmp/ 临时目录已排除
- [ ] cloudbaserc.json 含 envId - 需人工确认
- [ ] apps/*/project.private.config.json 需检查
- [ ] profiles/ 目录可能有本地路径引用
