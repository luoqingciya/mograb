# 变更日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [PEP 440](https://peps.python.org/pep-0440/)。

版本号只有一个来源：仓库根的 `VERSION` 文件。改它，三个包一起变。

## [0.1.0.dev0] - 未发布

项目初始化。把规划书里互相矛盾的地方定下来，冻结了四份规范，搭出可运行、
可测试的骨架。

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
- `storage` —— SQLAlchemy 2.0 映射 8 张表，6 个仓储协议，SQLite 实现开了 WAL。
  批量写入走单事务，避免"下载成功但库里只有一半"。
- `content` —— 清洗分 DOM 级和文本级，内置了常见水印行过滤。
  校验阈值收在 `ContentPolicy` 里，不硬编码。
- `export` —— TXT / Markdown / EPUB。EPUB 是自研的（`ebooklib` 是 AGPL，
  会给这个 GPL-3.0-only 的项目带来额外分发义务）。文件名模板和路径安全
  分开处理：书名用宽容清洗，用户输入用严格拒绝。
- `config` —— 路径解析和配置。数据目录跟随运行目录，支持 `MOGRAB_HOME` 覆盖。
- `logging` —— structlog，`Cookie` / `Authorization` 这类字段自动脱敏。
- `errors` —— 20 个错误类型，每个带稳定的 `code` 和 `retryable`。

### 应用

- `apps/cli` —— `mog` 命令，11 个命令组。退出码定成 7 个。
  `mog source lint` 和 `mog config` 已经能用了。
- `apps/api` —— FastAPI，22 个端点挂在 `/api/v1` 下。统一错误模型，
  SSE 事件流（除了规划书要求的单任务流，另外加了全局流，桌面端任务页要用）。
  CORS 收紧到只允许本机来源。
- `apps/desktop` —— Electron 骨架。开了 `contextIsolation` 和 `sandbox`，
  关了 `nodeIntegration`，CSP 只放行本地 API。

### 书源

参考书源放在 `tests/fixtures/example-source/`，带三个 HTML 快照，
兼做 fixture 测试的数据。用 `example.com`（IANA 保留域名），不指向真实站点。

**书源本身不进仓库。** `sources/` 已加进 `.gitignore`，留给本地开发。
理由见 [架构总览](docs/architecture/overview.md#书源为什么不进仓库)。

### 工程

- uv workspace monorepo。版本号统一到根 `VERSION` 文件。
- 数据目录改成便携模式：全部在运行目录的 `data/` 下，不写系统目录。
- Ruff + Pyright + pre-commit 配置。
- GitHub Actions：CI（lint / 类型检查 / 测试矩阵 / 书源校验 / 构建），
  Release（PyInstaller onedir + Electron + SHA256SUMS）。
- `scripts/version.py`、`scripts/build.py`、`scripts/release.py`。
- 282 个测试，覆盖率 85%，门槛设在 70%。

### 相对原规划书的改动

规划书里有几处自相矛盾或者没做选择的地方，这一版做了裁决：

| 项 | 规划书 | 这里怎么定的 |
|----|--------|-------------|
| 仓库结构 | §4 / §5 / §59 三处不一致 | 单核心包 + 双应用 |
| 书源版本字段 | `version` 一处指规范、一处指书源 | 拆成 `spec_version` + `version` |
| 数据目录 | §23 说 `~/.mograb`，§57.4 说 `%APPDATA%` | 都不采用，跟随运行目录 |
| 解析器 | 写的是 `selectolax / lxml`，没选 | `lxml`，因为它支持 XPath |
| EPUB 库 | 没列 | 自研，避开 AGPL 依赖 |
| 任务状态机 | 只列了状态，没写转移规则 | 写成表 |
| 缓存失效 | 说"必须提供"，没说什么策略 | TTL + 显式 + LRU |
| 并发模型 | 三处数值和语义都不一样 | 全局和单源两级，取小的那个 |
| 导出接口 | §26 同步、§29 异步，矛盾 | 异步作业 |
| 数据库迁移 | 没提 | 引入 Alembic |

理由都写在 [规划评估报告](docs/evaluation/规划评估报告.md) 里。

### 还没做

- `SourceRepository` / `ExportRepository` 没实现
- `DownloadScheduler.run()` 和 `plan_update()` 没接线
- CLI 除了 `source lint`、`config`，API 除了 `/health`，其余都是骨架
- API 没有认证，只有 CORS
- `.mgs` 打包格式没做
- E2E 测试没建
- 桌面端只有占位界面

## 版本规划

按规划书的节奏走：

| 版本 | 目标 |
|------|------|
| v0.1.0 | 能完整下载一本小说 |
| v0.2.0 | 能稳定下载大量章节 |
| v0.3.0 | 第三方能写书源并维护 |
| v0.4.0 | API 成为正式接口 |
| v0.5.0 | CLI 在 Windows / Linux 上独立可用 |
| v0.6.0 | Windows 桌面端 Beta |
| v0.7.0 | 输出质量和性能 |
| v1.0.0 | 规范、API、CLI 命令全部稳定 |

[0.1.0.dev0]: https://github.com/luoqingciya/mograb/releases
