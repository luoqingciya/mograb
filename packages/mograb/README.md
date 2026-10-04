# mograb —— MoGrab Core

MoGrab 核心引擎：声明式书源（Source DSL）、网络层、任务引擎、存储与导出。

本包是**唯一**的业务实现所在。CLI 与 Desktop 不得复制此处的逻辑。

## 模块地图

| 模块 | 职责 |
|------|------|
| `mograb.app` | composition root：CLI 与 API 共用的装配入口 |
| `mograb.domain` | 领域模型（Book / Chapter / Source / Task） |
| `mograb.source` | 书源加载、校验、执行、fixture 测试 |
| `mograb.network` | HTTP 客户端、缓存、限流、重试 |
| `mograb.task` | 队列、Worker 池、调度、生命周期 |
| `mograb.content` | 正文清洗、规范化、校验 |
| `mograb.storage` | ORM 模型、仓储接口、SQLite 实现 |
| `mograb.export` | TXT / Markdown / EPUB |
| `mograb.config` | 配置与跨平台路径 |
| `mograb.logging` | 结构化日志与脱敏 |
| `mograb.errors` | 统一错误层次 |

各模块的契约在 `docs/` 下的规范里，不在本文件重复：

- 领域模型、任务状态机、错误层次 → [Domain Model v1](../../docs/domain-model/domain-model-v1.md)
- 书源 DSL → [Source Specification v1](../../docs/source-spec/source-spec-v1.md)
- 表结构与仓储 → [Storage v1](../../docs/storage/storage-v1.md)
- 分层与边界 → [架构总览](../../docs/architecture/overview.md)

## 使用

```python
from mograb.source import load_source_file, SourceEngine, lint

spec = load_source_file("tests/fixtures/example-source/source.yaml")
report = lint(spec)
assert report.is_ready
```

## 架构边界

```
Source   └── 规则        Network  └── 网络
Parser   └── 解析        Content  └── 清洗
Task     └── 调度        Storage  └── 持久化
Exporter └── 导出
```

禁止越权，例如 Exporter 不得直接请求网络，Source 不得直接操作数据库。

## 许可证

GPL-3.0-only
