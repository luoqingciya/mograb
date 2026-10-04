# MoGrab Source Specification v1

> 状态：已冻结
> 版本：`spec_version: 1`
> 生效日期：2026-10-04
> 对应规划书：§3.2、§3.3、§7–§13、§41、§53
> Python 映射：`mograb/domain/source.py`

---

## 1. 设计目标

MoGrab 不追求兼容 Legado 的历史书源，而是建立一套**干净、严格、可测试、可版本化**
的声明式书源规范。

书源**只描述**：

```
请求什么  →  从哪里取  →  如何提取  →  如何转换
```

书源**不负责**：

```
重试 · 并发 · 缓存 · 任务调度 · 数据库 · 日志
```

后六项由 MoGrab Core 统一实现。这条边界是规范的核心，任何试图在书源中表达
「重试几次」「并发多少」的设计都应被拒绝——它们属于 `network` 策略块（由 Core 解释执行），
而非书源逻辑。

### 1.1 安全底线（不可协商）

> **书源不是 Python 插件，不允许执行任意代码。**

v1 不支持脚本、表达式求值、模板函数调用。所有能力必须由固定的算子组合表达。
这一约束牺牲了表达力，但换来了可静态分析、可安全分发、可离线测试的生态基础。

---

## 2. 顶层结构

```yaml
spec_version: 1
id: example
name: Example
version: 1.0.0
homepage: https://example.com
description: ...
license: GPL-3.0-only
authors: [MoGrab Contributors]

engine_min_version: 0.1.0
engine_max_version: null

capabilities: [search, book, chapters, content]

network:      {...}
permissions:  {...}
search:       {...}
book:         {...}
chapters:     {...}
content:      {...}
transforms:   [...]
```

### 2.1 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `spec_version` | int | 是 | 规范版本，v1 恒为 `1`。不等于引擎支持版本时立即失败 |
| `id` | str | 是 | 书源唯一 ID。`^[a-z][a-z0-9]*([-_][a-z0-9]+)*$` |
| `name` | str | 是 | 展示名 |
| `version` | str | 是 | **书源自身**的语义化版本，如 `1.2.0` |
| `homepage` | str | 否 | 来源站点首页 |
| `description` | str | 否 | 用途说明 |
| `license` | str | 否 | 书源自身的许可证标识（SPDX） |
| `authors` | list[str] | 否 | 作者列表 |
| `engine_min_version` | str | 否 | 所需最低引擎版本 |
| `engine_max_version` | str | 否 | 兼容的最高引擎版本（不含） |
| `capabilities` | list[str] | 是 | 声明的能力列表 |
| `network` | object | 否 | 网络策略（Core 解释，非书源逻辑） |
| `permissions` | object | 否 | 权限声明 |
| `transforms` | list | 否 | 全局变换，作用于所有能力的提取结果 |

> **`spec_version` 与 `version` 是两个不同的字段**，这是对规划书 §7/§13/§53
> 中 `version` 语义冲突的修正。详见 `docs/architecture/decisions/ADR-0002`。

### 2.2 未知字段处理

**严格模式**：任何未在规范中定义的字段都会导致校验失败。

理由：书源由社区贡献，拼写错误（如 `capabilites`）若被静默忽略，
会造成「书源看起来正常但某能力不生效」的隐蔽故障。

---

## 3. Capabilities

### 3.1 v1 已实现

| 能力 | 必需规格 | 说明 |
|------|---------|------|
| `search` | `search` | 关键词搜索 |
| `book` | `book` | 书籍详情 |
| `chapters` | `chapters` | 章节目录 |
| `content` | `content` | 章节正文 |

### 3.2 保留（未来版本）

`discover` · `image` · `login` · `cookie` · `update`

v1 引擎遇到保留能力时抛 `SourceUnsupportedError`。

### 3.3 一致性约束（强制）

> **声明了能力就必须提供对应规格；提供了规格就必须声明对应能力。**

两者任一不满足都导致校验失败。这避免了「声明了 content 但忘记写 content 块」
和「写了 content 块但忘记声明能力导致永不执行」两类错误。

### 3.4 能力判断的正确用法

```python
# 正确写法：正确：先判断能力存在
if source.supports(SourceCapability.SEARCH):
    results = await engine.search(source, keyword)

# 错误写法：错误：假定能力存在
results = await engine.search(source, keyword)  # 未声明 search 时会抛错
```

注意：规划书 §9 的表述「而不是 `source.search()`」易被误读为「禁止调用方法」。
正确规则是**不得假定能力存在**；具备能力时调用完全合法。

---

## 4. 请求（Request）

所有能力共用同一套请求描述。

```yaml
request:
  method: GET            # GET | POST，默认 GET
  url: "https://example.com/search"
  headers:
    User-Agent: "{{user_agent}}"
  query:
    q: "{{keyword}}"
    page: "{{page}}"
  body: null             # str 或 map（POST）
  cookies: {}
  encoding: null         # 强制编码；null 时由引擎自动探测
  timeout_ms: null       # 覆盖 network.timeout_ms
```

