# CLI 命令完全参考（`mog`）

> 对应版本：MoGrab `1.0.0`（Rust 实现见 [crates/mograb-cli](../../crates/mograb-cli/src/main.rs)）。

---

## 1. 全局选项

以下选项可用于所有子命令前后：

| 选项 | 说明 |
|------|------|
| `-V`, `--version` | 输出版本号（例如 `mog (MoGrab) 1.0.0`）并退出 |
| `-v`, `--verbose` | 输出详细调试日志 |
| `--json` | 各业务子命令均支持以机器可读的漂亮 JSON 输出（`mog logs` 除外） |
| `-h`, `--help` | 打印命令或子命令帮助 |

---

## 2. 退出码约定

脚本调用可根据进程退出码判断错误类型：

| 退出码 | 常量名 | 含义 |
|--------|--------|------|
| `0` | `EXIT_OK` | 成功 |
| `1` | `EXIT_ERROR` | 一般运行时或内部错误 |
| `2` | `EXIT_USAGE` | 参数缺漏或用法/任务参数不合法 |
| `3` | `EXIT_NOT_FOUND` | 书籍、书源或任务不存在 |
| `4` | `EXIT_VALIDATION` | 书源 Schema 校验失败或正文内容校验未通过 |
| `5` | `EXIT_NETWORK` | 网络请求、超时、限流或 HTTP 状态异常 |
| `130` | `EXIT_INTERRUPTED` | 用户中断（Ctrl+C） |

---

## 3. 子命令一览

### `mog init` — 初始化数据目录
创建 `cache/`、`covers/`、`exports/`、`logs/`、`sources/` 目录、SQLite 数据库表与 `token` 令牌文件。幂等可重复运行。

```bash
mog init
mog init --json
```

---

### `mog config` — 配置与路径管理

| 子命令 | 说明 |
|--------|------|
| `mog config init [--force] [--json]` | 在数据目录下生成带注释的默认 `config.toml` |
| `mog config path [--json]` | 打印当前生效的根目录、配置文件、数据库、导出、书源、日志路径 |
| `mog config show [--json]` | 打印合并 `config.toml` 与环境变量覆盖后的最终生效配置 |

---

### `mog source` — 书源管理与开发工具链

| 子命令 | 说明 |
|--------|------|
| `mog source init <NAME> [-d, --dir <DIR>]` | 在 `<DIR>/<NAME>` 生成带示例与 `fixtures/` 的书源开发脚手架 |
| `mog source lint <PATH> [--json]` | 离线静态检查（Schema、选择器语法、模板变量、域名白名单、`clean` 提示） |
| `mog source test <TARGET> [--json]` | 读取 `<TARGET>/fixtures/cases.yaml` 与快照离线试跑提取规则，检验非空结果 |
| `mog source install <TARGET> [--force] [--json]` | 校验并复制 `source.yaml` 进数据目录 `sources/`，`--force` 覆盖已有同 ID 书源 |
| `mog source list [--json]` | 列出所有已安装书源的 ID、版本、启用状态、健康度与能力 |
| `mog source show <SOURCE_ID> [--json]` | 查看单个书源的作者、`repository`、能力、权限白名单与完整规则 |
| `mog source enable <SOURCE_ID>` | 启用书源 |
| `mog source disable <SOURCE_ID>` | 禁用书源（不参与默认并发搜索） |
| `mog source rescan [--json]` | 重新扫描数据目录 `sources/` 并同步到数据库 |
| `mog source doctor [SOURCE_ID] [--live] [--json]` | 诊断书源配置；加上 `--live` 对目标站点发起在线连通性检测 |
| `mog source remove <SOURCE_ID> [-y, --yes]` | 卸载已安装书源 |

---

### `mog search` — 并发搜索书源

```bash
mog search [OPTIONS] <KEYWORD>
```

| 参数 / 选项 | 说明 |
|-------------|------|
| `<KEYWORD>` | 搜索关键词 |
| `-s`, `--source <SOURCE_ID>` | 限定只搜指定书源（可多次传入 `-s a -s b`） |
| `-n`, `--limit <N>` | 最多返回结果数（默认 `20`） |
| `--json` | 输出 JSON 数组 |

---

### `mog download` — 下载整本（并可选导出）

