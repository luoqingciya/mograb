# 变更日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [PEP 440](https://peps.python.org/pep-0440/)。

版本号只有一个来源：仓库根的 `VERSION` 文件。改它，三个包一起变。

## [未发布]

写第一个真实站点书源（`bqgnovels.com`）时暴露出来的问题。**四个引擎缺口
加一个真 bug**，都已修复。

### 新增

**`result.paginate` —— 列表分页。** 站点把长目录切成多页是常态
（100 章一页的书站很常见），而原先的 `chapters` 只发一次请求：
1453 章的书只能取到前 100 章，**而且不报错**。静默截断比报错更糟 ——
用户会以为下载完了。

```yaml
result:
  list: ".list_item"
  fields: {title: ".t", url: "a@href"}
  paginate:
    next: ".seo_page a@href"   # 指向「下一页」的提取规则
    max_pages: 30              # 上限，默认 20
```

只支持「跟着下一页链接走」这一种方式：站点的分页 URL 形态各异
（`?page=2` / `/list_2.html` / 带 token 的路径），靠猜规律很容易在某次改版后
静默失效。让页面自己说下一页在哪，是最稳的做法。

终止条件是 `next` 取不到值、下一页地址已经抓过（防死循环）、或到达
`max_pages`。**到达上限会记 WARNING** —— 不能静默截断。
`reverse` 改为在所有页面抓完之后才应用。见规范 §5.4。

### 新增

**`mog find` —— 在已下载的章节正文里搜关键词。** 和 `mog search` 是两件事：

- `mog search <关键词>` —— 去**书源**上搜书，找的是「哪本书」
- `mog find <关键词>` —— 在**本地已下载的正文**里搜，找的是「哪一章」

完全不访问网络，也不受任何站点 robots.txt 约束。`--book` 可限定某一本，
`--json` 便于脚本调用。只返回命中处的**片段**而不是整章正文 ——
一本几千章的书，搜一次就把几十兆正文读进内存是不可接受的。

用 `LIKE` 做字面子串匹配，关键词里的 `%` 和 `_` 会转义
（否则搜「100%」会退化成「100 开头且后面任意」）。已知限制：`LIKE '%kw%'`
用不上索引，是全表扫描 —— 个人书库规模够用，库再大就该上 FTS5 虚拟表，
那需要动 schema，属于另一件事。

**JSON 响应支持列表提取。** `extract_many` 原先写死了 `tree.cssselect`，
JSONPath 传进去直接抛 `SelectorSyntaxError`。于是 `format: json` 只有单值能用
（`extract_one` 走 JSONPath 提取器是好的），**列表型能力（`search` / `chapters`）
完全做不了** —— 任何 JSON API 书源都卡在这。测试也没覆盖到，
`test_jsonpath` 只测了扁平单值。

现在按**规则类型**分流（不是按 `document.kind`，书源可能对 HTML 响应声明
JSONPath）。`list` 的 JSONPath 匹配到数组时按元素展开，所以 `$.data.list`
和 `$.data.list[*]` 等价。

### 修复

**`--format` 指定的格式不影响导出文件的扩展名。** `resolve_export_target`
拿的是**配置里的默认格式**（`epub`）来拼扩展名，而不是本次实际用的格式。
于是 `mog download -f txt` 会产出一个内容是纯文本、名字却叫 `.epub` 的文件 ——
内容没错，名字骗人，而且不报错。

只有「指定了格式但没指定路径」这个组合会触发，所以之前的测试全都没覆盖到：
指定路径的那条测试传的是 `.txt` 路径，不指定路径的那条用的是默认格式。
现在扩展名跟着**实际导出器**走，并补了三种格式的参数化测试
（连内容一起验：epub 必须是 ZIP）。

**书源的状态和自定义字段到不了领域模型。** 两条链路都是断的：

- `BookStatus` 枚举的文档写着「由书源尽力解析，未知时为 UNKNOWN」，
  但 **`BookDraft` 里根本没有 `status` 字段** —— 全仓库它只出现在枚举定义、
  `Book` 的默认值、从数据库读回时的转换三处，没有任何地方把它设成
  ONGOING 或 COMPLETED
- **`draft.extra` 全仓库无人消费** —— 引擎把规范外的字段收集好，
  然后直接丢掉。`Book.metadata` 也永远只从数据库读回，从没被写入过

