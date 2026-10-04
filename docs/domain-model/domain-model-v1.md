# MoGrab Domain Model v1

> 状态：已冻结
> 版本：v1
> 生效日期：2026-10-04
> 对应[原始规划书](../planning/项目规划书.md)（历史存档，非规范）：§6、§17、§9
> Python 映射：`mograb/domain/`

---

## 1. 设计原则

### 1.1 核心模型稳定，外围可替换

```
可替换：HTTP Client · HTML Parser · Database · Exporter · CLI · Desktop
稳定：  Book · Chapter · Source · Task
```

领域层**只依赖 pydantic 与标准库**，不得依赖 httpx / sqlalchemy / fastapi。
这保证了：更换数据库或 HTTP 库时，领域模型与业务逻辑零改动。

### 1.2 内部 ID 与来源 ID 分离

> **绝不把来源站 ID 直接当主键。**

| ID 类型 | 字段 | 作用 |
|---------|------|------|
| MoGrab 内部 ID | `id` | 主键。ULID，全局唯一且单调递增 |
| 来源站 ID | `source_*_id` | 用于增量更新、去重、回溯来源 |

理由：来源站 ID 可能变更、可能跨站冲突、可能为 URL 形式。
若作为主键，站点改版会导致本地数据失效。

内部 ID 是 ULID（`mograb.domain.ids`）。选它而不是 `uuid4` 的原因：
前 48 位是毫秒时间戳，所以**按 ID 排序就等于按创建时间排序** ——
排查问题时看一串 ID 就能看出先后，不用再去 join 时间字段。
编码用 Crockford Base32（去掉了 I / L / O / U），26 个字符，
复制粘贴和口头念都不容易错。

带类型前缀的写法是 `new_id("book")` → `book_01J8X2QK...`，
前缀是为了看日志和翻数据库时一眼能认出对象类型。

### 1.3 严格模式

所有领域模型使用 `extra="forbid"`。未知字段导致校验失败，
避免上游拼写错误被静默吞掉。

---

## 2. Source

```python
class SourceSpec:
    spec_version: int  # 规范版本（v1 = 1）
    id: str
    name: str
    version: str  # 书源自身语义化版本
    homepage: str | None
    description: str | None
    license: str | None
    authors: list[str]

    engine_min_version: str | None
    engine_max_version: str | None

    capabilities: list[SourceCapability]

    network: NetworkPolicy
    permissions: Permissions

    search: SearchSpec | None
    book: BookSpec | None
    chapters: ChapterSpec | None
    content: ContentSpec | None

    transforms: list[Transform]
```

完整定义见 [`source-spec-v1.md`](../source-spec/source-spec-v1.md)。

### 2.1 能力判断

```python
source.supports(SourceCapability.SEARCH) -> bool
```

Core **不得假定**能力存在。未声明能力时调用对应方法抛 `SourceUnsupportedError`。

### 2.2 InstalledSource

`SourceSpec` 只包含规范里定义的字段，是书源作者写的东西。
「装没装、启没启用、体检什么结果、从哪个版本升上来的」属于 MoGrab 自己的记账，
放在 `InstalledSource` 里：

```python
class InstalledSource:
    spec: SourceSpec
    enabled: bool
    health: HealthStatus
    installed_version: str
    previous_version: str | None
    installed_at: datetime | None
    updated_at: datetime | None
```

分开的理由：导出书源时不该把本机状态带出去。存储层返回这个类型，
调度器取 `entry.spec` 用即可，挑源时用 `entry.is_usable`
（启用，且健康度不是 broken / unsupported）。

---

## 3. Book

```python
class Book:
    # --- 标识 ---
    id: str  # MoGrab 内部 ID（ULID）
    source_id: str
    source_book_id: str  # 来源站标识

    # --- 来源位置 ---
    url: str  # 详情页 URL，抓目录和更新都要用

    # --- 元数据（书源提供）---
    title: str
    author: str | None
    intro: str | None
    language: str | None  # BCP-47，如 zh-CN
    cover_url: str | None
    status: BookStatus
    latest_chapter: str | None

    # --- 派生统计（Core 维护）---
    cover_path: str | None  # 已下载封面的本地相对路径
    word_count: int
    chapter_count: int

    # --- 时间戳 ---
    created_at: datetime
    updated_at: datetime

    # --- 扩展 ---
    metadata: dict[str, Any]
```

### 3.1 唯一性约束

```
(source_id, source_book_id)  唯一
```

`Book.identity` 属性返回该二元组，供幂等写入使用。

### 3.2 字段来源划分（重要）

| 类别 | 字段 | 谁能写 |
|------|------|-------|
| 书源元数据 | `title` `author` `intro` `language` `cover_url` `status` `latest_chapter` | Source Engine |
| 来源位置 | `url` | Source Engine（登记时写入，之后不改） |
| 派生统计 | `word_count` `chapter_count` `cover_path` | Content / Storage 层 |
| 系统字段 | `id` `created_at` `updated_at` | Storage 层 |

