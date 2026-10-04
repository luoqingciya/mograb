# mograb —— MoGrab Core

MoGrab 核心引擎：声明式书源（Source DSL）、网络层、任务引擎、存储与导出。

本包是**唯一**的业务实现所在。CLI 与 Desktop 不得复制此处的逻辑。

## 模块地图

| 模块 | 职责 | 对应规划书 |
|------|------|-----------|
| `mograb.domain` | 领域模型（Book / Chapter / Source / Task） | §6 |
| `mograb.source` | 书源加载、校验、执行 | §7–§12 |
| `mograb.network` | HTTP 客户端、缓存、限流、重试 | §14–§16 |
| `mograb.task` | 队列、Worker 池、调度、生命周期 | §17–§20 |
| `mograb.content` | 正文清洗、规范化、校验 | §21–§22 |
| `mograb.storage` | ORM 模型、仓储接口、SQLite 实现 | §23–§25 |
| `mograb.export` | TXT / Markdown / EPUB | §26–§28 |
| `mograb.config` | 配置与跨平台路径 | §23、§35 |
| `mograb.logging` | 结构化日志与脱敏 | §36 |
| `mograb.errors` | 统一错误层次 | §37 |

## 使用

```python
from mograb.source import load_source_file, SourceEngine, lint

spec = load_source_file("sources/official/example/source.yaml")
report = lint(spec)
assert report.is_ready
```

## 架构边界（规划书 §61）

```
Source   └── 规则        Network  └── 网络
Parser   └── 解析        Content  └── 清洗
Task     └── 调度        Storage  └── 持久化
Exporter └── 导出
```

禁止越权，例如 Exporter 不得直接请求网络，Source 不得直接操作数据库。

## 许可证

GPL-3.0-only