所以书源里写 `status` 或 `category` 都是白写。现在 `book.fields.status` 会经
`BookStatus.parse` 映射成枚举，规范外的字段合并进 `Book.metadata`
（刷新已有书时保留用户写入的其他键）。见规范 §5.5。

`BookStatus.parse` 接受规范值（`ongoing` / `completed` / `unknown`）和常见
同义写法（`连载中` / `已完结` / `完本` / `finished` …），**认不出来一律降级为
`unknown`** —— 状态是锦上添花的元数据，不该因为它让整本书登记失败。
**刻意不接受 `"0"` / `"1"`**：这两个值的含义每个站点都不一样，引擎没有依据
去猜；书源该用锚定整值的 `regex_replace` 自己转成规范值，
这样转换规则跟着书源一起被审阅和版本化。

这是第三个「声明了没接线」（前两个 `network.headers` / `network.retry`）。

**`network.headers` 与 `network.retry` 是死配置。** `NetworkPolicy` 声明了
五个字段，引擎只接了三个，这两个从来没被读过。规范 §8.1 把它们写进了示例，
**官方参考书源也声明了 `network.headers.User-Agent`** —— 那条配置一直没生效。
危害在于「静默」：书源作者写了自定义 UA 或 Referer，以为生效了，实际没有。

现在 `headers` 作为来源级默认值参与合并（`request.headers` 优先，
越具体的声明优先级越高），`retry` 只覆盖次数、不改退避曲线
（退避算法是全局配置，书源不该管）。

**`remove_html` 把 `<br>` 分段的正文压成一整行。** 中文小说站的正文普遍是
`第一段<br><br>第二段`，而 `remove_html` 只是 `unescape(去标签)`，
`<br>` 跟着一起没了。每个书源都得自己用 `regex_replace` 补一遍。

现在它会**先把 `<br>` 和块级闭合标签换成 `\n` 再删标签**。
行内标签（`<b>`/`<span>`）仍然直接删除、不断行。
顺带在规范 §13.1 记了一笔：这算改了既有语义，本该提升 `spec_version`，
但旧行为是错的、影响面可控、提升版本会让所有现存书源立刻失效 —— 所以例外一次。

**文本清洗不处理 U+00A0。** `cleaner.py` 处理了 `&nbsp;` 实体，但不处理
反转义之后的字符；`_ZERO_WIDTH_RE` 也不含它（它是可见字符，不是零宽）。
而逐行只做 `rstrip()`，所以行首缩进会一路进到导出文件。

现在 U+00A0 与 U+3000 归一化成普通空格（不是直接删 —— 万一在词中间会把词粘住），
并且逐行去掉首尾空白。后者是有意的：网页正文的行首空白几乎总是伪缩进，
段落缩进该由导出层统一决定，而不是沿用各站点各自的土办法。

**分页里 `params={}` 会清空 URL 自带的查询串。** 实现分页时写的是
`replace(current, url=next_url, params={})`，意思是「不要再叠加首页的 query」。
结果在真实站点上第 2 页返回的仍是第 1 页 —— httpx 遇到空 dict 会先
`copy_with(query=None)` 再赋空参数，`?sort=0&page=2` 被整个抹掉。

**这个 bug 离线快照测不出来**：假 fetcher 根本不看 `params`。
只有真跑一遍才会暴露。修法是传 `params=None`，测试里断言「必须是 None
而不是空 dict」。

### 书源

新增第一个真实站点书源（`sources/bqgnovels/`，本地目录不进仓库）。
验证结果：完整目录 **1453 章**（15 页）、正文 2561 字符 / 69 段 /
无残留标签 / 无伪缩进。站点挂了 Cloudflare 但未拦截。

端到端实跑过一本 7 章的书：下载 7/7 章、0 失败、76,725 字，
TXT / Markdown / EPUB 三种导出都正常；`mog find 荔枝` 搜到 7 处。

该站点新增了 `search` 能力（走 `/api/query/search`）。**注意：该端点被站点
robots.txt 的 `Disallow: /api*` 与 `Disallow: /search*` 两条同时命中**，
使用它等于绕过站方表态，已由使用者决定并承担。不绕的替代方案
（爬全部分类页建本地索引）是 1000+ 次请求，反而重得多。

搜索实测可用（`mog search 剑来` 返回 3 条真实结果）。响应信封最初是按
首页 SSR 载荷推断的，实测确认与书籍列表接口同构。

