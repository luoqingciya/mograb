# MoGrab 文档中心

欢迎查阅 MoGrab `1.0.0` 文档。下面按使用角色列出全部文档入口，点击链接即可直达。

---

## 快速上手（用户向）

- [用户使用指南](guide/user-guide.md) —— 安装包选择、Tauri v2 桌面端 6 大页面操作说明、双主题切换、便携模式与 `config.toml` 全项配置参考
- [CLI 命令完全参考](guide/cli-reference.md) —— `mog` 全局选项、退出码与全部 14 组子命令参数及示例
- [安全政策](../SECURITY.md) —— `1.0.x` 正式版安全支持范围与漏洞私密报告指引

## 写书源（规则作者必读）

- **[写书源从入门到实战教程](source-spec/writing-a-source.md)** —— 从脚手架生成（`mog source init`）、抓包、逐块编写规则、5 套进阶场景 Cookbook（JSON API / POST / 分页倒序 / GBK / 广告清理）、离线测试验收闭环到常见报错排错
- [Source Specification v1](source-spec/source-spec-v1.md) —— 已冻结的完整书源 DSL 规范，涵盖严格校验、提取器语义、Transform 执行顺序与安全边界
- [官方参考示例书源](../tests/fixtures/example-source/README.md) —— 内置在仓库测试中的标准四能力示例与快照夹具

## 系统规范与架构（贡献者向）

- [架构总览](architecture/overview.md) —— Core / API / CLI / Tauri Desktop 四层架构、依赖流向与关键技术选型
- [Domain Model v1](domain-model/domain-model-v1.md) —— Book / Chapter / Source / Task 实体与任务状态机
- [Storage v1](storage/storage-v1.md) —— SQLite WAL 表结构、索引与迁移约定
- [API v1](api/api-v1.md) —— REST API（24 条路由）、Bearer 鉴权与 SSE 任务事件流契约
- [架构决策记录 (ADR)](architecture/decisions/README.md) —— 仓库布局、书源版本字段、Rust 解析与 EPUB 选型、本地 API 鉴权决策

## 开发、CI 与项目历史

- [开发环境搭建](development/getting-started.md) —— Rust 工具链、Tauri 构建依赖、本地运行与提交流程
- [开发约定与常见坑点](development/conventions.md) —— 工程约定、文档内链校验与历史踩坑记录
- [CI 与发布流水线](development/ci.md) —— GitHub Actions CI/Release 工作流与跨平台打包产物规范
- [项目进度](progress.md) —— 质量指标、里程碑状态与进度唯一出处
- [更新日志](../CHANGELOG.md) —— 从 `1.0.0rc0` 到 `1.0.0` 正式版的完整变更历史
- [规划评估报告](evaluation/规划评估报告.md) / [原始规划书](planning/项目规划书.md) —— 历史设计评估与溯源存档（非当前实现规范）
