# MoGrab REST API v1

> 状态：已冻结
> 版本：`/api/v1`
> 生效日期：2026-10-04
> 对应[原始规划书](../planning/项目规划书.md)（历史存档，非规范）：§29、§30、§34、§37、§50
> 实现：`apps/api/src/mograb_api/`

---

## 1. 定位

MoGrab 是 **API-First** 项目：所有正式功能先进入 Core/API 层，
再由 CLI / Desktop 使用。

```
Desktop ─┐
         ├── API / Core ── Source Engine / Task Engine / Download / Export
CLI ─────┘
```

**禁止** CLI 或 Desktop 各自实现业务逻辑。

### 1.1 监听与信任边界

- 默认监听 `127.0.0.1:48721`（仅本机）
- CORS 仅允许 `http://127.0.0.1:*` / `http://localhost:*` / `file://`
- **第一版无认证**

> 已知风险：`localhost` 不等于安全。任何本机进程（包括浏览器中的恶意页面）
> 都可访问该端口。v0.4.0 引入 API 时必须增加**随机 token 校验**
> （写入 `config.toml`，CLI / Desktop 读取）。
> 仅靠 CORS 不足以防御「简单请求」场景。详见评估报告 P2-02。

---

## 2. 通用约定

| 项 | 约定 |
|----|------|
| 前缀 | `/api/v1` |
| 内容类型 | `application/json`（SSE 除外） |
| 时间戳 | ISO-8601 UTC 字符串 |
| ID | 字符串（ULID） |
| 分页 | `limit`（默认 50，上限 200）+ `offset` |

### 2.1 版本化政策

`/api/v1` 冻结后，**不轻易破坏**：

| 变更 | 处理 |
|------|------|
| 新增端点 | 兼容 |
| 新增响应字段 | 兼容 |
| 新增可选请求参数 | 兼容 |
| 修改字段语义 | 破坏性 → 需 `/api/v2` |
| 删除端点/字段 | 破坏性 → 需 `/api/v2` |

---

## 3. 端点总览

```
GET    /health                              健康检查

GET    /api/v1/sources                      列出书源
POST   /api/v1/sources                      安装书源
GET    /api/v1/sources/{id}                 书源详情
DELETE /api/v1/sources/{id}                 卸载书源
POST   /api/v1/sources/{id}/enable          启用
POST   /api/v1/sources/{id}/disable         禁用
POST   /api/v1/sources/{id}/doctor          健康检查

GET    /api/v1/search                       跨书源搜索

GET    /api/v1/books                        书架列表
GET    /api/v1/books/{id}                   书籍详情
GET    /api/v1/books/{id}/chapters          章节列表
GET    /api/v1/books/{id}/chapters/{cid}    章节正文
POST   /api/v1/books/{id}/update            增量更新

POST   /api/v1/tasks                        创建任务
GET    /api/v1/tasks                        任务列表
GET    /api/v1/tasks/{id}                   任务详情
POST   /api/v1/tasks/{id}/pause             暂停
POST   /api/v1/tasks/{id}/resume            继续
POST   /api/v1/tasks/{id}/cancel            取消
POST   /api/v1/tasks/{id}/retry             重试
GET    /api/v1/tasks/{id}/events            SSE 单任务事件流
GET    /api/v1/tasks/events                 SSE 全局事件流（新增）
POST   /api/v1/exports                      创建导出作业
GET    /api/v1/exports/{id}                 导出作业状态
```

标了"（新增）"的是相对原始规划书 §30 补的端点，原因见评估报告 P2-01。

---

## 4. 端点详解

### 4.1 健康检查

```http
GET /health
```

```json
{ "status": "ok", "version": "0.1.0.dev0" }
```

Desktop 启动时轮询此端点。

---

### 4.2 书源

#### 列出书源

```http
GET /api/v1/sources
```

```json
[
  {
    "id": "example",
    "name": "Example",
    "version": "1.0.0",
    "spec_version": 1,
    "capabilities": ["search", "book", "chapters", "content"],
    "enabled": true,
    "health": "healthy",
    "installed_version": "1.0.0",
    "previous_version": null
  }
]
```

#### 安装书源

```http
POST /api/v1/sources
```

```json
{ "mode": "yaml", "content": "spec_version: 1\nid: ..." }
```

或

```json
{ "mode": "registry", "id": "example", "version": "1.0.0" }
```

