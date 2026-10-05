# MoGrab

开源的小说抓取与电子书整理工具。Python 写的，后端 + 命令行 + Windows 桌面端。

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0--only-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

## 这个项目想解决什么

现有的小说下载工具大多围绕 Legado 书源格式做兼容，结果是书源规则越写越复杂，
一个站点改版就要靠一堆正则和脚本去救。MoGrab 换个思路：不兼容 Legado，
自己定一套书源规范，规则只描述"请求什么、从哪取、怎么提取、怎么转换"，
重试、并发、缓存、调度全部交给程序。

书源是一份 YAML 配置，不是 Python 插件，不允许执行任意代码。表达力换来的是
可静态检查、可安全分发、可以离线测试。

```yaml
spec_version: 1
id: example
version: 1.0.0
capabilities: [search, book, chapters, content]

search:
  request: { method: GET, url: "https://example.com/search", query: { q: "{{keyword}}" } }
  result:
    list: ".book-item"
    fields:
      title: ".title"
      author: ".author"
      url: "a@href"

content:
  request: { method: GET, url: "{{chapter.url}}" }
  body: { selector: "#content" }
  clean:
    remove: ["script", "style", ".advert"]
```

## 现在做到哪了

版本 `1.0.0rc4`（**预发布**）。规范已经定下来，**整条链路都通了** ——
装书源、搜书、下载、增量更新、导出、在已下载的正文里搜关键词（纯本地），
全部有命令行入口；本地 API 在同一套 Core 上跑起来了；桌面端最小闭环可用。

**真实站点跑通过一整本**：`bqgnovels.com` 的书源，完整目录 1453 章，
端到端下载 **2036 章 / 451 万字**，0 失败，TXT / Markdown / EPUB 三种导出都正常。

标成 rc 而不是正式版，是因为**真实站点只验证过一个**——那是最简单的一类
（Nuxt SSR、内容直出 HTML）。还没遇到过需要 JS 渲染的、有真实反爬的、
用 GBK 编码的、靠页码规律而非「下一页链接」翻页的站点。
桌面端也还只有最小闭环。

```
规范与领域模型    已冻结
书源引擎 · 网络层  已实现
内容管线 · 导出    已实现
存储 · 任务引擎    已实现
CLI · API        已实现（含鉴权）
桌面端           最小闭环
```

711 个测试通过，覆盖率 85.7%，Ruff 与 Pyright 干净，CI 全绿。

缺口、里程碑对照和下一步看 **[项目进度](docs/progress.md)** —— 进度信息只在那份文档里维护。

## 怎么用

**推荐命令行。** 三条路用的都是同一套 Core，行为和产物完全一致，但完成度不一样：

| | 命令行 | 桌面端 | 本地 API |
|---|---|---|---|
| 搜索书源 | ✅ | ✅ | ✅ |
| 下载 | ✅ | ✅ 只能从搜索结果点 | ✅ |
| 任务进度 | ✅ | ✅ | ✅ |
| 增量更新 / 导出 | ✅ | ⬜ 未接 | ✅ |
| 书架 / 章节浏览 | ✅ | ⬜ 占位页 | ✅ |
| 书源管理 | ✅ | ⬜ 占位页 | ✅ |
| 设置 | ✅ | ⬜ 占位页 | ✅ |
| 本地全文搜索 | ✅ | ⬜ 未接 | ✅ |

桌面端目前只有**搜索**和**下载**两个页面能用，书架、书源管理、设置都还是占位页。
**所以推荐命令行** —— 它是功能最全、最稳的入口。桌面端和 API 是给
「想要界面」和「想自己写客户端」的场景准备的。

### 方式一：用发布包（推荐）

