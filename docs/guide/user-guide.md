# 用户使用指南

> 适用于 MoGrab `1.0.0`（Windows x64 / Linux x64 桌面端与命令行）。如果你想亲自编写网站书源规则，请看 [写书源从入门到实战教程](../source-spec/writing-a-source.md)。

---

## 1. 安装与获取

从 GitHub [Releases](https://github.com/luoqingciya/mograb/releases) 下载对应平台产物：

| 组件 | 平台 | 安装包 / 压缩包 | 说明 |
|------|------|----------------|------|
| **桌面端** | Windows x64 | `mograb-desktop-v<版本>-windows-x64-setup.exe` | 标准 NSIS 安装向导 |
| **桌面端（便携）** | Windows x64 | `mograb-desktop-v<版本>-windows-x64.zip` | 解压即用，数据留在同目录 `data/` |
| **桌面端** | Linux x64 (Debian/Ubuntu) | `mograb-desktop-v<版本>-linux-x64.deb` | `sudo apt install ./mograb-desktop-*.deb` |
| **桌面端** | Linux x64 (Fedora/RHEL) | `mograb-desktop-v<版本>-linux-x64.rpm` | `sudo dnf install ./mograb-desktop-*.rpm` |
| **命令行** | Windows x64 | `mograb-cli-v<版本>-windows-x64.zip` | 内含单二进制 `mog.exe`，无外部依赖 |
| **命令行** | Linux x64 | `mograb-cli-v<版本>-linux-x64.tar.gz` | 内含单二进制 `mog`，无外部依赖 |

下载后建议用随附的 `SHA256SUMS.txt` 校验压缩包完整性：

```bash
sha256sum -c --ignore-missing SHA256SUMS.txt
```

> **重要说明**：MoGrab 不内置任何第三方网站书源。首次使用前请先自行编写或安装合法的 `.yaml` 书源（参考 [写书源教程](../source-spec/writing-a-source.md) 与示例夹具 [example-source](../../tests/fixtures/example-source/README.md)）。

---

## 2. 桌面端使用指南（Tauri v2）

MoGrab Desktop 已在 Rust 宿主进程内直接嵌入本地 API 服务（监听 `127.0.0.1:48721`，若本机已有同端口服务运行则自动复用），启动即可使用，无需手动额外起后台服务。

左侧栏共提供 6 个功能页面，底部提供 **主题切换按钮**，可在 **深色 / 浅色 / 跟随系统** 三种高对比度主题间循环切换并自动记忆选择。

### 2.1 搜索

- **跨源关键词搜索**：输入书名或作者，点击上方书源芯片可限定在某一个或多个已启用、且具备 `search` 能力的书源中并发搜索。
- **作品信息与加入队列**：卡片展示书名、作者、来源 ID 与简介，点击「下载」会提交下载任务并跳转到「任务」页实时查看进度。
- **按 URL 直接下载**：展开「按 URL 直接下载」抽屉，选择目标书源并粘贴书籍详情页链接即可绕过搜索直接抓取（适用于仅支持直链或未声明搜索能力的书源）。

### 2.2 书架与内置阅读器

- **藏书过滤**：支持按书名、作者或书源 ID 实时过滤本地已入库书籍。
- **书籍详情**：点击任意书籍进入详情页，可查看元信息、简介、当前章数与总字数，并支持关键词过滤章节目录（未下载正文的章节会显示为「未下载」虚线框）。
- **增量检查更新**：点击「检查更新」会拉取最新目录并增量下载新增或缺失章节。
- **一键导出**：右上角选择 `EPUB` / `TXT` / `Markdown` 后点击「导出」，后台生成文件后会在通知栏与「任务 → 近期导出记录」中展示输出路径。
- **内置阅读器**：点击任意已下载章节打开内置阅读器，支持 **`A-` / `A+` 字号调节**、**上一章 / 目录 / 下一章** 切换；从「全文检索」页点击「阅读本章」也会直接跳转至此。

### 2.3 全文检索

- 对已下载到本地 SQLite 数据库的所有章节正文进行纯本地关键词匹配（完全不联网）。
- 支持选择全部书籍或限定单本书籍检索，命中片段会自动用高亮标签标出关键词；点击「阅读本章」直接打开对应章节正文定位。

### 2.4 任务与导出历史

- 通过 SSE 实时接收后台下载、更新与导出任务的百分比进度、成功/失败计数。
- 支持状态芯片筛选（全部 / 进行中 / 已完成 / 失败/取消）。
- 支持针对任务状态的控制操作：进行中任务可 **暂停** 或 **取消**；已暂停任务可 **继续** 或 **取消**；失败或已取消任务可 **重试**。
- 页面下方列出近期导出作业的状态、文件大小及磁盘路径。

### 2.5 书源管理

- **安装 / 更新书源**：展开「+ 安装 / 更新书源」，支持 **粘贴 YAML 内容** 或 **填写本地 `.yaml` / `.json` 文件路径**；勾选「忽略非致命校验/覆盖已存在」等同 CLI 的 `--force`。
- **启停 / 体检 / 详情 / 卸载**：
  - 「禁用 / 启用」控制该书源是否参与默认并发搜索；
  - 「体检」会向真实站点发起在线连通性检测并刷新健康徽章（正常 / 降级 / 不可用 / 不支持）；
  - 「详情」展示书源declared 的 `permissions.network` 域名白名单与磁盘配置文件路径；
  - 「重扫 sources/」可立即同步手动放入数据目录 `sources/` 的文件；
  - 「卸载」采用防误触二次确认按钮。

### 2.6 设置与运行环境

- **运行时环境卡片**：直观显示当前版本号、运行模式（进程内嵌入 Axum API 或复用外部本地服务），以及 `数据目录`、`配置文件`、`数据库`、`导出目录`、`书源目录`、`日志目录` 的真实绝对路径。
- **核心配置在线编辑**：支持直接在界面修改全局并发（1–64）、单书源并发（1–32）、请求间隔、单请求超时、失败重试次数、HTTP 代理地址、默认导出格式、导出文件名模板、缓存开关与容量上限、日志级别，保存后直接写入 `config.toml`。
- **HTTP 缓存运维**：在进程内嵌入模式下展示当前缓存条目数与磁盘占用，支持「清理过期缓存」与「清空全部缓存」。

---

## 3. 数据目录、便携模式与路径规则

MoGrab 按运行环境自动确定数据根目录（优先级从高到低）：

1. **环境变量 `MOGRAB_HOME`**：若设置，则所有组件（CLI / API / 桌面端）强制使用该目录。
2. **Linux 系统安装的桌面端**（`.deb` / `.rpm`，可执行文件位于只读目录如 `/usr/bin` 且非仓库开发树）：自动使用 `$XDG_DATA_HOME/mograb`（未设则 `~/.local/share/mograb`）。
3. **源码开发模式**（从仓库树内运行）：自动使用 `<仓库根>/data/`。
4. **Windows / CLI 便携模式**：自动使用 `<可执行文件所在目录>/data/`，整个文件夹可直接拷贝迁移。

数据目录内部结构如下：

```text
data/
├── config.toml       # 主配置文件
├── token             # 本地 API Bearer 访问令牌（首次启动自动生成）
├── mograb.db         # SQLite WAL 主数据库（books / chapters / tasks / exports / http_cache）
├── covers/           # 下载缓存的书籍封面图片
├── exports/          # 默认导出文件保存目录
├── sources/          # 已安装的书源规则文件（<id>.yaml）
└── logs/             # 结构化滚动日志文件（app.log / task.log / source.log）
```

---

## 4. 配置文件 `config.toml` 全项参考

运行 `mog config init` 可在数据目录下生成带注释的默认 `config.toml`；运行 `mog config show` 查看合并环境变量覆盖后的当前最终生效配置。

```toml
[server]
host = "127.0.0.1"          # API 监听地址
port = 48721                # API 监听端口（1024..=65535）
health_timeout_ms = 5000    # 健康检查等待超时（>= 100）
auth = true                 # 是否启用 Bearer 令牌校验

[download]
concurrency = 4             # 全局并发上限（1..=64）
per_source_concurrency = 2  # 单书源默认并发上限（1..=32）
retry = 3                   # 单请求重试次数（0..=10）
request_interval_ms = 500   # 最小请求间隔（0..=60000 ms）
timeout_ms = 15000          # 单请求超时（100..=120000 ms）
# proxy = "http://127.0.0.1:7890"  # 未配置时自动读取系统 HTTPS_PROXY / HTTP_PROXY / ALL_PROXY

[cache]
enabled = true              # 是否开启 SQLite HTTP 响应缓存
max_size = "5GB"            # 支持 B / KB / MB / GB / TB
ttl_seconds = 1800          # 搜索与目录等页面默认缓存 TTL（秒）
content_ttl_seconds = 604800 # 正文页默认缓存 TTL（默认 7 天）

[output]
directory = "exports"                   # 导出目录（相对 data/ 或绝对路径）
format = "epub"                         # 默认导出格式：epub / txt / markdown
template = "{{author}} - {{title}}"     # 导出文件名模板（支持 {{title}} / {{author}} / {{source_id}} / {{book_id}}）
chapter_template = "{{index}}. {{title}}" # 单章节标题展示模板

[output.metadata]
# EPUB 自定义 Dublin Core 元数据（identifier 为系统保留键，不可覆盖）
# 值支持模板变量 {{title}}、{{author}}、{{source_id}}
publisher = "个人整理"
subject = "{{author}} 作品"

[logging]
level = "INFO"              # DEBUG / INFO / WARNING / ERROR
json_output = false         # 是否以 JSON 行格式落盘
max_bytes = 10485760        # 单日志文件轮转大小（默认 10 MB）
backup_count = 5            # 保留历史轮转文件个数
```

### 用环境变量临时覆盖任意配置

所有配置项都支持以 `MOGRAB_<SECTION>__<FIELD>`（双下划线分隔）格式覆盖：

```bash
MOGRAB_DOWNLOAD__CONCURRENCY=8 mog download <book_id>
MOGRAB_SERVER__PORT=49000 mog server start
HTTPS_PROXY=http://127.0.0.1:7890 mog download --source my_site --url "https://..."
```

---

## 5. 本地 API 与脚本自动化

如需自己写脚本或通过 HTTP 调用核心能力：

1. 启动服务并读取访问令牌：

   ```bash
   mog server start
   mog server token
   ```

2. 携带 `Authorization: Bearer <token>` 访问接口（Swagger 交互文档见 `http://127.0.0.1:48721/docs`，完整接口契约见 [API v1](../api/api-v1.md)）：

   ```bash
   TOKEN="$(mog server token)"
   curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:48721/api/v1/books
   ```

3. 配合 CLI `--json` 做 Shell 流水线（除 `mog logs` 外的全部业务命令均支持 `--json`）：

   ```bash
   # 导出书架第一本书为 EPUB
   BOOK_ID="$(mog book --json | jq -r '.[0].id')"
   mog export --format epub "$BOOK_ID"
   ```

---

## 6. 日常运维与常见问题

- **下载一半中断怎么续传？** 直接重跑同一条 `mog download`（或对已入库书籍跑 `mog update <book_id>`）。引擎通过章节 ID、规范化 URL 与序号三路对齐，仅抓取缺失章节。
- **想确认某条请求为什么失败或被跳过？** 查看实时日志流：
  ```bash
  mog logs -t app -n 100
  mog logs -t source -f
  ```
- **需要删除旧页面缓存迫使重新拉取最新目录？** `mog cache clear-source <source_id>` 或 `mog cache clear -y`。
- **完整 CLI 命令参数查询**：见 [CLI 命令完全参考](cli-reference.md)。
