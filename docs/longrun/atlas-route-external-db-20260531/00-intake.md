# Intake

Updated: 2026-05-31 06:10 CST

## User Commands Consolidated

- 全量整理所有路由管线。
- 全量整理所有外链抓取。
- 整理所有数据库 / DB1 DB2 DB3。
- 统一所有字段，避免空字段覆盖原字段。
- 恢复手机端 DJ-DJ、DJ-场地、场地-DJ 关系和历史演出。
- 加入随便听听 / mixtape，但优先考虑版权，最好跳转原链接。
- 地址和坐标必须重新确认，不能用旧地址/旧坐标糊弄。
- 可以运行微信云开发、上传、生产部署、CLI 检查、自唤醒、自执行、自优化、并行代理。

## Product Interpretation

Atlas 是地下电子音乐场景的存档与留存系统，不是评论/评分系统。核心价值是小 DJ 的演出记录、历史同台关系、常去场地、mixtape/outlink 证据，以及对应公众号/source evidence 的可追溯归档。

## Success Criteria

- 有一个可重复生成的路由/外链/数据库 inventory。
- 所有字段统一修改前都有字段契约和风险队列。
- 地址/坐标修复只接受可验证来源，无法确认的保持 blocked。
- 手机端能展示历史演出、关系、常去场地、mixtape/outlinks，并遵守版权跳转边界。
- CloudRun/小程序上传只在验证通过且存在运行时变更时执行。
- 最新 SSOT 和接手文档能让新 agent 从一个入口继续。