> 设计裁决：规划书 §29 列出 `POST /sources`，§13 描述 Registry 安装流程，
> 但未说明两者关系。本实现裁决为**同一端点**，通过 `mode` 区分。

---

### 4.3 搜索

```http
GET /api/v1/search?q=三体&source=example&limit=20
```

```json
{
  "keyword": "三体",
  "total": 3,
  "items": [
    {
      "source_id": "example",
      "title": "三体",
      "url": "https://example.com/book/1001",
      "author": "刘慈欣",
      "cover_url": "https://example.com/covers/1001.jpg",
      "intro": null
    }
  ],
  "errors": [
    { "source_id": "broken-source", "code": "SOURCE_EXECUTION_ERROR", "message": "..." }
  ]
}
```

> 设计裁决：规划书 §29 未说明 `GET /search` 是否跨源。
> 本实现裁决为**默认跨源并发聚合**，可用 `source` 参数限定。
> **单源失败不影响整体**——失败信息通过 `errors` 返回。

---

### 4.4 书籍

#### 章节列表

```http
GET /api/v1/books/{book_id}/chapters
```

```json
[
  { "id": "chap_0001", "title": "第一章 科学边界", "index": 0, "word_count": 3200, "has_content": true }
]
```

**不含正文**——目录可能数千章，携带正文会使响应体过大。
正文单独通过 `/chapters/{chapter_id}` 获取。

#### 增量更新

```http
POST /api/v1/books/{book_id}/update?dry_run=true
```

```json
{
  "book_id": "book_xxx",
  "dry_run": true,
  "plan": {
    "total": 1012,
    "to_download": 12,
    "skipped": 1000,
    "new": 12,
    "changed": 0,
    "missing": 0
  }
}
```

`dry_run=true` 只返回差异计划，不创建任务。

---

### 4.5 任务

#### 创建任务

```http
POST /api/v1/tasks
```

下载任务有两种给法。

书已经在库里（`mog download <book-id>` 或书架里点下载）：

```json
{
  "type": "download_book",
  "book_id": "book_xxx",
  "priority": 50
}
```

只有一个详情页 URL（从搜索结果直接点下载，桌面端走这条）：

```json
{
  "type": "download_book",
  "source_id": "example",
  "url": "https://example.com/book/1001"
}
```

第二种会先按 `(source_id, source_book_id)` 登记成书再下，
所以同一本书重复提交不会产生两条记录。任务完成后 `book_id` 会填上。

其余类型：`update_book` 与 `export_book` 要 `book_id`；
`refresh_source` 两者都不用。任务专属参数放 `params`，比如导出任务的
`format` / `target`。

建任务时就会把引用的实体查清楚，不留到 worker 执行时才失败 ——
否则调用方拿到 `201` 却无从判断这个任务能不能跑：

| 情况 | 状态码 | 错误码 |
|------|--------|--------|
| `book_id` 指向的书不存在 | 404 | `STORAGE_NOT_FOUND` |
| `source_id` 指向的书源不存在 | 404 | `SOURCE_NOT_FOUND` |
| 下载任务既没 `book_id` 也没 `source_id` + `url` | 400 | `TASK_PARAMETER_ERROR` |
| `export_book` 没给 `book_id` | 400 | `TASK_PARAMETER_ERROR` |

响应 `201`：

```json
{
  "id": "task_1a2b3c4d",
  "type": "download_book",
  "status": "pending",
  "priority": 50,
  "book_id": "book_xxx",
  "total": 0,
  "completed": 0,
  "failed": 0,
  "progress": 0.0,
  "created_at": "2026-10-04T08:00:00Z"
}
```

#### 任务控制

| 端点 | 合法前置状态 | 结果状态 |
|------|-------------|---------|
| `POST /tasks/{id}/pause` | `pending` `running` | `paused` |
| `POST /tasks/{id}/resume` | `paused` | `pending` |
| `POST /tasks/{id}/cancel` | 非终态 | `cancelled` |
| `POST /tasks/{id}/retry` | `failed` `cancelled` | **返回新任务** |

> `retry` 创建**新任务**而非复活旧任务——终态不可逆（见 domain-model §5.1）。

非法状态转移返回 `409 Conflict`，错误码 `TASK_INVALID_TRANSITION`。

---

### 4.6 SSE 事件流

#### 单任务

```http
GET /api/v1/tasks/{task_id}/events
Accept: text/event-stream
```

#### 全局（Desktop 任务页使用）

```http
GET /api/v1/tasks/events
Accept: text/event-stream
```