### 4.1 模板变量

语法：`{{变量名}}`，支持点号命名空间。

| 变量 | 可用范围 | 说明 |
|------|---------|------|
| `{{keyword}}` | search | 搜索关键词 |
| `{{page}}` | search | 页码 |
| `{{book.url}}` | book / chapters | 书籍详情页 URL |
| `{{book.id}}` | book | 来源站书籍 ID |
| `{{book.title}}` | book | 书名 |
| `{{chapter.url}}` | content | 章节页 URL |
| `{{chapter.index}}` | content | 章节序号 |
| `{{chapter.id}}` | content | 来源站章节 ID |
| `{{user_agent}}` | 全部 | 引擎注入的 UA（**书源不应硬编码**） |
| `{{config.<key>}}` | 全部 | 用户配置项 |

**严格模式**：引用未定义的变量会抛 `SourceExecutionError`，而非静默替换为空串。
Linter 会在静态检查阶段报出该错误。

### 4.2 编码探测

未指定 `encoding` 时，引擎按以下顺序探测：

1. HTTP 响应头 `Content-Type: charset=...`
2. HTML `<meta charset="...">`
3. HTML `<meta http-equiv="Content-Type" content="...charset=...">`
4. 默认 `utf-8`

`gb2312` 与 `gbk` 会被**统一提升为 `gb18030`**（前两者是其子集，
用超集解码可避免生僻字失败）。

---

## 5. 提取（Extractor）

### 5.1 统一字符串语法

| 写法 | 类型 | 说明 |
|------|------|------|
| `.book-item` | CSS | CSS 选择器 |
| `a@href` | CSS + 属性 | 选择器 + 取属性；`@text` 表示取文本 |
| `@href` | 属性 | 作用于当前上下文节点 |
| `@text` | 文本 | 当前节点文本 |
| `xpath://div[@id='c']` | XPath | |
| `jsonpath:$.data[*].title` | JSONPath | |
| `regex:第(\d+)章` | 正则 | 取第 1 捕获组；无捕获组则取整体 |

### 5.2 列表提取（`result`）

```yaml
result:
  list: ".book-item"          # 定位列表项
  fields:
    title: ".title"
    author: ".author"
    url: "a@href"
  reverse: false              # 目录倒序修正
```

**逐项下钻语义**：`fields` 中的规则作用于**列表项内部**，而非整个文档。
因此 `a@href` 取的是「该项内的第一个 `<a>` 的 href」。

`reverse: true` 用于目录倒序的站点（最新章节在前），引擎会在提取后统一反转为顺序。

### 5.3 未匹配时的行为

**不抛异常**。未匹配返回空值，由上层决定处理方式：

- `search` / `chapters`：缺少 `title` 或 `url` 的条目被**跳过**（不中断整批）
- `book`：缺少 `title` 视为致命错误（`SourceExecutionError`）
- `content`：`body` 未匹配视为致命错误

理由：列表页常有个别畸形条目，不应因一条坏数据导致整本书无法下载；
但详情页/正文页的关键字段缺失说明规则已失效，必须显式报错。

---

## 6. 变换（Transformer）

### 6.1 算子清单（v1）

| 算子 | 参数 | 说明 |
|------|------|------|
| `trim` | — | 去首尾空白 |
| `normalize_whitespace` | — | 连续空白折叠为单空格 |
| `remove_html` | — | 去 HTML 标签并反转义实体 |
| `replace` | `pattern`, `replacement` | 字面替换 |
| `regex_replace` | `pattern`, `replacement` | 正则替换 |
| `prepend` | `value` | 前缀 |
| `append` | `value` | 后缀 |
| `url_join` | — | 相对 URL 转绝对（需 `base_url` 上下文） |
| `default` | `value` | 值为空时的兜底 |
| `join` | `separator` | 列表合并（列表上下文） |

### 6.2 两种写法

```yaml
transform:
  - trim
  - regex_replace:
      pattern: "\\s+"
      replacement: " "
```

### 6.3 作用域与执行顺序

| 作用域 | 位置 | 应用对象 |
|--------|------|---------|
| 全局 | `transforms` | 所有能力的提取结果 |
| 能力级 | `search.transform` 等 | 该能力的所有字段 |

执行顺序：**全局 → 能力级 → 按声明顺序**。

### 6.4 `url_join` 的条件化语义（重要）

v1 的 `transform` 作用于能力下的**所有字段**。若无条件执行 `url_join`，
会把标题也拼成 URL：

```
urljoin("https://site/search", "三体")  →  "https://site/三体"    ← 不对
```

因此 v1 的 `url_join` 采用**保守判定**——仅当值「像 URL 引用」时才拼接：

| 判定 | 结果 |
|------|------|
| 含空白 | 不拼接 |
| 以 `//` / `/` / `./` / `../` 开头 | 拼接 |
| 带 scheme（`https://` 等） | 拼接 |
| 含 `/` 且无空白 | 拼接 |
| 形如 `chapter.html` 的文件名 | 拼接 |
| 其他（如 `三体`、`刘慈欣`） | 不拼接 |

