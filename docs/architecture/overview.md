# MoGrab 架构总览

对应规划书 §3、§4、§38、§60、§61。

## 分层

```
                    ┌────────────────────┐
                    │   Electron Desktop │
                    │      Windows       │
                    └─────────┬──────────┘
                              │ REST + SSE
┌─────────────────────────────┼──────────────────────────┐
│                             ▼                          │
│              MoGrab API Server (FastAPI)               │
│                       /api/v1                          │
├────────────────────────────────────────────────────────┤
│  Source │ Search │ Book │ Task │ Download │ Export     │
├────────────────────────────────────────────────────────┤
│                 MoGrab Core Engine                     │
├────────────────────────────────────────────────────────┤
│   HTTP │ Cache │ Parser │ Transformer │ Storage        │
└────────────────────────┬───────────────────────────────┘
                         │
                   ┌─────▼─────┐
                   │  SQLite   │
                   └───────────┘
        ▲
        │ 同一套 Core，进程内调用，不走 HTTP
   ┌────┴────┐
   │   CLI   │
   └─────────┘
```

CLI 直接调 Core，桌面端走 HTTP 调 Core。两条路径共用同一套业务实现，
不存在"CLI 自己写了一份下载逻辑"这种事。

## 仓库结构

```
MoGrab/
├── pyproject.toml              uv workspace 根，本身不可安装
├── uv.lock
├── VERSION                     版本号唯一来源
├── README.md  LICENSE  CHANGELOG.md
├── CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md
├── THIRD_PARTY_LICENSES.md
│
├── packages/
│   └── mograb/                 核心库，唯一
│       ├── pyproject.toml
│       └── src/mograb/
│           ├── domain/         领域模型，最稳定的部分
│           ├── source/         书源加载、校验、执行
│           ├── network/        HTTP、缓存、限流、重试
│           ├── task/           队列、Worker、调度、生命周期
│           ├── storage/        ORM、仓储、SQLite
│           ├── content/        清洗、规范化、校验
│           ├── export/         TXT、Markdown、EPUB
│           ├── config/         配置与路径
│           ├── logging/        结构化日志与脱敏
│           ├── _version.py     从包元数据读版本
│           └── errors.py       统一错误层次
│
├── apps/
│   ├── cli/                    mograb-cli，命令名 mog
│   ├── api/                    mograb-api，FastAPI
│   └── desktop/                Electron，仅 Windows
│
├── sources/                   本地书源工作区，不进仓库（见下）
│
├── tests/
│   ├── unit/  integration/  source/
│   └── fixtures/
│       └── example-source/    参考书源 + HTML 快照，兼测试数据
│
├── docs/
│   ├── architecture/           本目录
│   ├── source-spec/            Source Specification v1
│   ├── domain-model/           Domain Model v1
│   ├── storage/                Storage v1
│   ├── api/                    API v1
│   ├── development/            开发指南
│   └── evaluation/             规划评估报告
│
├── scripts/
└── .github/workflows/
```

### 书源为什么不进仓库

`sources/` 在 `.gitignore` 里，永远不提交。原因是书源描述的是针对具体第三方站点的
抓取规则，把它随主仓库一起分发，容易让项目被误解成"某个站点的专用工具"，
也会把站点改版、失效、条款变动这些事带进主仓库的历史里。

所以职责拆成两半：

- **主仓库**只提供规范、引擎和工具链。参考实现放在 `tests/fixtures/example-source/`，
  用 `example.com`（IANA 保留域名），不指向任何真实站点。
- **书源**由使用者自己写、自己留。要分享就直接发 `source.yaml` 或 `.mgs` 文件。

这条边界也让 CI 更干净：`source-lint` 只校验仓库里的参考实现，
不会因为某个外部站点挂掉就红。

### 为什么只有一个核心包

规划书 §4、§5、§59 给了三套互相冲突的结构，这里选了单核心包加双应用。

§4 和 §59 的"七个独立包"在当前阶段属于过度设计。七个包意味着七份
`pyproject.toml`、七组版本号、复杂的跨包依赖约束，而换来的"可以单独发布"
这个能力，对 network、task、storage 这些模块来说并不成立 —— 它们本来就是
为同一个产品的同一条流程服务的。

§5 的模块划分是三套里最具体的，也基本和 §59 的目录名同构，所以拿它的划分
放在 §59 的 `packages/` 语义下。

模块边界靠导入约束守，不靠包边界。§61 要求的那些边界（Exporter 不许请求网络
之类）用包边界来强制并非不可替代，而代价是持续的版本管理负担。

详见 [ADR-0001](decisions/ADR-0001-monorepo-layout.md)。

## 边界

规划书 §61 列了这张表，实现时基本是照着它在拆模块。

| 模块 | 只管 |
|------|------|
| `Source` | 规则：请求什么、从哪取、怎么提取、怎么转换 |
| `Network` | 网络：连接、缓存、限流、重试 |
| `Parser` | 解析：HTML、JSON、文本 |
| `Content` | 清洗：正文净化、规范化、校验 |
| `Task` | 调度：队列、并发、状态机 |
| `Storage` | 持久化：仓储、事务 |
| `Exporter` | 导出：格式生成 |
| `API` | 对外能力 |
| `CLI` | 命令行交互 |
| `Desktop` | 图形交互 |

不能越的界：

```
Exporter  不许请求网络
Source    不许操作数据库
Desktop   不许直接改 DB
Parser    不许决定下载任务
CLI       不许自己实现下载
Desktop   不许自己实现解析
Source    不许执行任意代码
```

这些约束怎么落地的：

