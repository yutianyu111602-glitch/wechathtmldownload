# 本地开发 SOP — 09_LOCAL_DEV_SOP.md

项目: wechat-ingest
更新: 2026-06-10

## 前置条件

| 依赖 | 版本要求 | 安装方式 |
|---|---|---|
| Node.js | >= 20 | https://nodejs.org |
| Python | >= 3.11 | https://python.org (或 WSL) |
| 微信开发者工具 | 最新稳定版 | https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html |
| Git | 最新版 | https://git-scm.com |
| WSL2 (可选) | Ubuntu | 用于 Python Stage7 和数据库操作 |

## 1. 克隆仓库

```powershell
git clone https://github.com/yutianyu111602-glitch/wechathtmldownload-private.git
cd wechathtmldownload-private
```

## 2. 安装 Node.js 依赖

```powershell
npm install
```

## 3. 构建 TypeScript

```powershell
npm run build
```

预期输出: 无错误，生成 dist/ 目录

## 4. 配置环境变量

```powershell
copy .env.example .env
# 编辑 .env，填入 DeepSeek API Key (本地开发可选)
```

## 5. Python Stage7 环境 (WSL)

```bash
# 在 WSL 中
cd /mnt/c/code/githubstar/wechathtmldownload-private
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/stage7_rewrite/requirements.txt  # 如存在
# 或使用 uv (如果项目使用)
uv sync --directory tools/stage7_rewrite
```

## 6. 运行测试

```powershell
# TypeScript 编译检查
npm run build

# 微信小程序测试 (129 tests)
node apps/weekly_activity_miniprogram/tests/smoke-test.cjs

# Python Stage7 测试 (在 WSL 中)
python -m pytest tools/stage7_rewrite/tests/ -q --timeout=30
```

## 7. 启动微信小程序开发

1. 打开微信开发者工具
2. 导入项目: `apps\weekly_activity_miniprogram`
3. 填入 AppID: wx0bc0a1d9d892af2d (或选"测试号")
4. 勾选"不校验合法域名"
5. 编译运行

## 8. 启动本地 API 服务

```powershell
cd services\weekly_activity_cloudrun
npm install
npm start
# 服务监听 http://localhost:8787
```

## 9. 启动桌面应用

```powershell
npm run start:gui
```

## 10. 管道 CLI 试运行

```powershell
# 处理单篇文章 (dry-run)
npm run process-article -- --help

# 归档批处理
npm run archive-batch -- --help

# Markdown 导出
npm run export-markitdown-batch -- --help
```

## 11. 常见问题

| 问题 | 解决方案 |
|---|---|
| `tsc` 找不到 | `npm install` 后重试 |
| Python 模块缺失 | `pip install -r requirements.txt` |
| 小程序无法编译 | 检查 project.config.json 中 appid |
| 本地 API 无数据 | 需要 serving SQLite 文件 (1.6GB)，从外部获取 |
| `D:\rawwechat` 不存在 | 正常 - 管道输入为外部数据源 |
| `node_modules` 过大 | 正常 - 开发依赖，不提交 Git |

## 12. 最小可运行环境

如果不涉及数据处理，仅开发小程序前端：

```powershell
# 仅需
npm install        # 小程序测试依赖 (miniprogram-automator)
# 在微信开发者工具中打开 apps\weekly_activity_miniprogram
# 不需要: Python, WSL, SQLite 数据库
```

如果要运行完整管道：

```powershell
# 需要全部依赖 + DeepSeek API key + 源数据
# 源数据为外部制品，不包含在仓库中
# 见 EXTERNAL_ARTIFACTS_MANIFEST.md
```