> 已知局限：字段级 transform 将在 **v1.1** 引入，届时可精确指定
> 「仅对 `url` 字段执行 `url_join`」。当前的条件化方案是 v1 的折中，
> 原则是「宁可漏拼，不可误拼」。

---

## 7. 清洗（Clean）

```yaml
content:
  body: "#content"
  clean:
    remove: ["script", "style", ".advert", ".chapter-nav"]
```

`clean.remove` 是 CSS 选择器列表，在**DOM 级**删除匹配节点（发生在正文提取之前）。

除书源声明的规则外，引擎内置以下通用清洗（无需每个书源重复声明）：

- 零宽字符与不可见控制字符
- 常见水印行（`请记住本站`、`本章未完`、`上一章`/`下一章` 等导航行）
- 裸域名行
- 连续空行压缩

---

## 8. 网络策略与权限

### 8.1 `network`

```yaml
network:
  concurrency: 2              # 单源并发上限（1–32）
  request_interval_ms: 500    # 最小请求间隔（礼貌抓取）
  timeout_ms: 15000
  retry: 3
  headers: {}
```

**按书源隔离**：每个书源持有独立的限流器，多个来源不共用全局限制器。
实际并发 = `min(全局并发, 本源并发)`。

### 8.2 `permissions`（安全声明）

```yaml
permissions:
  network:
    - example.com
  cookies: false
  filesystem: false
  script: false
```

| 权限 | v1 策略 |
|------|---------|
| `network` | **必需**。域名白名单，Linter 会校验所有请求 URL 的域名都在白名单内 |
| `cookies` | 固定 `false` |
| `filesystem` | 固定 `false`。声明为 `true` 直接拒绝加载 |
| `script` | 固定 `false`。声明为 `true` 直接拒绝加载 |

用户安装第三方书源时可以看到权限声明。

---

## 9. 校验流程

```
YAML
 ↓ 读取
原始 dict
 ↓ Pydantic 结构校验（字段 / 类型 / 版本 / 能力一致性 / 权限）
SourceSpec
 ↓ 语义校验（选择器可编译 / 模板变量已声明 / 域名白名单 / clean 覆盖）
LintReport
 ↓
Compiled Source
```

### 9.1 Linter 输出要求

错误信息必须包含：**位置 + 字段路径 + 原因 + 解决建议**。

```
[ERROR] search.result.fields: 搜索结果缺少必需字段 'url'
    → 补充 search.result.fields.url

[WARNING] content.clean.remove: 未移除常见的 script 节点
    → 在 content.clean.remove 中加入 'script'

[ERROR] search.request.url: 未定义的模板变量: {{nope}}
    → 可用变量: chapter.id, chapter.index, chapter.url, keyword, page, ...
```

诊断分级：

| 级别 | 含义 | 是否阻断 |
|------|------|---------|
| `ERROR` | 书源不可用 | 是 |
| `WARNING` | 可能存在问题，但可运行 | 否 |
| `INFO` | 提示性信息 | 否 |

CLI 输出 `Result: READY`（无 ERROR）或 `Result: BROKEN`。

---

## 10. 版本兼容

```yaml
spec_version: 1
engine_min_version: 0.1.0
engine_max_version: "1.0.0"
```

Core 加载书源时依次检查：

1. **Spec 版本**：`spec_version` 必须等于引擎支持的版本
2. **引擎兼容性**：引擎版本必须落在 `[engine_min_version, engine_max_version)` 区间

任一不满足抛 `SourceUnsupportedError`，**不静默降级解析**。

> 这是 §53 的核心意图：防止新版书源被旧 Core 静默错误解析，
> 产生难以诊断的提取失败。

---

## 11. 分发格式

### 11.1 v1（当前）

裸 `.yaml` 文件。用户直接放置或通过 Registry 安装。

### 11.2 规划中（`.mgs`）

```
my-source-1.0.0.mgs   (ZIP)
├── manifest.yaml
├── source.yaml
├── README.md
└── assets/
```

`.mgs` 尚未实现。第一阶段仅支持裸 `.yaml`。

---

## 12. 完整示例

见 `sources/official/example/source.yaml`，该示例：

- 演示全部四种能力
- 演示条件化 `url_join`
- 演示 `clean.remove`
- 附带 fixture（`fixtures/*.html`）供离线测试

验证：

```bash
uv run mog source lint sources/official/example/source.yaml
uv run pytest tests/source -v
```

---

## 13. 变更政策

| 变更类型 | 处理方式 |
|---------|---------|
| 新增可选字段 | 保持 `spec_version: 1`，minor 版本记录 |
| 新增算子 / 能力 | 保持 `spec_version: 1`，需 Linter 兼容旧书源 |
| 修改已有字段语义 | **必须**提升 `spec_version` |
| 删除字段 | **必须**提升 `spec_version` |

`spec_version` 提升后，引擎需同时支持 N 与 N-1 至少一个 minor 周期。
