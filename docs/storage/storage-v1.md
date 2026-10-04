# MoGrab Storage v1

> 状态：已冻结
> 版本：v1
> 生效日期：2026-10-04
> 对应[原始规划书](../planning/项目规划书.md)（历史存档，非规范）：§23、§24、§25、§39
> Python 映射：`mograb/storage/`

---

## 1. 技术选型

**SQLite**（经 SQLAlchemy 2.0 async + aiosqlite）。

| 理由 | 说明 |
|------|------|
| 单机优先 | MoGrab 是个人工具，无需部署数据库 |
| CLI / Desktop 通用 | 同一份数据文件，两种前端共享 |
| 零部署 | 用户无需安装任何数据库服务 |
| 迁移简单 | 单文件，备份即复制 |
| 可抽象 | 通过 Repository 协议隔离，未来可换 PostgreSQL |

**连接配置**：

```sql
PRAGMA journal_mode = WAL;      -- 提升并发读性能
PRAGMA foreign_keys = ON;       -- 启用外键约束
PRAGMA synchronous = NORMAL;    -- WAL 下的合理折衷
```

---

## 2. 数据目录

便携模式：所有运行期数据都放在程序运行目录下的 `data/` 里，不写系统目录。
打包后跟随可执行文件，开发时跟随当前工作目录。

```
<运行目录>/
├── mog.exe  /  _internal/          程序
└── data/                           数据
    ├── config.toml       配置文件
    ├── mograb.db         SQLite 数据库
    ├── cache/            HTTP 缓存（可再生）
    ├── covers/           封面图片
    ├── logs/             app.log / task.log / source.log
    ├── exports/          导出产物
    └── sources/          已安装书源
```

环境变量 `MOGRAB_HOME` 可以覆盖数据目录位置，测试和特殊部署用。

之所以选便携模式而不是平台标准目录（`%APPDATA%` 之类）：这是个人工具，
用户更可能想要"拷走就能用、删掉就干净"。而且数据就在程序旁边，
"升级程序不能删用户数据"这件事天然成立，不需要额外的升级逻辑去保证。

代价是程序目录会混着程序文件和数据目录，所以升级时应该只替换可执行文件和
运行时文件，别整个目录覆盖。

---

## 3. 表结构

### 3.1 关系总览

```
sources ──< books ──< chapters
books   ──< tasks ──< task_items
books   ──< exports
http_cache   （独立）
settings     （键值）
```

### 3.2 通用约定

- 主键统一为 `TEXT`（ULID）
- 时间戳统一为 `TEXT`（UTC ISO-8601 字符串）——SQLite 无原生时间类型
- JSON 字段使用 SQLAlchemy `JSON` 类型（SQLite 下存为 TEXT）
- 所有表名小写复数

---

