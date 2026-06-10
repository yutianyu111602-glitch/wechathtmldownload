# 安全与隐私文档

项目: wechat-ingest (wechathtmldownload)
审计日期: 2026-06-10
状态: 报告

## 1. 敏感信息总览

审计范围: 项目根目录、services/、apps/、tools/、profiles/

### 已确认的敏感信息

| 类型 | 文件路径 | 字段/变量名 | 处理建议 | 风险等级 |
|---|---|---|---|---|
| API Key | services/weekly_activity_cloudrun/.env | DEEPSEEK_API_KEY | 立即轮换；确保 .env 不在 Git 中 | **极高** |
| CloudBase ID | services/weekly_activity_cloudrun/.env | CLOUDBASE_ENV_ID | 不属高敏但建议不公开 | 低 |
| CloudBase ID | cloudbaserc.json | envId | 已追踪于 Git，建议确认公开风险 | 中 |

### 未发现但需警惕的

| 类型 | 应查找位置 | 当前状态 |
|---|---|---|
| WeChat App Secret | apps/weekly_activity_miniprogram/ | 未发现硬编码 |
| 微信支付密钥 | 全项目 | 未发现 |
| 数据库密码 | 全项目 | 未发现硬编码 |
| JWT Secret | 全项目 | 未发现 |
| 对象存储 AK/SK | 全项目 | 未发现 |
| 私钥文件 (.pem, .key) | 全项目 | 未发现 (.gitignore 中已排除) |
| 明文手机号/openid | 全项目 | 报告和数据库文件中可能存在但未在源码中硬编码 |

## 2. 疑似泄露点

1. **DEEPSEEK_API_KEY** (`services/weekly_activity_cloudrun/.env:2`)
   - 类型: API Key 明文
   - 风险: 极高 - 可被用于消耗 API 配额
   - 处理: 该文件已在 .gitignore 中排除 (`.env` 模式)
   - 建议: **立即在 DeepSeek 控制台轮换此 Key**，旧 Key 作废

2. **cloudbaserc.json** 含 CloudBase 环境 ID
   - 类型: 环境标识符
   - 风险: 中 - envId 本身不授予访问权限但暴露基础设施信息
   - 处理: 如仓库公开，建议移除或替换为占位值

## 3. 建议加入 .gitignore 的规则

已在 `.gitignore.proposed` 中完整覆盖。关键新增规则:

```gitignore
# Secrets
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.crt
secrets/
credentials/

# Database artifacts
*.sqlite
*.sqlite3
*.db
*.dump
*.sql

# Large data
*.tar.gz
*.zip
reports/**/*.sqlite
```

## 4. .env.example 变量清单

| 变量名 | 用途 | 环境 |
|---|---|---|
| DEEPSEEK_API_KEY | DeepSeek API 认证 | 生产/测试 |
| CLOUDBASE_ENV_ID | 腾讯云 CloudBase 环境 | 生产 |
| WECHAT_APP_ID | 微信小程序 AppID | 生产 |
| WECHAT_APP_SECRET | 微信小程序密钥 | 生产 |
| DATABASE_URL | 数据库连接串 | 生产 |
| REDIS_URL | Redis 连接串 | 生产 |

## 5. 环境配置分层

| 环境 | 配置来源 | SECRET_KEY 来源 | DEBUG |
|---|---|---|---|
| 本地开发 | .env (不提交) | 环境变量 | True |
| 测试 | .env.test | 环境变量 | False |
| 生产 (CloudRun) | CloudBase 环境变量 | 平台注入 | False |

## 6. 数据脱敏建议

- **openid / unionid**: 生产数据中不可提取到源码或文档
- **手机号 / 身份证**: 如数据库中存在，导出时必须脱敏
- **WeChat 文章内容**: 版权内容，不可公开发布原文
- **DJ/场地数据**: 公开信息 (来自公开 WeChat 文章)，可分享脱敏统计

## 7. 上传 GitHub 前检查清单

- [x] .env 已在 .gitignore 中排除
- [x] .env 文件未被 Git 追踪 (`git ls-files .env` 无输出)
- [ ] **轮换 DEEPSEEK_API_KEY** (旧 Key 在会话中暴露)
- [x] 数据库文件 (.sqlite) 未被追踪
- [x] 无证书/私钥文件被追踪
- [ ] 确认 cloudbaserc.json 的 envId 公开风险可接受
- [ ] 检查 apps/*/project.private.config.json 不含敏感值
- [ ] 检查 profiles/ 目录无本地绝对路径

## 8. 密钥泄露后处理

如果发现密钥已被提交到 Git 历史 (当前检查: .env 未被追踪):

1. 立即在服务提供商控制台轮换密钥
2. 使用 `git filter-branch` 或 `BFG Repo-Cleaner` 清理历史
3. 强制推送 (`git push --force`) 覆盖远程历史
4. 通知所有相关方密钥已轮换
5. 检查 API 使用日志确认无异常消耗
6. 更新所有环境中的密钥值
