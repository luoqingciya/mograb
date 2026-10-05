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
- **所有业务端点要求 `Authorization: Bearer <token>`**（见 §2.2）
- CORS 仅允许 `http://127.0.0.1:*` / `http://localhost:*` / `file://` / `null`

> **回环地址不是信任边界。** 浏览器里的任意页面都能向 `127.0.0.1:48721`
> 发请求，而且简单请求（表单编码、`text/plain`）连预检都不触发 ——
> CORS 只约束能不能**读响应**，不阻止请求送达。所以光靠 CORS 的话，
> 用户随手打开一个恶意网页，那个页面就能让 MoGrab 下载、删书源、建任务。
>
> 令牌是主要防线，CORS 是第二道。详见 [ADR-0004](../architecture/decisions/ADR-0004-local-api-auth.md)。

---

## 2. 通用约定

| 项 | 约定 |
|----|------|
| 前缀 | `/api/v1` |
| 内容类型 | `application/json`（SSE 除外） |
| 鉴权 | `Authorization: Bearer <token>` |
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

### 2.2 认证

每个业务请求都要带令牌：

```http
GET /api/v1/sources HTTP/1.1
Authorization: Bearer <token>
```

**只认这一种传法。** 不接受查询参数（`?token=`）—— 令牌会因此出现在
服务端访问日志里，而日志是最容易被翻出来和贴出去的东西。

**令牌从哪来。** 首次启动时自动生成在数据目录下的 `token` 文件
（POSIX 权限 0600），之后一直复用。CLI 和 Desktop 各自读它，不需要握手。
手工调接口时用 `mog server token` 打印。

```bash
TOKEN=$(mog server token)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:48721/api/v1/sources
```

**不要求令牌的端点：**

| 端点 | 为什么开放 |
|------|-----------|
| `/health` | 用来探「有没有实例在跑」。Desktop 启动时轮询它，`mog server status` 也用它。只暴露「在跑」和版本号 |
| `/docs`、`/redoc` | 浏览器里打开没法带请求头。接口本身是公开文档 |
| `/openapi.json` | 同上 |

**令牌不对时**返回 `401`，响应体走统一错误模型：

```json
{
  "code": "AUTH_REQUIRED",
  "message": "缺少或无效的 API 令牌",
  "details": { "scheme": "Bearer", "hint": "用 `mog server token` 查看令牌" }
}
```

响应头带 `WWW-Authenticate: Bearer realm="MoGrab"`。

**「没带令牌」和「令牌不对」返回同样的信息** —— 区分开等于告诉对方猜的方向是对的。

**SSE 也要令牌。** 注意浏览器内置的 `EventSource` 不能设置请求头，
所以订阅事件流要用 `fetch` 自己读流。Desktop 就是这么做的
（`apps/desktop/src/renderer/sse.ts`）。

**关掉认证。** `[server] auth = false` 可以关，但只在临时调试时说得通。
监听回环不构成关闭它的理由。

---

## 3. 端点总览

**除 `/health` 外，下面所有端点都要求 `Authorization: Bearer <token>`**（见 §2.2）。

共 **24 条路径 / 28 个端点**（含 2 条 SSE）。核对办法：起一次 server，
数 `GET /openapi.json` 里的 `paths` 与「路径 × 方法」组合。

```
GET    /health                              健康检查（无需令牌）

GET    /api/v1/sources                      列出书源
POST   /api/v1/sources                      安装书源
GET    /api/v1/sources/{id}                 书源详情
DELETE /api/v1/sources/{id}                 卸载书源
POST   /api/v1/sources/{id}/enable          启用
POST   /api/v1/sources/{id}/disable         禁用
POST   /api/v1/sources/{id}/doctor          健康检查
POST   /api/v1/sources/rescan               重扫书源目录

GET    /api/v1/search                       跨书源搜索（去站点上搜书）
GET    /api/v1/search/local                 在已下载的正文里搜（纯本地）

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
GET    /api/v1/tasks/events                 SSE 全局事件流
GET    /api/v1/exports                      导出作业列表
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
{ "status": "ok", "version": "1.0.0rc7" }
```