事件格式：

```
event: progress
id: 42
data: {"task_id":"task_1a2b3c4d","completed":520,"total":1000,"speed":3.4}

event: heartbeat
id: 43
data: {"task_id":null,"seq":43}
```

| 事件类型 | 说明 |
|---------|------|
| `progress` | 进度更新 |
| `status` | 状态变更 |
| `error` | 任务失败 |
| `done` | 任务完成（终态） |
| `heartbeat` | 心跳（默认 15 秒，防止代理断开） |

**第一版不使用 WebSocket** —— SSE 对单向进度通知已足够。

---

### 4.7 导出

```http
POST /api/v1/exports
```

```json
{ "book_id": "book_xxx", "format": "epub", "output_dir": null, "template": null }
```

响应 `201`：

```json
{
  "id": "export_xxx",
  "book_id": "book_xxx",
  "format": "epub",
  "status": "pending",
  "path": null,
  "size_bytes": 0
}
```

```http
GET /api/v1/exports/{export_id}
```

```json
{
  "id": "export_xxx",
  "status": "success",
  "path": "C:/Users/.../exports/刘慈欣 - 三体.epub",
  "size_bytes": 2048576
}
```

> 设计裁决：规划书 §26 定义同步导出接口，§29 给出异步作业语义（`POST` + `GET /{id}`）。
> 本实现裁决为**异步作业**，与 Task Engine 复用同一状态机。
> 理由：大书（数千章）的 EPUB 生成耗时可观，同步会阻塞请求。
> 底层 `Exporter` 协议保持原签名不变（由 Task Worker 调用）。
> 详见评估报告 P1-07。

---

## 5. 错误模型

所有错误响应统一为：

```json
{
  "code": "SOURCE_PARSE_FAILED",
  "message": "未能提取书籍标题",
  "details": { "source_id": "example", "url": "https://example.com/book/1001" }
}
```

### 5.1 错误码与 HTTP 状态映射

| 领域错误 | HTTP | 说明 |
|---------|------|------|
| `EntityNotFoundError` | 404 | |
| `SourceNotFoundError` | 404 | |
| `TaskNotFoundError` | 404 | |
| `SourceSchemaError` | 422 | 书源校验失败 |
| `SourceUnsupportedError` | 422 | 不支持的规范版本 / 能力 |
| `ContentValidationError` | 422 | 内容未通过校验 |
| `ExportError` | 422 | 导出失败（含路径非法） |
| `HttpStatusError` | 502 | 上游站点返回错误 |
| `NetworkError` | 502 | 网络层失败 |
| `TaskParameterError` | 400 | 建任务的参数不成立（缺必填项） |
| `TaskError` | 409 | 状态转移冲突 |
| `StorageError` | 500 | 持久化失败 |
| 其他 | 500 | |

匹配按从上到下的顺序取第一个命中的类型，所以子类要排在父类前面
（`TaskParameterError` 在 `TaskError` 之前）。

`details` 字段始终存在（可能为空对象），便于客户端稳定解析。

---

## 6. OpenAPI

FastAPI 自动生成：

| 路径 | 内容 |
|------|------|
| `/openapi.json` | OpenAPI 3.x schema |
| `/docs` | Swagger UI |
| `/redoc` | ReDoc |

补充文档位于 `docs/api/`（本文件）。

---

## 7. 启动模式

```bash
mog server start          # 由 CLI 拉起（后台，默认）
mog server status
mog server stop

mograb-api                # console script（前台）
python -m mograb_api      # 等价
```

### 7.1 Desktop 启动流程

```
Electron 启动
    ↓
spawn mograb-api.exe (Sidecar)
    ↓
轮询 GET /health 直至就绪（超时 5s）
    ↓
加载 UI
```

配置项：`server.host`（默认 `127.0.0.1`）、`server.port`（默认 `48721`）、
`server.health_timeout_ms`（默认 `5000`）。

---

## 8. 客户端约定

### 8.1 CLI

```bash
mog search "三体" --json          # 机器可读
mog search "三体"                 # 人类可读
```

退出码：

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数错误 |
| 3 | 未找到 |
| 4 | 校验失败 |
| 5 | 网络错误 |
| 130 | 用户中断 |

### 8.2 Desktop

- 仅通过 preload 暴露的 `window.mograb` 访问 API
- CSP 限制 `connect-src` 为本地 API
- 任务进度通过 SSE 订阅（`/tasks/events`），不用轮询