### 3.3 `sources` —— 已安装书源

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | TEXT | PK | 书源 ID |
| `name` | TEXT | NOT NULL | |
| `version` | TEXT | NOT NULL | 书源自身版本 |
| `spec_version` | INT | NOT NULL | 规范版本 |
| `homepage` | TEXT | | |
| `license` | TEXT | | |
| `capabilities` | JSON | NOT NULL | 能力列表 |
| `enabled` | BOOL | NOT NULL | 是否启用 |
| `installed_version` | TEXT | NOT NULL | 当前安装版本 |
| `previous_version` | TEXT | | 上一版本号，**纯诊断用**（见下） |
| `health` | TEXT | NOT NULL | healthy / degraded / broken / unsupported / unknown |
| `installed_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

> **`previous_version` 不用于回滚。** 回滚已明确不做，旧版本的定义文件也不保留
> （磁盘上只有单个 `data/sources/<id>/source.yaml`，新版本直接覆盖）。
> 这一列只记录「上一次装的是哪个版本」，`mog source show` 显示成
> 「版本变更 1.0.0 → 1.0.1」。
>
> 早期文档和 CLI 提示都写成「可回滚到 X」，那是错的 —— 命令根本不存在。

---

### 3.4 `books` —— 书籍

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | TEXT | PK | MoGrab 内部 ID |
| `source_id` | TEXT | FK → sources.id, INDEX | |
| `source_book_id` | TEXT | NOT NULL, INDEX | 来源站 ID |
| `url` | TEXT | NOT NULL | 详情页 URL，抓目录要用 |
| `title` | TEXT | NOT NULL, INDEX | |
| `author` | TEXT | INDEX | |
| `intro` | TEXT | | |
| `language` | TEXT | | BCP-47 |
| `cover_url` | TEXT | | |
| `cover_path` | TEXT | | 本地相对路径 |
| `status` | TEXT | NOT NULL | unknown / ongoing / completed |
| `latest_chapter` | TEXT | | 最新章节标题 |
| `word_count` | INT | NOT NULL | 派生 |
| `chapter_count` | INT | NOT NULL | 派生 |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL, INDEX | |
| `metadata` | JSON | NOT NULL | 书源自定义字段 |

**唯一约束**：`UNIQUE(source_id, source_book_id)`

保证幂等写入：同一本书重复入库时按该约束 upsert。

---

### 3.5 `chapters` —— 章节

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | TEXT | PK | |
| `book_id` | TEXT | FK → books.id, INDEX | |
| `source_chapter_id` | TEXT | | 来源站章节 ID |
| `identity_key` | TEXT | NOT NULL, INDEX | 见 domain-model §4.1 |
| `title` | TEXT | NOT NULL | |
| `url` | TEXT | NOT NULL | |
| `normalized_url` | TEXT | NOT NULL | 规范化 URL |
| `index` | INT | NOT NULL | 顺序 |
| `content` | TEXT | | 正文 |
| `content_hash` | TEXT | INDEX | BLAKE2b-128 |
| `word_count` | INT | NOT NULL | |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

**唯一约束**：`UNIQUE(book_id, identity_key)`

**复合索引**：`INDEX(book_id, index)` —— 目录顺序查询

> 正文与元数据同表存储（而非拆表）。理由：SQLite 对 TEXT 大字段的处理足够高效，
> 且正文查询几乎总是「按 book_id 顺序取全部」，同表避免 JOIN。

---

### 3.6 `tasks` —— 任务

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | TEXT | PK | |
| `type` | TEXT | NOT NULL, INDEX | |
| `status` | TEXT | NOT NULL, INDEX | |
| `priority` | INT | NOT NULL | 0–100 |
| `source_id` | TEXT | | |
| `book_id` | TEXT | FK → books.id, INDEX | |
| `total` / `completed` / `failed` | INT | NOT NULL | 进度 |
| `retry_count` / `max_retries` | INT | NOT NULL | |
| `resume_cursor` | INT | | 断点续传 |
| `error_code` / `error_message` | TEXT | | |
| `created_at` | TEXT | NOT NULL | |
| `started_at` / `finished_at` | TEXT | | |

**孤儿恢复**：进程启动时，所有 `status IN ('running','retrying')` 的行
被更新为 `failed` + `error_code='INTERRUPTED'`。

---

### 3.7 `task_items` —— 任务项

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | TEXT | PK | |
| `task_id` | TEXT | FK → tasks.id, INDEX | |
| `chapter_id` | TEXT | | |
| `chapter_index` | INT | | |
| `title` | TEXT | | |
| `status` | TEXT | NOT NULL, INDEX | pending/running/success/failed/skipped/cancelled |
| `attempts` | INT | NOT NULL | 尝试次数 |
| `error_code` / `error_message` | TEXT | | |
| `created_at` / `updated_at` | TEXT | NOT NULL | |

级联：`ON DELETE CASCADE`（删除任务时清理其 items）。

---

### 3.8 `exports` —— 导出记录

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | TEXT | PK | |
| `book_id` | TEXT | FK → books.id, INDEX | |
| `format` | TEXT | NOT NULL | txt / markdown / epub |
| `status` | TEXT | NOT NULL | pending/running/success/failed |
| `path` | TEXT | | 产物路径 |
| `size_bytes` | INT | NOT NULL | |
| `error_message` | TEXT | | |
| `created_at` | TEXT | NOT NULL | |
| `finished_at` | TEXT | | |

---

### 3.9 `http_cache` —— HTTP 缓存

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `key` | TEXT | PK | 见下 |
| `source_id` | TEXT | NOT NULL, INDEX | |
| `url` | TEXT | NOT NULL | |
| `status_code` | INT | NOT NULL | |
| `encoding` | TEXT | | |
| `content` | BLOB | NOT NULL | 响应体原始字节，不做文本化 |
| `created_at` | TEXT | NOT NULL | |
| `expires_at` | TEXT | NOT NULL | TTL 到期时间 |
| `accessed_at` | TEXT | NOT NULL, INDEX | 最近命中时间，容量淘汰按它排序 |
| `size_bytes` | INT | NOT NULL | |

**索引**：`INDEX(expires_at)` 用于批量清理过期条目；`INDEX(accessed_at)`
用于容量淘汰时排序。

**缓存键**（BLAKE2b-128 十六进制）由以下要素派生：

```
source_id · method · normalized_url · body_hash · relevant_header_flags
```

`relevant_header_flags` 仅记录 `accept` / `accept-language` / `cookie`
的**存在与否**（不记录值，避免 Cookie 泄漏）。

**失效策略**（三层）：

| 层级 | 机制 | 默认 |
|------|------|------|
| 条目级 | TTL | 列表/详情 30 分钟；正文 7 天 |
| 显式级 | `invalidate_url` / `invalidate_source` / `clear` | CLI `mog cache` |
| 容量级 | LRU 淘汰 | 超过 `cache.max_size`（默认 5GB） |

---

### 3.10 `settings` —— 键值配置

| 列 | 类型 | 约束 |
|----|------|------|
| `key` | TEXT | PK |
| `value` | TEXT | NOT NULL |
| `updated_at` | TEXT | NOT NULL |

用于承载用户级覆盖（优先于 `config.toml`）。

---

## 4. Repository 模式

> **业务层不得直接写 SQL。**

所有持久化通过仓储协议完成，以便替换底层数据库时不改动业务代码。

```python
class BookRepository(Protocol):
    async def get(self, book_id: str) -> Book | None: ...
    async def get_by_identity(self, source_id: str, source_book_id: str) -> Book | None: ...
    async def save(self, book: Book) -> None: ...
    async def list_all(self, *, limit: int = ..., offset: int = ...) -> list[Book]: ...
    async def delete(self, book_id: str) -> bool: ...
    async def count(self) -> int: ...