书源**不得**写入派生统计字段。`metadata` 用于承载书源自定义的附加字段，
不得用于承载核心语义。

`url` 是必须的：书源里的 `chapters.request.url` 写的是 `{{book.url}}`，
没有它就没法抓目录，也没法做增量更新。`source_book_id` 不能顶替 ——
书源给了 `id` 字段时它是个站内编号（比如 `1001`），不是 URL。

> 这几个字段是相对原始规划书补的：`language` / `word_count` / `chapter_count` / `cover_path`。
> 详见评估报告 P1-04。`url` 是实现调度器时发现缺的。

### 3.3 BookStatus

| 值 | 含义 |
|----|------|
| `unknown` | 未解析出（默认） |
| `ongoing` | 连载中 |
| `completed` | 已完结 |

---

## 4. Chapter

```python
class Chapter:
    # --- 标识 ---
    id: str  # MoGrab 内部 ID
    book_id: str
    source_chapter_id: str | None

    # --- 内容元数据 ---
    title: str
    url: str
    index: int

    # --- 正文 ---
    content: str | None
    content_hash: str | None
    word_count: int

    # --- 时间戳 ---
    created_at: datetime
    updated_at: datetime
```

### 4.1 章节身份（Chapter Identity）

去重**不能只依赖章节序号**——站点可能插入卷标、重复章节、调整顺序。

身份按以下优先级解析：

| 优先级 | 依据 | 键格式 |
|--------|------|--------|
| 1 | `source_chapter_id` | `sid:<id>` |
| 2 | 规范化 URL | `url:<normalized_url>` |
| 3 | 序号 + 标题（兜底） | `idx:<index>:<title>` |

`Chapter.identity_key` 返回主身份键，用于数据库唯一索引。

### 4.2 增量更新使用**候选键集合**（重要）

单键匹配存在缺陷：若书源某次更新后不再返回 `source_chapter_id`，
本地章节的主键是 `sid:c1`，而远程草稿的主键是 `url:https://...`，
两者不相等 → **整本书被误判为全新章节**。

因此 `compute_chapter_diff` 使用**候选键集合求交集**：

```python
# 本地章节的候选键
{"sid:c1", "url:https://example.com/book/1001/chapter/1"}

# 远程草稿的候选键
{"url:https://example.com/book/1001/chapter/1"}

# 交集非空 → 匹配成功
```

这使 diff 对「ID 可用性变化」保持鲁棒。

### 4.3 URL 规范化

`normalize_url()` 的处理：

- 协议与主机小写化，去除默认端口（`:80` / `:443`）
- 移除 fragment
- 移除追踪参数（`utm_*` / `from` / `ref` / `share` / `spm` / `sid` / `t` 等）
- query 参数按 key 排序（顺序无关）
- 去除路径尾部多余斜杠（保留根路径 `/`）

```
输入: https://Example.com/Book/12/?utm_source=x&b=2&a=1#frag
输出: https://example.com/Book/12?a=1&b=2
```

### 4.4 内容哈希

`compute_content_hash()`：

- 算法：**BLAKE2b-128**（快、碰撞率足够低）
- 归一化：先折叠空白再哈希（避免仅空白差异被误判为内容变化）

用于检测「同一章节的内容是否变化」，是增量更新判定 `changed` 的依据。

> 变更哈希算法需要迁移既有数据，因此算法固定。

---

## 5. Task

```python
class Task:
    id: str
    type: TaskType
    status: TaskStatus
    priority: int  # 0–100

    source_id: str | None
    book_id: str | None

    total: int
    completed: int
    failed: int
    retry_count: int
    max_retries: int

    resume_cursor: int | None  # 断点续传

    error_code: str | None
    error_message: str | None

    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
```

### 5.1 状态机（形式化）

> 原始规划书 §17 列出了状态但**未定义转移规则**。本节将其形式化。

```
PENDING   → RUNNING | PAUSED | CANCELLED
RUNNING   → PAUSED | RETRYING | SUCCESS | FAILED | CANCELLED
PAUSED    → PENDING | RUNNING | CANCELLED | FAILED
RETRYING  → RUNNING | FAILED | CANCELLED
SUCCESS   → ∅（终态）
FAILED    → ∅（终态）
CANCELLED → ∅（终态）
```

**唯一合法变更入口**：`Task.transition_to(status)`。
非法转移抛 `InvalidTaskTransitionError`。

**终态不可逆**：重试通过创建**新任务**实现（`TaskManager.retry`），
而非复活旧任务。这保证任务历史的不可篡改性。

### 5.2 TaskType

| 值 | 说明 |
|----|------|
| `download_book` | 下载整本书 |
| `update_book` | 增量更新 |
| `export_book` | 导出 |
| `refresh_source` | 刷新书源 |