626 个测试，覆盖率 85%。

## [1.0.0rc0] - 2026-10-04

**首个预发布版本。** 规范冻结、核心链路跑通、API 与 CLI 接线完成、
桌面端最小闭环可用。

这是一个 **release candidate**：接口层面已经稳定，但还没在真实站点上验证过
完整下载，所以不标正式版。

装上之后能干的事：装书源 → 跨源搜书 → 下载整本 → 增量更新 →
导出 TXT / Markdown / EPUB。命令行、本地 API、桌面端三条路都能走。

### 规范

四份核心规范冻结，作为后续实现的契约：

- **Source Specification v1** —— 声明式书源 DSL。拆分了原本混用的
  `version` 字段（规范版本和书源版本现在是两个字段）；统一提取语法
  （CSS / XPath / JSONPath / Regex / `@attr`）；十个变换算子；
  权限模型里 `script` / `filesystem` / `cookies` 一律禁止。
- **Domain Model v1** —— 领域模型。给 `Book` 补了 `language`、`word_count`、
  `chapter_count`、`cover_path`（EPUB 和书架页要用，原规划书漏了）；
  把任务状态机的转移规则写死成表；错误层次里每个错误带上 `retryable` 标记。
- **Storage v1** —— 8 张表的结构、索引、唯一约束，以及事务边界。
- **API v1** —— 22 个端点，错误模型，SSE 事件格式。

### 核心库

`mograb` 包，按模块划分：

- `domain` —— `Book` / `Chapter` / `SourceSpec` / `Task`。章节身份用候选键
  （`sid:` / `url:` / `idx:`）而不是单键，避免书源某次更新不再返回章节 ID 时
  整本书被当成新的。URL 规范化去掉追踪参数、排序 query。内容哈希用 BLAKE2b-128。
- `source` —— 加载、校验、执行。`loader` 报错会带字段路径；`validator` 是
  linter，检查选择器能不能编译、模板变量有没有声明、请求域名在不在白名单里；
  `extractor` 支持四种提取方式和逐项下钻；`transformer` 十个算子；
  `engine` 是纯函数式的，可以完全离线测试。
- `network` —— httpx 封装，串起缓存、限流、重试。编码探测按
  响应头 → meta → utf-8 的顺序，`gb2312`/`gbk` 一律提升成 `gb18030`。
  缓存失效分三层：TTL、显式清除、LRU 淘汰。限流按书源隔离。
- `task` —— 队列、Worker 池、生命周期管理。`TaskManager.start()` 会先把
  上次进程崩溃留下的 RUNNING / RETRYING 任务标成 FAILED，而不是让它们
  在界面上永远转圈。增量更新用 `compute_chapter_diff` 这个纯函数算。

  下载编排（`DownloadScheduler`）按固定顺序走：
  抓目录 → 和本地比 → 并发下载 → 清洗校验 → 单事务落库 → 刷新统计 → 可选导出。
  单章失败只记进报告，不中断整本书；并发度受书源自己的 `network.concurrency`
  约束，防止一本三千章的书一次性铺开。进度通过回调抛出去，给后面的 SSE 用。
- `storage` —— SQLAlchemy 2.0 映射 8 张表，7 个仓储实现，SQLite 开了 WAL。
  书源仓储把定义放磁盘、把本机记账放数据库，索引能从磁盘重建；
  HTTP 缓存实现三层失效（TTL / 显式 / 容量），容量满了按最久未访问淘汰。
  批量写入走单事务，避免「下载成功但库里只有一半」。
- `content` —— 清洗分 DOM 级和文本级，内置了常见水印行过滤。
  校验阈值收在 `ContentPolicy` 里，不硬编码。
- `export` —— TXT / Markdown / EPUB。EPUB 是自研的（`ebooklib` 是 AGPL，
  会给这个 GPL-3.0-only 的项目带来额外分发义务）。文件名模板和路径安全
  分开处理：书名用宽容清洗，用户输入用严格拒绝。
- `config` —— 路径解析和配置。数据目录跟随运行目录，支持 `MOGRAB_HOME` 覆盖。
- `logging` —— structlog，`Cookie` / `Authorization` 这类字段自动脱敏。
- `errors` —— 20 个错误类型，每个带稳定的 `code` 和 `retryable`。

### 应用