支持两种输入方式：对**已入库书籍**按 `<BOOK_ID>` 续传，或按 **`--source` + `--url`** 直接从详情页 URL 开始抓取。

```bash
mog download --source bqgnovels --url "https://www.example.com/book/1001" -f epub
mog download <BOOK_ID> -f txt -o ./out.txt
```

| 参数 / 选项 | 说明 |
|-------------|------|
| `[BOOK_ID]` | 已入库书籍 ID（与 `--url`/`--source` 二选一） |
| `-u`, `--url <URL>` | 书籍详情页 URL |
| `-s`, `--source <SOURCE_ID>` | 书源 ID |
| `-f`, `--format <FORMAT>` | 下载完成后立即导出（`txt` / `markdown` / `epub`） |
| `-o`, `--output <PATH>` | 自定义导出文件路径 |
| `--json` | 输出下载与导出结果 JSON |

---

### `mog update` — 增量检查更新

```bash
mog update <BOOK_ID> [--dry-run] [--json]
```

- 默认先拉取远端最新目录与本地三路 diff 后，仅下载新增与缺失章节；
- 加上 `--dry-run` 只报告待新增/缺失数量而不发起正文下载。

---

### `mog book` — 书架、详情与终端阅读

```bash
mog book [-n, --limit 50] [--json]            # 省略 BOOK_ID 时列出书架
mog book <BOOK_ID> [--json]                   # 查看单本书元信息与总字数
mog book <BOOK_ID> -c [--json]                # 列出全部章节摘要（序号/标题/字数）
mog book <BOOK_ID> --chapter <N> [--json]     # 在终端阅读指定章节正文
```

---

### `mog export` — 导出本地书籍

```bash
mog export <BOOK_ID> [-f, --format epub] [-o, --output <PATH>] [--json]
```

未传 `-f` 时读取 `config.toml` 中 `[output].format`（默认 `epub`）；未传 `-o` 时按 `output.template` 自动写入导出目录。

---

### `mog find` — 本地全文检索

```bash
mog find <KEYWORD> [-b, --book <BOOK_ID>] [-n, --limit 50] [--json]
```

纯本地 SQLite 查询已下载章节正文中的关键字，不产生任何网络请求。

---

### `mog task` — 任务队列与监控

| 子命令 | 说明 |
|--------|------|
| `mog task list [-s, --status <STATUS>] [-n <N>] [--json]` | 列出历史/进行中任务 |
| `mog task show <TASK_ID> [--json]` | 查看任务详情及子条目列表 |
| `mog task pause <TASK_ID> [--json]` | 暂停任务（需运行本地 API 服务） |
| `mog task resume <TASK_ID> [--json]` | 恢复已暂停任务（需运行本地 API 服务） |
| `mog task cancel <TASK_ID> [--json]` | 取消任务（需运行本地 API 服务） |
| `mog task retry <TASK_ID> [--json]` | 重试失败或已取消任务（需运行本地 API 服务） |
| `mog task watch [TASK_ID] [--json]` | 通过 SSE 持续打印实时进度；指定 ID 时进入终态自动退出 |

---

### `mog cache` — HTTP 缓存管理

| 子命令 | 说明 |
|--------|------|
| `mog cache stats [--json]` | 显示当前缓存条目数、已用容量与配额 |
| `mog cache clear [-y, --yes] [--json]` | 清空全部 HTTP 缓存 |
| `mog cache clear-source <SOURCE_ID> [-y, --yes] [--json]` | 仅清理某个书源域名的缓存 |

---

### `mog server` — 本地 REST API 服务与令牌

| 子命令 | 说明 |
|--------|------|
| `mog server start [-p, --port <PORT>] [-b, --bind <HOST>] [--daemon]` | 启动本地 Axum API 服务 |
| `mog server status [--json]` | 检查本地 API 服务是否在线 |
| `mog server stop [--json]` | 停止后台守护启动的 API 服务 |
| `mog server token [--json]` | 打印（若无则生成）`data/token` 中的 Bearer 令牌 |

---

### `mog logs` — 日志查看

```bash
mog logs [-t, --target app|task|source] [-n, --lines 50] [-f, --follow]
```

---

### `mog completion` — Shell 自动补全

```bash
mog completion <bash|zsh|fish|powershell|elvish>
```

例如为 Bash / Zsh 启用补全：

```bash
source <(mog completion zsh)
```