| 边界 | 手段 |
|------|------|
| Source 不碰数据库 | `SourceEngine` 只依赖 `Fetcher` 协议，不 import storage |
| Exporter 不碰网络 | `Exporter` 协议只接受 `Book` + `list[Chapter]` + `Path` |
| Parser 不决定任务 | `extract_*` 是纯函数，没有副作用 |
| Desktop 不碰 DB | Electron 只能通过 HTTP 访问 API |
| 领域层不依赖基础设施 | `mograb.domain` 只 import pydantic 和标准库 |

## 数据流

### 搜索

```
CLI / API
  ↓ SourceEngine.search(source, keyword)
TemplateContext(keyword) → build_request → RenderedRequest
  ↓ Fetcher.fetch  [Network: 缓存 → 限流 → 重试 → httpx]
Document
  ↓ extract_many(list_rule, field_rules)   [Parser]
rows
  ↓ apply_transforms_many(transforms, base_url)   [Transformer]
SearchResult[]
```

### 下载

```
创建任务 → 队列 → Worker
  ↓
读书籍信息（engine.fetch_book）
  ↓
读章节目录（engine.fetch_chapters）
  ↓
compute_chapter_diff(local, remote)     增量更新的核心
  ↓
下载（并发受 SourceLimiter 约束）
  ↓
清洗 + 校验（ContentPipeline）
  ↓
落库（单事务）
  ↓
导出（可选）
```

### 增量更新

```
本地目录（DB）
     +
远程目录（engine.fetch_chapters）
     ↓
compute_chapter_diff
     ↓
new / changed / missing / unchanged
     ↓
只把 new 和 changed 排进下载任务
```

## 并发

```
GlobalLimiter(concurrency=8)
        │
        ├── SourceLimiter["example"](concurrency=2, interval=500ms)
        ├── SourceLimiter["other"](concurrency=5, interval=200ms)
        └── ...
```

实际并发取 `min(全局, 本源的)`。

底层是 asyncio + httpx.AsyncClient + 有界 worker 池。

| 层级 | 作用 | 配置项 |
|------|------|-------|
| `GlobalLimiter` | 保护本机资源 | `download.concurrency` |
| `SourceLimiter` | 保护目标站点 | 书源的 `network.concurrency`，或全局的 `download.per_source_concurrency` |

关键点：不同来源不能共用同一个限流器。`SourceLimiterRegistry` 按 `source_id`
维护独立实例。

## 错误与重试

```
出错
  ↓
归类成 MoGrabError 子类（带 code 和 retryable）
  ↓
RetryPolicy.should_retry(error, attempt)?
  ├─ 是 → 算退避（指数 + 抖动，尊重 Retry-After）→ 重试
  └─ 否 → 往上抛
       ↓
   Task Worker 捕获 → 更新 TaskItem 状态和错误码
       ↓
   API 层映射成 HTTP 状态码 + {code, message, details}
```

退避序列 1s → 2s → 4s → 8s，上限 60s，叠加 ±25% 抖动，避免多任务同时重试。

## 技术选型

| 层 | 选型 | 说明 |
|----|------|------|
| 语言 | Python ≥ 3.11 | 用到了 `StrEnum`、`datetime.UTC` |
| 依赖管理 | uv workspace | 只在开发和构建期用，不进发布产物 |
| API | FastAPI + uvicorn + sse-starlette | |
| 校验 | Pydantic v2 + pydantic-settings | |
| 解析 | lxml + cssselect + jsonpath-ng | 一个引擎覆盖 CSS 和 XPath |
| HTTP | httpx | 异步 |
| 存储 | SQLAlchemy 2.0 async + aiosqlite + Alembic | |
| 日志 | structlog | 结构化，带脱敏 |
| CLI | Typer + Rich | |
| 桌面端 | Electron + TypeScript | |
| 测试 | pytest + pytest-asyncio + pytest-cov | |
| 质量 | Ruff + Pyright + pre-commit | |

### 刻意不用的

| 库 | 原因 |
|----|------|
| `ebooklib` | AGPL-3.0，会给 GPL-3.0-only 带来额外分发义务。改成自研 EPUB 写入器 |
| `tenacity` | 需要按错误类型分类重试、按书源隔离策略，自研反而更直接 |
| `selectolax` | 不支持 XPath，而规范要求支持。留作可选加速依赖 |
| `platformdirs` | 改成便携模式后不再需要 |

## 开发顺序

规划书 §60 定的顺序，不要跳步。

```
Source Specification    已冻结
        ↓
Domain Model            已冻结
        ↓
Parser / Transformer    已实现，有测试
        ↓
HTTP Layer              已实现，有测试
        ↓
Storage                 仓储已全部实现，含书源、导出与 HTTP 缓存
        ↓
Task Engine             状态机、队列、Worker、下载编排均已实现
        ↓
Export                  已实现，有测试
        ↓
API                     已实现，22 个端点 + SSE
        ↓
CLI                     已实现，11 组命令
        ↓
Desktop                 骨架就位
```

Electron 界面放到最后。UI 是最容易看到成果的部分，但也是最难用来决定核心架构的
部分 —— 先做它会逼着核心去迁就界面。

## 质量基线

| 项 | 现状 |
|----|------|
| 测试 | 439 个通过（单元 / 集成 / CLI / API / 书源 fixture） |
| Lint | Ruff 无告警 |
| 类型 | Pyright 0 错误 |
| 覆盖率 | 83%，门槛设在 70% |

## 相关文档

- [Source Specification v1](../source-spec/source-spec-v1.md)
- [Domain Model v1](../domain-model/domain-model-v1.md)
- [Storage v1](../storage/storage-v1.md)
- [API v1](../api/api-v1.md)
- [规划评估报告](../evaluation/规划评估报告.md)
- [ADR](decisions/)