- `apps/cli` —— `mog` 命令，11 个命令组，退出码定成 7 个。全部接线完成：
  书源管理（list / show / lint / install / remove / enable / disable / rescan /
  doctor / init）、跨源搜索、书籍信息、下载、增量更新、导出、任务查询、
  缓存管理、配置、日志、server 控制。

  下载是就地跑完再退出 —— 命令行进程起 worker 池再等调度没意义；
  后台执行交给 API server。任务记录照样写库，`mog task list` 能看到历史。

  `mog task pause/resume/cancel/retry` 走 API：任务状态在 server 进程的内存里，
  改数据库它不知道。连不上就给一句人话，不抛 httpx 堆栈。

- `apps/api` —— FastAPI，22 个端点挂在 `/api/v1` 下，全部接线完成。
  统一错误模型；SSE 事件流（除规划书要求的单任务流外，另加了全局流，
  桌面端任务页要用）；CORS 收紧到只允许本机来源。任务走 worker 池 + 队列，
  支持暂停/继续/取消。**所有业务端点要求 Bearer 令牌**，见下面的「修复」。

- `apps/desktop` —— Electron + TypeScript。最小闭环已跑通：
  搜索 → 点下载 → 看任务进度（SSE 实时推）。书架 / 书源管理 / 设置还是占位页。

  构建用 tsc 不引打包器 —— 渲染层走原生 ES modules，编译完 Electron 直接加载。
  主进程 CommonJS、渲染层 ESM，所以有两份 tsconfig。开了 `contextIsolation`、
  `sandbox`，关了 `nodeIntegration`，CSP 只放行本地 API。

  后端以 sidecar 方式拉起；令牌由主进程读好后经 preload 递给渲染进程。
  SSE 用 fetch 读流而不是 `EventSource`（后者设不了请求头）。

### 装配

新增 `mograb.app` 作为 composition root。CLI 和 API 要的是同一套东西
（数据库、仓储、HTTP 客户端、引擎、管线、调度器、任务管理器），
这套装配只该有一份 —— 两边各接一遍迟早会走样。`create_application()` 是唯一入口。

顺带把「执行任务 + 维护状态机」从 WorkerPool 里抽成 `TaskRunner`：
CLI 就地跑和后台 worker 走同一份，不会出现「两边对失败的处理不一样」。

### 书源

参考书源放在 `tests/fixtures/example-source/`，带三个 HTML 快照，
兼做 fixture 测试的数据。用 `example.com`（IANA 保留域名），不指向真实站点。