Desktop 启动时轮询此端点。**不需要令牌** —— 它只回答「有没有实例在跑」和版本号。
`version` 是引擎自己的版本（读自包元数据），不是书源版本。

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
    "homepage": "https://example.com",
    "repository": null,
    "description": "官方参考书源",
    "capabilities": ["search", "book", "chapters", "content"],
    "enabled": true,
    "health": "healthy",
    "installed_version": "1.0.0",
    "previous_version": null
  }
]
```

`repository` 是**书源自身的发布地址**，不是被采集的站点（那是 `homepage`）。
MoGrab 不做远端版本检查，这个字段只是给用户一个更新入口。见规范 §2.3。

`previous_version` 是**纯诊断字段**：回滚没有实现，旧版本定义文件也不保留，
不要拿它做「可回退」的承诺。

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

#### 本地正文搜索

```http
GET /api/v1/search/local?q=荔枝&book_id=book_xxx&limit=50
```

```json
{
  "keyword": "荔枝",
  "total": 7,
  "items": [
    {
      "book_id": "book_01M43QSWXEJ7HWYARYGSBA4MNB",
      "book_title": "长安的荔枝",
      "chapter_id": "chap_01M43QSY0K0Z1F1QRC7H27X3E9",
      "chapter_title": "第一章",
      "chapter_index": 0,
      "snippet": "…时刘署令从苇席下取出一轴文牒：“也不是甚么大事，内廷要采办些荔枝煎，此事非让老李你来勾当不可。”…"
    }
  ]
}
```

**和 `GET /search` 是两件事，所以分成两个端点而不是加个开关**：

| | `GET /search` | `GET /search/local` |
|---|---|---|
| 搜什么 | **书源**（站点上有什么书） | **本地库**（我下载过的正文） |
| 答案 | 「哪本书」 | 「哪一章」 |
| 网络 | 要发请求 | **一行都不发** |

`q` 按**字面子串**匹配，不解析正则；关键词里的 `%` 和 `_` 会被转义。

`snippet` 是命中位置附近的**片段**，不是整章正文 —— 一本几千章的书，
搜一次就把几十兆正文读进内存是不可接受的。

> 已知限制：底层是 `LIKE '%kw%'` 全表扫描，用不上索引。个人书库规模够用；
> 库再大该上 FTS5 虚拟表，那要改 schema。

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
event: task
id: task_1a2b3c4d
data: {"event":"task","task_id":"task_1a2b3c4d","type":"download_book","status":"running",
       "book_id":"book_01M459...","total":2036,"completed":339,"failed":0,
       "error_code":null,"error_message":null}

event: heartbeat
data: {"task_id":null}
```

| 字段 | 说明 |
|------|------|
| `event` | 固定 `task`。心跳帧是 `heartbeat`，**没有 `status` 字段** |
| `status` | `pending` / `running` / `paused` / `retrying` / `success` / `failed` / `cancelled` |
| `total` / `completed` / `failed` | 进度。`total` 为 0 表示还没算出总数 |
| `error_code` / `error_message` | 只在失败时有值 |

**两类帧都会发**，订阅方按「有没有 `status`」区分 —— 心跳只是保活，
没有业务含义。

**什么时候发**：

- 任务**状态跃迁**时（→ running、→ 终态）
- **进度变化时**，但**限流到 1 秒一条**（`PROGRESS_NOTIFY_INTERVAL_SECONDS`）。
  逐章推会把流灌满 —— 一本三千章的书就是三千条事件。
  最后一次不受限流约束，免得订阅方看到进度停在 99%。

> 进度事件是后补的。原先只有状态跃迁才推，于是整个下载过程只在首尾各推
> 一条，中间什么都没有 —— 而 Desktop 的任务页没有轮询、全靠这个流，
> 进度条会从 0 直接跳到完成。见 CHANGELOG。

**第一版不使用 WebSocket** —— SSE 对单向进度通知已足够。

**订阅方式**：令牌只能走 `Authorization` 头，所以**不能用 `EventSource`**
（它设不了请求头），要 `fetch` 读流。Desktop 在
`apps/desktop/src/renderer/sse.ts`，CLI 在 `mog task watch`
（`mograb_cli/commands/_api.py` 的 `stream_task_events`）。

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
| `AuthError` | 401 | 缺少或无效的 API 令牌 |
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
mog server token          # 打印访问令牌
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
轮询 GET /health 直至就绪（超时 20s，此端点无需令牌）
    ↓
读 <数据目录>/token 拿到访问令牌
    ↓
经 preload 把 {baseUrl, token} 递给渲染进程
    ↓
渲染进程 configure() 之后才创建视图
```

读令牌放在健康检查**之后**：后端在 `run()` 里先落盘令牌再开监听，
所以端口一旦能应答，令牌文件必然已经在了。

配置项：`server.host`（默认 `127.0.0.1`）、`server.port`（默认 `48721`）、
`server.auth`（默认 `true`）、`server.health_timeout_ms`（默认 `5000`）。

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

- 令牌由主进程从 `<数据目录>/token` 读出来，经 preload 递到渲染进程 ——
  渲染进程开了 sandbox，拿不到文件系统
- 渲染进程直接 `fetch` 本地 API，不逐请求绕 IPC
- 每个请求都带 `Authorization: Bearer <token>`
- CSP 限制 `connect-src` 为本地 API
- 任务进度通过 SSE 订阅（`/tasks/events`），不用轮询。
  **用 `fetch` 读流而不是 `EventSource`** —— 后者设不了请求头，
  而令牌不能走查询参数（会进访问日志）
- **视图只在拿到后端地址之后创建。** 视图一建出来就会发请求，
  配置之前建的会把相对路径解析成 `file:///...`，然后被 CSP 拦下，
  报错完全指不到真正的原因