到 [Releases](https://github.com/luoqingciya/mograb/releases) 下载
`MoGrab-CLI-v<版本>-win-x64.zip`（Linux 用 `.tar.gz`），解压即用：

```
MoGrab-CLI/
├── mog.exe
├── _internal/
└── data/          ← 首次运行自动创建
```

**自带 Python 运行时，不需要装 Python、uv 或任何依赖。**
整个目录可以拷到 U 盘上带走，`data/` 跟着走。

### 方式二：从源码跑（开发用）

需要 Python 3.11+ 和 [uv](https://github.com/astral-sh/uv)：

```bash
git clone https://github.com/luoqingciya/mograb.git
cd mograb
uv sync --all-packages

uv run mog --help          # 跑 CLI
uv run pytest -q           # 跑测试
```

开发时数据落在 `<仓库根>/data/`（已在 `.gitignore` 里排除），
和发布包的 `<程序目录>/data/` 是同一套逻辑。

### 方式三：桌面端（Windows）

到 Releases 下载 `MoGrab-Setup-v<版本>-win-x64.exe` 安装，
或 `MoGrab-v<版本>-win-x64.zip` 解压直接用。

桌面端内置后端 sidecar，启动后自己拉起来，不用手工开服务。

## 命令行教程

下面按「第一次用」的顺序走一遍。**书源要自己准备** —— 项目不内置任何书源，
理由见下面的「不做什么」。

### 1. 装一个书源

书源是一份 YAML，描述怎么从某个站点取书。

```bash
mog source install my-source.yaml
mog source list
```

```
┌───────────┬─────────────────────┬───────┬────────────────────────────┬──────┐
│ ID        │ 名称                │ 版本  │ 能力                       │ 状态 │
├───────────┼─────────────────────┼───────┼────────────────────────────┼──────┤
│ bqgnovels │ 笔趣阁（bqgnovels） │ 1.0.0 │ search,book,chapters,cont… │ 正常 │
└───────────┴─────────────────────┴───────┴────────────────────────────┴──────┘
```

写书源的工具链：

```bash
mog source init my-source          # 脚手架，产物直接能过 lint
mog source lint my-source          # 只查规则能不能编译
mog source test my-source          # 用离线快照真跑一遍提取，查结果是否为空
mog source doctor bqgnovels        # 对着真实站点体检
```

### 2. 搜书

```bash
mog search 斗罗大陆
```

```
┌───────────┬────────────────────┬──────────────┬──────────────────────────────┐
│ 来源      │ 书名               │ 作者         │ URL                          │
├───────────┼────────────────────┼──────────────┼──────────────────────────────┤
│ bqgnovels │ 斗罗大陆3龙王传说  │ 唐家三少     │ https://…/book/49907         │
└───────────┴────────────────────┴──────────────┴──────────────────────────────┘
用 `mog download --url <URL> --source <来源>` 下载
```

### 3. 下载

```bash
mog download --url https://www.bqgnovels.com/book/49907 --source bqgnovels
```

进度条就地刷新，跑完打印结果：

```
⠦ 下载章节 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2036/2036 0:35:03
完成：新下载 2036 章，失败 0 章，共 2036 章
本地已有 2036 章 / 4512103 字
```

**中断了直接重跑同一条命令**，已下过的章节会跳过（增量 diff 按章节 ID / URL /
序号三路匹配，站点改版换了链接也能对上）。

### 4. 查书架、读章节

`book_id` 是一串 ULID，记不住 —— **不给 ID 就是书架列表**：

```bash
mog book
```

```
┌─────────────────────────────────┬───────────────────┬──────────┬──────┬────────────┐
│ ID                              │ 书名              │ 作者     │ 章节 │ 更新       │
├─────────────────────────────────┼───────────────────┼──────────┼──────┼────────────┤
│ book_01M4590M0VAKH0ND8G62G8G290 │ 斗罗大陆3龙王传说 │ 唐家三少 │ 2036 │ 2026-10-05 │
└─────────────────────────────────┴───────────────────┴──────────┴──────┴────────────┘
用 `mog book <ID>` 看详情（含字数），`mog export <ID>` 导出
```

```bash
mog book book_01M4590M0VAKH0ND8G62G8G290                 # 详情
mog book book_01M4590M0VAKH0ND8G62G8G290 --chapters      # 章节列表
mog book book_01M4590M0VAKH0ND8G62G8G290 --chapter 1     # 读第 1 章正文
```

### 5. 导出

```bash
mog export --format epub book_01M4590M0VAKH0ND8G62G8G290
```

```
已导出 → …\data\exports\唐家三少 - 斗罗大陆3龙王传说.epub
```

支持 `txt` / `markdown` / `epub`。输出路径默认按配置里的模板生成，
也可以用 `--output` 指定。忘了导到哪去了就查任务详情：

```bash
mog task list                       # 找那条 export_book
mog task show <task_id>             # 参数里带 path
```

### 6. 在已下载的正文里搜

```bash
mog find 荔枝
```

纯本地、不联网，搜的是**已下载的章节正文**（和 `mog search` 搜书源是两件事）。

### 7. 盯着一个任务

`mog download` 是就地跑、跑完就退出。如果是通过 API 或桌面端起的任务，
或者想另开一个窗口盯着：

```bash
mog task watch <task_id>     # 盯着一个，进终态自动退出
mog task watch               # 盯着所有，Ctrl+C 停
```

```
task_585c00a1c9474198   download_book   running   119/2036
task_585c00a1c9474198   download_book   running   121/2036
task_585c00a1c9474198   download_book   success   2036/2036
```

```bash
mog task pause <task_id>     # 暂停
mog task resume <task_id>    # 继续
mog task cancel <task_id>    # 取消
```

> 这几条和 `watch` 一样**需要本地 server 在跑**（`mog server start`）——
> 任务状态在 server 进程的内存里。`mog download` 不需要。

### 其它

```bash
mog update <book_id>              # 增量更新
mog cache stats                   # 缓存占用
mog config show                   # 当前生效的配置
mog server start                  # 起本地 API
```

**所有命令都支持 `--json`**，方便脚本接：

```bash
mog book --json | jq '.[0].id'
```

## 数据放在哪

便携式的，所有运行数据都在程序目录下的 `data/` 里，不写系统目录。
删掉 `data/` 就等于恢复出厂设置，整个程序目录可以直接拷走。

```
<程序目录>/
├── mog.exe
├── _internal/
└── data/
    ├── config.toml
    ├── token            ← API 访问令牌，首次启动自动生成
    ├── mograb.db
    ├── cache/
    ├── covers/
    ├── logs/
    ├── exports/
    └── sources/
```

开发时从仓库根运行，数据落在 `<仓库根>/data/`。

想改位置就设 `MOGRAB_HOME`。

## 配置

配置文件是 `data/config.toml`，`mog config init` 生成带注释的模板，
`mog config show` 看当前生效的值。

最常改的几项：

```toml
[download]
concurrency = 4          # 全局并发上限
retry = 3                # 单请求重试次数
timeout_ms = 15000
# proxy = "http://127.0.0.1:7890"

[cache]
enabled = true
max_size = "5GB"
ttl_seconds = 1800
```

**代理**有两条路，都行：

1. `[download] proxy = "http://127.0.0.1:7890"` —— 写进配置文件
2. 环境变量 `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` —— 不填配置时自动读

第 2 条对「本机挂了 TUN 模式代理」之外的场景够用，比如只给 MoGrab 单独走代理：

```bash
HTTPS_PROXY=http://127.0.0.1:7890 mog download --url ... --source ...
```

所有配置项都支持环境变量覆盖，前缀 `MOGRAB_`、嵌套用 `__`，
例如 `MOGRAB_DOWNLOAD__CONCURRENCY=8`、`MOGRAB_SERVER__PORT=9000`。

## 结构

```
MoGrab/
├── packages/mograb/     核心库
│   └── src/mograb/
│       ├── app.py       composition root（CLI 与 API 共用）
│       ├── domain/      领域模型
│       ├── source/      书源加载、校验、执行、fixture 测试
│       ├── network/     HTTP、缓存、限流、重试
│       ├── task/        队列、Worker、调度
│       ├── storage/     ORM、仓储、SQLite
│       ├── content/     清洗、规范化、校验
│       ├── export/      TXT / Markdown / EPUB
│       ├── config/      配置与路径
│       └── logging/     结构化日志
├── apps/
│   ├── cli/             命令行，命令名 mog
│   ├── api/             本地 API，FastAPI
│   └── desktop/         桌面端，Electron
├── sources/             本地书源工作区（不进仓库）
├── tests/               单元 / 集成 / 书源 fixture
└── docs/                文档
```

书源不进远程仓库 —— 涉及第三方站点的抓取规则不适合随主仓库分发。
`sources/` 已在 `.gitignore` 里，留给你本地开发和调试。
规范的参考实现和测试数据放在 `tests/fixtures/example-source/`。

架构上就一条硬规则：CLI 和桌面端都不许自己实现业务逻辑，一切走 Core 或 API。
其他的边界写在[架构总览](docs/architecture/overview.md)里。

版本号只有一个来源，仓库根的 [`VERSION`](VERSION) 文件。三个包构建时都读它，
改一处全局生效。

## 文档

- [项目进度](docs/progress.md) —— **做到哪了、还差什么**，进度只在这里维护
- [架构总览](docs/architecture/overview.md) —— 分层、边界、数据流、技术选型
- [Source Specification v1](docs/source-spec/source-spec-v1.md) —— 书源规范，最重要的一份
- [Domain Model v1](docs/domain-model/domain-model-v1.md) —— 领域模型与任务状态机
- [Storage v1](docs/storage/storage-v1.md) —— 表结构
- [API v1](docs/api/api-v1.md) —— 接口契约
- [开发指南](docs/development/getting-started.md) —— 环境、命令、提交规范
- [CI 与发布](docs/development/ci.md) —— 流水线与打包
- [规划评估报告](docs/evaluation/规划评估报告.md) —— 对原始规划书的评估，以及几个关键裁决的理由
- [原始规划书](docs/planning/项目规划书.md) —— 历史存档，**不是规范**，只用来追溯出处
- [ADR](docs/architecture/decisions/) —— 架构决策记录

## 不做什么

MoGrab 是个人工具，不是通用爬虫框架。以下明确不做：

- 兼容 Legado 全部规则
- 执行任意第三方脚本
- 复杂反爬对抗、验证码破解
- 绕过付费墙或访问控制
- 多用户服务器、移动端、分布式爬虫

**也不内置任何书源。** 书源描述的是针对具体站点的抓取规则，
随主仓库分发容易让项目被误解成「某个站点的专用工具」，也会把站点改版、
失效、条款变动带进仓库历史。规范、引擎和工具链在这里，书源由你自己写、自己留。

## 使用须知

仅供个人学习研究，抓取公开可访问的内容。

使用者需要自己遵守目标站点的服务条款、robots.txt 和所在地法律。
不要用于商业用途、批量分发版权内容，也不要给站点造成不合理负载 ——
程序默认单源并发 2、请求间隔 500ms，别改得比这更激进。

项目本身不提供、不内置任何版权内容。书源只描述如何访问公开页面，
不含内容数据。

按 GPL-3.0 分发，不提供任何担保。

## 许可证

[GNU General Public License v3.0](LICENSE)，`GPL-3.0-only`。

第三方依赖的许可证清单在 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)，
里面也说明了为什么这个项目刻意避开 AGPL 依赖。