```

### 4.1 仓储清单

| 协议 | 实现 | 说明 |
|------|------|------|
| `SourceRepository` | `SqliteSourceRepository` | 书源安装 / 启停 / 卸载，见 §4.3 |
| `BookRepository` | `SqliteBookRepository` | |
| `ChapterRepository` | `SqliteChapterRepository` | 含本地全文搜索 `search_content`（见 §4.5） |
| `TaskRepository` | `SqliteTaskRepository` | 与 `mograb.task.manager.TaskRepository` 一致 |
| `ExportRepository` | `SqliteExportRepository` | 导出作业状态 |
| `SettingsRepository` | `SqliteSettingsRepository` | |
| `HttpCache`（网络层协议） | `SqliteHttpCache` | 三层失效，见 §4.4 |

### 4.2 所有方法均为 async

即使 SQLite 是同步的——由实现层用 aiosqlite 桥接，
保证接口不因后端而变。

### 4.3 书源仓储：磁盘 + 数据库

`SqliteSourceRepository` 是这个项目里唯一同时碰文件系统和数据库的仓储，
因为它持久化的不是一行数据，而是整个「已安装书源」聚合。分工是：

- **`<sources_dir>/<id>/source.yaml` 是定义的唯一真相。** 用户可以自己往里
  丢文件，换机器直接拷目录。
- **数据库那张表只记本机状态**：装没装、启没启用、体检结果、从哪个版本升上来的。
  这些不属于书源定义，导出书源时也不该带出去。

由此推出几条行为：

| 情况 | 处理 |
|------|------|
| 索引里有、文件没了 | 当没装处理，`get()` 返回 None，`list_all()` 跳过 |
| 文件坏了（YAML 不合法） | 跳过这一份，其余照常。单个坏书源不该拖垮整个列表 |
| 想重建索引 | `rescan()`：扫目录、逐份加载、写入索引，并删掉文件已消失的行 |
| `rescan()` 遇到已有行 | 只更新定义相关字段，`enabled` 和 `health` 保留 |

最后一条是有意的：用户手动关掉的开关，不该被一次扫描重置回打开。

`delete()` 会校验 ID 格式（`SOURCE_ID_RE`）再动文件系统，避免路径穿越。

### 4.4 HTTP 缓存的三层失效

`SqliteHttpCache` 把「必须提供失效策略」这条要求落成三层：

| 层级 | 机制 | 触发点 |
|------|------|--------|
| TTL | 条目自带 `expires_at` | `get()` 读到过期条目顺手删；`purge_expired()` 批量清 |
| 显式 | `invalidate_url` / `invalidate_source` / `clear` | 对应 `mog cache` 系列命令 |
| 容量 | `max_size_bytes` 满了按最久未访问淘汰 | `put()` 之后自动检查 |

关于容量淘汰的实现取舍：

- **近似 LRU**。严格 LRU 要在每次读取时回写 `accessed_at`，等于把缓存命中
  变成一次写库。这里按小时粒度更新（`ACCESS_REFRESH_INTERVAL`），
  排序精度够用，又不会让读操作频繁触发写入。
- **淘汰是一次批量删除**。先查出全部 `(key, size)` 按访问时间升序累减，
  再一条 `DELETE ... IN (...)`。比循环「查一条删一条」少很多次往返。
- `max_size_bytes=0` 表示不限容量，测试和临时场景用。

`content` 用 `LargeBinary` 存原始字节，不做文本化 —— 正文可能是 GBK 编码的
字节流，当文本存会坏。

### 4.5 本地全文搜索

`ChapterRepository.search_content(keyword, *, book_id=None, limit=50)`
是 `mog find` 的底座：在**已下载**的章节正文里找关键词，纯本地、不联网。

```python
async def search_content(...) -> list[ChapterSearchHit]: ...
```

返回 `ChapterSearchHit`（`book_id` / `book_title` / `chapter_id` /
`chapter_title` / `chapter_index` / `snippet`）。**只返回片段，不返回整章正文** ——
一本几千章的书，搜一次就把几十兆正文读进内存是不可接受的。

两个实现要点：

- **关键词里的 `%` 和 `_` 必须转义**（配合 `LIKE ... ESCAPE '\'`）。
  否则搜「100%」会退化成「100 开头且后面任意」，搜「a_b」会连「axb」一起命中。