### 5.3 TaskItem

任务下的单个工作单元（通常是一章）：

```python
class TaskItem:
    id: str
    task_id: str
    chapter_id: str | None
    chapter_index: int | None
    title: str | None
    status: TaskItemStatus  # pending/running/success/failed/skipped/cancelled
    attempts: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
```

`SKIPPED` 表示「已存在且内容未变，跳过下载」——增量更新的正常结果，非失败。

---

## 6. ExportRecord

```python
class ExportRecord:
    id: str
    book_id: str
    format: ExportFormat
    status: ExportStatus
    path: str | None  # 完成前是 None
    size_bytes: int
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
```

导出是**异步作业**（API v1 §4.7）：创建时返回 id，之后查状态。
所以这条记录要能表达「排队中 → 进行中 → 完成/失败」的整个过程，
而不只是一条历史流水。`path` 在作业完成前拿不到 —— 这正是当初把导出
裁决成异步的原因之一。

`is_terminal` 判断是否已结束（成功或失败）。

---

## 7. 枚举清单

| 枚举 | 取值 |
|------|------|
| `SourceCapability` | `search` `book` `chapters` `content` \| `discover` `image` `login` `cookie` `update`（保留） |
| `BookStatus` | `unknown` `ongoing` `completed` |
| `TaskType` | `download_book` `update_book` `export_book` `refresh_source` |
| `TaskStatus` | `pending` `running` `paused` `retrying` `success` `failed` `cancelled` |
| `TaskItemStatus` | `pending` `running` `success` `failed` `skipped` `cancelled` |
| `ExportFormat` | `txt` `markdown` `epub` |
| `ExportStatus` | `pending` `running` `success` `failed` |
| `HealthStatus` | `healthy` `degraded` `broken` `unsupported` `unknown` |
| `ChapterChangeKind` | `new` `changed` `missing` `unchanged` |

所有枚举均为 `str` 子类，可直接序列化到 JSON / SQLite / API。

---

## 8. 错误层次

```
MoGrabError                       code: MOGRAB_ERROR
├── ConfigError                   CONFIG_ERROR
├── SourceError                   SOURCE_ERROR
│   ├── SourceSchemaError         SOURCE_SCHEMA_ERROR      立即失败，不重试
│   ├── SourceExecutionError      SOURCE_EXECUTION_ERROR   站点结构变化
│   ├── SourceUnsupportedError    SOURCE_UNSUPPORTED_ERROR
│   └── SourceNotFoundError       SOURCE_NOT_FOUND
├── NetworkError                  NETWORK_ERROR            retryable=True
│   ├── TimeoutError_             NETWORK_TIMEOUT
│   ├── RateLimitedError          NETWORK_RATE_LIMITED     携带 retry_after
│   └── HttpStatusError           NETWORK_HTTP_STATUS      5xx/429 可重试
├── ParseError                    PARSE_ERROR              不自动重试
├── ContentValidationError        CONTENT_VALIDATION_ERROR 不自动重试
├── TaskError                     TASK_ERROR
│   ├── TaskNotFoundError         TASK_NOT_FOUND
│   ├── TaskParameterError        TASK_PARAMETER_ERROR      建任务参数不成立
│   ├── InvalidTaskTransitionError TASK_INVALID_TRANSITION
│   └── TaskCancelledError        TASK_CANCELLED
├── StorageError                  STORAGE_ERROR
│   └── EntityNotFoundError       STORAGE_NOT_FOUND
└── ExportError                   EXPORT_ERROR
    └── UnsafePathError           EXPORT_UNSAFE_PATH
```

### 8.1 `retryable` 属性

每个错误类携带 `retryable: bool`，由 `RetryPolicy` 直接读取。
**避免在重试策略中散落 `isinstance` 判断**—— 这是刻意加的补充，原始规划书没提。

| 错误 | retryable |
|------|-----------|
| `NetworkError` 及其子类 | `True` |
| `HttpStatusError`（5xx / 429） | `True` |
| `HttpStatusError`（4xx） | `False` |
| `ParseError` | `False` |
| `ContentValidationError` | `False` |
| `SourceSchemaError` | `False` |

### 7.2 错误 → API 响应

```json
{
  "code": "SOURCE_PARSE_FAILED",
  "message": "...",
  "details": {}
}
```

HTTP 状态码映射见 [`api-v1.md`](../api/api-v1.md) §6。

---

## 9. 变更政策

| 变更 | 处理 |
|------|------|
| 新增可选字段 | 兼容，记录于 minor |
| 新增枚举值 | 需确认所有 `match` 语句有 default 分支 |
| 修改字段语义 | **破坏性**，需同步更新本文档与 Storage schema |
| 删除字段 | **破坏性** |
| 新增错误类型 | 兼容，但需同步 API 错误映射 |