**书源本身不进仓库。** `sources/` 已加进 `.gitignore`，留给本地开发。
理由见 [架构总览](docs/architecture/overview.md#书源为什么不进仓库)。

### 工程

- uv workspace monorepo。版本号统一到根 `VERSION` 文件。
- 数据目录改成便携模式：全部在运行目录的 `data/` 下，不写系统目录。
- Ruff + Pyright + pre-commit 配置。
- GitHub Actions：CI（lint / 文档内链 / 类型检查 / 测试矩阵 / 书源校验 / 构建），
  Release（PyInstaller onedir + Electron + SHA256SUMS）。
- `scripts/version.py`、`scripts/build.py`、`scripts/release.py`、
  `scripts/check_docs.py`。
- 606 个测试，覆盖率 85%，门槛设在 70%。桌面端另有 14 个（`npm test`）。

### 修复

**API 补上鉴权。** 之前只有 CORS。回环地址不构成信任边界 —— 浏览器里的
任意页面都能向 `127.0.0.1:48721` 发请求，而且简单请求（表单编码、
`text/plain`）连预检都不触发，CORS 只约束能不能**读响应**。也就是说，
用户随手打开一个恶意网页，那个页面就能让 MoGrab 下载、删书源、建任务。

现在所有业务端点都要求 `Authorization: Bearer <token>`：

- 令牌首次使用时生成在 `data/token`（POSIX 0600），之后复用。
  **不放 `config.toml`** —— 那个文件会被备份、被贴进 issue、在机器之间拷贝
- 生成用 `secrets.token_urlsafe(32)`，比较用 `secrets.compare_digest`
- 只认 `Authorization` 头，不做 `?token=` 查询参数 —— 后者会让令牌进访问日志
- `/health`、`/docs`、`/openapi.json` 保持开放
- 新增 `mog server token` 打印令牌（手工 curl 用）
- 新增 `AuthError`（`AUTH_REQUIRED`）→ 401，带 `WWW-Authenticate`

代价是桌面端的 SSE 从 `EventSource` 换成了 fetch 流式读取 ——
`EventSource` 设不了请求头。见 [ADR-0004](docs/architecture/decisions/ADR-0004-local-api-auth.md)。

**建任务时校验引用的实体。** `tasks.book_id` 上有外键，但 `POST /api/v1/tasks`
传一个不存在的 `book_id` 时，插入抛的是裸的 `IntegrityError` —— 到客户端
就是 500，而 `/api/v1/exports` 同样的输入给的是 404。现在校验收到
`Application.create_task()` 里，CLI 和 API 共用一份判据：

| 情况 | 之前 | 现在 |
|------|------|------|
| 书不存在 | 500 | 404 `STORAGE_NOT_FOUND` |
| 书源不存在 | 500 | 404 `SOURCE_NOT_FOUND` |
| 下载任务没说下哪本 | 500 | 400 `TASK_PARAMETER_ERROR` |

新增 `TaskParameterError`，和 `InvalidTaskTransitionError` 分开 ——
后者是「和资源当前状态冲突」（409），前者是「请求本身没说清楚」（400）。

**桌面端视图的创建时机。** 视图一被创建就会发请求，而原先 `bootstrap()`
是先建视图、再等后端地址。搜索结果页创建时不发请求，所以一直没暴露；
任务页创建时立刻订阅 SSE，于是把相对路径解析成了 `file:///D:/tasks/events`，
被 CSP 拦下。现在改成「拿到后端地址之后才建视图」，启动期间显示占位内容。


### 相对原规划书的改动

规划书里有几处自相矛盾或者没做选择的地方，这一版做了裁决：

| 项 | 规划书 | 这里怎么定的 |
|----|--------|-------------|
| 仓库结构 | 原始规划书 §4 / §5 / §59 三处不一致 | 单核心包 + 双应用 |
| 书源版本字段 | `version` 一处指规范、一处指书源 | 拆成 `spec_version` + `version` |
| 数据目录 | 原始规划书 §23 说 `~/.mograb`，§57.4 说 `%APPDATA%` | 都不采用，跟随运行目录 |
| 解析器 | 写的是 `selectolax / lxml`，没选 | `lxml`，因为它支持 XPath |
| EPUB 库 | 没列 | 自研，避开 AGPL 依赖 |
| 任务状态机 | 只列了状态，没写转移规则 | 写成表 |
| 缓存失效 | 说"必须提供"，没说什么策略 | TTL + 显式 + LRU |
| 并发模型 | 三处数值和语义都不一样 | 全局和单源两级，取小的那个 |
| 导出接口 | 原始规划书 §26 同步、§29 异步，矛盾 | 异步作业 |
| 数据库迁移 | 没提 | 引入 Alembic |

理由都写在 [规划评估报告](docs/evaluation/规划评估报告.md) 里。

### 还没做

完整清单和优先级在 [docs/progress.md](docs/progress.md)。最要紧的两条：

- **所有测试都是离线的**，没在真实站点上跑过完整下载。接口之间对得上，
  但真实站点的编码、反爬、目录结构差异都还没遇到过
- 桌面端还剩书架、书源管理、设置三个页面；架构已验证，照着补即可

## 版本规划

按规划书的节奏走（这里是**目标**，各版本实际做到哪一步见
[docs/progress.md](docs/progress.md)）：

| 版本 | 目标 | 状态 |
|------|------|------|
| v0.1.0 | 能完整下载一本小说 | 已达成 |
| v0.2.0 | 能稳定下载大量章节 | 已达成（未在真实站点验证） |
| v0.3.0 | 第三方能写书源并维护 | 部分（缺 Source Registry） |
| v0.4.0 | API 成为正式接口 | 已达成 |
| v0.5.0 | CLI 在 Windows / Linux 上独立可用 | 已达成 |
| v0.6.0 | Windows 桌面端 Beta | 进行中 |
| v0.7.0 | 输出质量和性能 | 部分（缺封面与元数据模板） |
| v1.0.0 | 规范、API、CLI 命令全部稳定 | 本版是它的 rc |

[1.0.0rc0]: https://github.com/luoqingciya/mograb/releases/tag/v1.0.0rc0