- **空关键词直接返回空**。`LIKE '%%'` 会命中一切。

> **已知限制**：`LIKE '%kw%'` 用不上索引，是全表扫描。个人书库规模够用
> （几十兆正文约百毫秒级）；库再大就该上 FTS5 虚拟表，那要改 schema，
> 属于另一件事。指定 `book_id` 能把扫描范围缩到一本书。

---

## 5. 事务与数据一致性

> 核心约束：

```
Download → Validate → Transaction → Persist
```

**只有持久化成功后才把 TaskItem 标记为 SUCCESS。**

### 5.1 事务 API

```python
async with db.transaction() as session:
    for chapter in chapters:
        await repo.save(chapter, session=session)
    # 正常退出提交，异常回滚
```

### 5.2 批量写入必须单事务

```python
await chapter_repo.save_many(chapters)  # 单事务，保证原子性
```

若逐条提交，中途失败会留下「部分章节已入库、任务却标记失败」的不一致状态。

### 5.3 幂等写入

所有写入基于唯一约束 upsert：

| 表 | 唯一键 |
|----|-------|
| `books` | `(source_id, source_book_id)` |
| `chapters` | `(book_id, identity_key)` |

重复执行同一本书的下载不会产生重复数据。

---

## 6. 迁移

- **建表**：`Database.init_schema()` 使用 `Base.metadata.create_all`（幂等）
- **迁移**：正式迁移由 **Alembic** 负责（依赖已声明，`alembic/` 目录待建）

> 原始规划书的技术栈里没列迁移工具，但 v1.0 目标要求「Database migration 稳定」。
> 本仓库补充 Alembic，详见评估报告 P2-06。

### 6.1 迁移政策

| 变更 | 处理 |
|------|------|
| 新增表 | 常规 migration |
| 新增可空列 | 常规 migration |
| 新增非空列 | 需提供 default 值 |
| 修改列类型 | 需数据迁移脚本 |
| 删除列 | 需两个 minor 周期的弃用期 |

---

## 7. 性能考量

| 场景 | 措施 |
|------|------|
| 章节批量写入 | 单事务 + `save_many` |
| 目录顺序查询 | 复合索引 `(book_id, index)` |
| 书架列表 | `updated_at DESC` 索引 + 分页 |
| 缓存清理 | `expires_at` 索引 |
| 并发读写 | WAL 模式 |
| 大正文 | 同表存储，按 `book_id` 顺序批量读取 |

---

## 8. 备份与恢复

| 操作 | 方式 |
|------|------|
| 备份 | 复制 `mograb.db`（WAL 模式下建议先 `PRAGMA wal_checkpoint`） |
| 恢复 | 替换 `mograb.db` |
| 导出 | 由 Export Engine 负责（业务层导出，非数据库 dump） |

缓存（`cache/`）与封面（`covers/`）为可再生数据，不纳入备份范围。
