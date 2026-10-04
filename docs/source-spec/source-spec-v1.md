# MoGrab Source Specification v1

> 状态：已冻结
> 版本：`spec_version: 1`
> 生效日期：2026-10-04
> 对应[原始规划书](../planning/项目规划书.md)（历史存档，非规范）：§3.2、§3.3、§7–§13、§41、§53
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
| `repository` | str | 否 | **书源自身**的发布地址（仓库 / 发布页）。见 §2.3 |
| `description` | str | 否 | 用途说明 |
| `license` | str | 否 | 书源自身的许可证标识（SPDX） |
| `authors` | list[str] | 否 | 作者列表 |
| `engine_min_version` | str | 否 | 所需最低引擎版本 |
| `engine_max_version` | str | 否 | 兼容的最高引擎版本（不含） |
| `capabilities` | list[str] | 是 | 声明的能力列表 |
| `network` | object | 否 | 网络策略（Core 解释，非书源逻辑） |
| `permissions` | object | 否 | 权限声明 |
| `transforms` | list | 否 | 全局变换，作用于所有能力的提取结果 |

> **`spec_version` 与 `version` 是两个不同的字段**，这是对原始规划书 §7 / §13 / §53
> 中 `version` 语义冲突的修正。详见 `docs/architecture/decisions/ADR-0002`。

### 2.2 未知字段处理

**严格模式**：任何未在规范中定义的字段都会导致校验失败。

理由：书源由社区贡献，拼写错误（如 `capabilites`）若被静默忽略，
会造成「书源看起来正常但某能力不生效」的隐蔽故障。

### 2.3 `homepage` 与 `repository` 的区别

两个都是 URL，但指向完全不同的东西，别写混：

| 字段 | 指向 | 例子 |
|------|------|------|
| `homepage` | **被采集的站点** | `https://www.example-novels.com` |
| `repository` | **书源自身的发布地址** | `https://github.com/me/mograb-sources` |

**MoGrab 不做远端版本检查，也不会自动下载更新。** 那需要一整套分发协议
（Registry、版本协商、签名校验），目前不在范围内。

`repository` 的作用是**给用户一个更新入口**：`mog source show` 会显示它，
并提示「需要新版就去这里取，重新 install 即可覆盖」。不填就什么都不显示 ——
对只在本地用、不分发的书源，留空即可。

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

注意：原始规划书 §9 的表述「而不是 `source.search()`」易被误读为「禁止调用方法」。
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
  paginate:                   # 可选，见 §5.4
    next: ".pager a@href"
    max_pages: 30
```

**逐项下钻语义**：`fields` 中的规则作用于**列表项内部**，而非整个文档。
因此 `a@href` 取的是「该项内的第一个 `<a>` 的 href」。

#### `list` 支持 JSONPath

`result.list` 与 `fields` 都按 §5.1 的统一语法解析，所以 JSON API 直接可用：

```yaml
search:
  request:
    url: https://api.example.com/search
    query: {keyword: "{{keyword}}"}
  response:
    format: json
  result:
    list: "jsonpath:$.data.list[*]"
    fields:
      title: "jsonpath:$.title"
      url: "jsonpath:$.id"
```

`list` 的 JSONPath 匹配到**数组**时会按元素展开，因此 `$.data.list` 和
`$.data.list[*]` 两种写法等价 —— 前者更贴近「取列表」的直觉，后者更显式。

下钻语义对 JSON 同样成立：`fields` 里的 `jsonpath:$.title` 取的是
「该项的 title」，不是整份响应的。

`reverse: true` 用于目录倒序的站点（最新章节在前），引擎会在提取后统一反转为顺序。
**声明了 `paginate` 时，反转发生在所有页面抓完之后**，而不是逐页反转。

### 5.3 未匹配时的行为

**不抛异常**。未匹配返回空值，由上层决定处理方式：

- `search` / `chapters`：缺少 `title` 或 `url` 的条目被**跳过**（不中断整批）
- `book`：缺少 `title` 视为致命错误（`SourceExecutionError`）
- `content`：`body` 未匹配视为致命错误

理由：列表页常有个别畸形条目，不应因一条坏数据导致整本书无法下载；
但详情页/正文页的关键字段缺失说明规则已失效，必须显式报错。

### 5.4 分页（`result.paginate`）

站点把长目录切成多页是常态（100 章一页的书站很常见）。
不声明 `paginate` 时只抓第一页 —— 这一点必须显式声明，因为没有通用的
「翻页规律」可以自动推断。

```yaml
result:
  list: ".list_item"
  fields: {title: ".t", url: "a@href"}
  paginate:
    next: ".seo_page a@href"   # 指向「下一页」的提取规则
    max_pages: 30              # 上限，默认 20
```

**只支持「跟着下一页链接走」这一种方式。** 站点的分页 URL 形态各异
（`?page=2` / `/list_2.html` / 带 token 的路径），靠猜规律很容易在某次改版后
静默失效。让页面自己告诉我们下一页在哪，是最稳的做法。

**终止条件**（满足任一即停）：

| 条件 | 说明 |
|------|------|
| `next` 取不到值 | 站点表达「没有下一页」的自然方式就是链接消失 |
| 下一页地址已经抓过 | 防止站点把链接永远指回自己造成死循环 |
| 到达 `max_pages` | 安全上限 |

**到达 `max_pages` 会记一条 WARNING。** 这是刻意的：静默截断会让用户
以为整本书下完了。看到这条日志就该把 `max_pages` 调大。

**`next` 提取出的链接必须是自包含的完整地址。** 引擎按原样使用它，
**不会**再把首页的 `query` 合并进去 —— 「下一页」链接本来就是站点对该页的
完整表述，再叠一次首页参数会出现 `page=1&page=2` 这种重复。

相对地址会按 RFC 3986 相对当前页解析，所以 `?page=2`、`/list_2.html`
这类写法都能用。

### 5.5 约定字段名

`fields` 的键名不是随便起的 —— 下面这些有特殊含义，会被引擎映射到领域对象上；
**其余键一律进 `extra`**（最终落到 `Book.metadata` / `SearchResult.extra`）。

| 能力 | 约定字段 | 映射到 |
|------|---------|--------|
| `book` | `id` | `Book.source_book_id`（缺省时用规范化后的 URL 兜底） |
| `book` | `title` | `Book.title`（**必需**，缺失即致命错误） |
| `book` | `author` / `intro` / `cover` | 同名字段 |
| `book` | `latest_chapter` | `Book.latest_chapter` |
| `book` | `status` | `Book.status`，见下 |
| `search` | `title` / `url` | 结果条目的必需字段 |
| `search` | `author` / `cover` / `intro` | 同名字段 |

#### `status` 的取值

`status` 会被 :meth:`BookStatus.parse` 映射成 `ongoing` / `completed` / `unknown`。
它接受规范值和常见同义写法（`连载中` / `已完结` / `完本` / `finished` …），
**认不出来一律降级为 `unknown`** —— 状态是锦上添花的元数据，
不该因为它让整本书登记失败。

> **`"0"` / `"1"` 不被接受。** 这两个值的含义每个站点都不一样，
> 引擎没有依据去猜。书源该用**锚定整值**的 `regex_replace` 自己转：

```yaml
book:
  fields:
    status: 'regex:state:"(\d+)"'
  transform:
    # `^1$` 只匹配「整个值恰好是 1」的字段，也就是只有 status。
    # 这是在用能力级 transform 模拟字段级 —— 见 §6.4。
    - regex_replace: {pattern: "^1$", replacement: "completed"}
    - regex_replace: {pattern: "^0$", replacement: "ongoing"}
```

把转换规则写在书源里而不是引擎里是有意的：它跟着书源一起被审阅和版本化。

---

## 6. 变换（Transformer）

### 6.1 算子清单（v1）

| 算子 | 参数 | 说明 |
|------|------|------|
| `trim` | — | 去首尾空白 |
| `normalize_whitespace` | — | 连续空白折叠为单空格（**含换行**） |
| `remove_html` | — | 去 HTML 标签并反转义实体，**保留块级换行**（见下） |
| `replace` | `pattern`, `replacement` | 字面替换 |
| `regex_replace` | `pattern`, `replacement` | 正则替换 |
| `prepend` | `value` | 前缀 |
| `append` | `value` | 后缀 |
| `url_join` | — | 相对 URL 转绝对（需 `base_url` 上下文） |
| `default` | `value` | 值为空时的兜底 |
| `join` | `separator` | 列表合并（列表上下文） |

#### `remove_html` 的换行语义（重要）

中文小说站的正文普遍写成 ``第一段<br><br>第二段<br><br>…``，而不是用 ``<p>``。
如果只是把标签删掉，整章会变成一整行 —— 所以 `remove_html` 会**先把换行边界
换成 `\n`，再删标签**：

| 标签 | 处理 |
|------|------|
| `<br>` / `<br/>` / `<br />` | → `\n` |
| `</p>` `</div>` `</li>` `</tr>` `</h1>`–`</h6>` `</blockquote>` `</section>` `</article>` | → `\n` |
| `<b>` `<span>` 等行内标签 | 直接删除，不断行 |

**别在 `remove_html` 后面接 `normalize_whitespace`** —— 后者会把换行一起折叠掉，
等于白做。要折叠行内空白的话，正文清洗阶段（§7）已经处理了。

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
- **伪缩进空格归一化**：不间断空格（U+00A0）与全角空格（U+3000）转成普通空格
- **逐行去掉首尾空白**
- 常见水印行（`请记住本站`、`本章未完`、`上一章`/`下一章` 等导航行）
- 裸域名行
- 连续空行压缩

### 7.1 关于伪缩进

站点想让段落看起来缩进两格，又不能用真空格（HTML 会折叠），于是塞一串
`&nbsp;`。反转义之后就是 U+00A0 字符 —— 它**不在**「零宽字符」的范围内
（它是可见字符），所以单独处理。

归一化成普通空格而不是直接删掉：万一它出现在词中间，删掉会把两个词粘一起。

**行首空白一律去掉。** 网页正文的行首空白几乎总是伪缩进，属于排版而非内容。
留着它，导出的 TXT 里每段前面就是几个来路不明的空格；段落缩进该由导出层
统一决定，而不是沿用各站点各自的土办法。

---

## 8. 网络策略与权限

### 8.1 `network`

```yaml
network:
  concurrency: 2              # 单源并发上限（1–32）
  request_interval_ms: 500    # 最小请求间隔（礼貌抓取）
  timeout_ms: 15000
  retry: 3                    # 最大重试次数（0–10）
  headers: {}                 # 来源级默认请求头，支持模板变量
```

**按书源隔离**：每个书源持有独立的限流器，多个来源不共用全局限制器。
实际并发 = `min(全局并发, 本源并发)`。

**`headers` 与 `request.headers` 的分工**：两处都能写请求头，越具体的优先级越高。
UA / Referer 这类对整站通用的放 `network.headers`；只在某个端点需要的放
`request.headers`。同名时 `request.headers` 覆盖 `network.headers`。

**`retry` 只覆盖次数，不改退避曲线。** 退避算法是全局配置 —— 书源不该管这个。

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

> 这么定的意图：防止新版书源被旧 Core 静默错误解析，
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

## 12. 完整示例与离线测试

见 `tests/fixtures/example-source/`，该示例：

- 演示全部四种能力
- 演示条件化 `url_join`
- 演示 `clean.remove`
- 附带 fixture（`fixtures/*.html`）与用例清单（`fixtures/cases.yaml`）

### 12.1 验证

```bash
uv run mog source lint tests/fixtures/example-source/source.yaml
uv run mog source test tests/fixtures/example-source
uv run pytest tests/source -v
```

`mog source test` 比 `lint` 多查一层：**提取结果是否为空**。

选择器写错时 lint 是发现不了的 —— 规则照样能编译，只是匹配不到东西。
站点改版最常见的失效方式正是这个，所以必须真跑一遍提取。

### 12.2 `fixtures/cases.yaml`

用例清单声明「每个能力用什么 URL 触发、喂哪些快照」：

```yaml
- capability: book
  url: https://example.com/book/1001
  files: [book.html]

- capability: chapters
  url: https://example.com/book/1001
  # 目录分页时按**请求顺序**依次提供
  files: [book.html, book-page2.html]

- capability: search
  url: https://example.com/search
  keyword: 三体
  files: [search.html]
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `capability` | 是 | `search` / `book` / `chapters` / `content` |
| `url` | 是 | 触发该能力的 URL |
| `files` | 是 | 快照文件名，相对 `fixtures/`；按请求顺序排列 |
| `keyword` | 否 | `search` 用的关键词，默认 `test` |

**为什么要显式写 `url`**：`chapters` 的目录常常就在书籍页上
（请求 URL 是 `{{book.url}}`），从文件名猜不出来。而且 `url_join` 需要真实的
base URL 才能验出「相对地址有没有被补全」。

**为什么 `files` 是列表**：分页书源会连着发多个请求，快照得按顺序喂进去。

### 12.3 `mog source test` 只接受路径

快照是**开发期产物**，`mog source install` 只复制 `source.yaml`，
不会把 `fixtures/` 带进数据目录 —— 否则每个已安装书源都拖着一份
会随版本变旧的测试数据。所以测试要在开发目录里跑：

```bash
cd my-source && mog source test .
```

（规划书 §51 写的是 `mog source test example`，传 ID。这里裁决为统一成路径，
传 ID 时会给出明确指引而不是去找一份不存在的快照。）

---

## 13. 变更政策

| 变更类型 | 处理方式 |
|---------|---------|
| 新增可选字段 | 保持 `spec_version: 1`，minor 版本记录 |
| 新增算子 / 能力 | 保持 `spec_version: 1`，需 Linter 兼容旧书源 |
| 修改已有字段语义 | **必须**提升 `spec_version` |
| 删除字段 | **必须**提升 `spec_version` |

`spec_version` 提升后，引擎需同时支持 N 与 N-1 至少一个 minor 周期。

### 13.1 本规范内的演进记录

| 变更 | 类型 | 说明 |
|------|------|------|
| `result.paginate` | 新增可选字段 | 保持 `spec_version: 1`。为 None 时行为与之前完全一致 |
| `remove_html` 保留块级换行 | 修正既有字段语义 | 见下 |

**`remove_html` 的这次改动严格来说改了语义**（以前 `<br>` 会被删掉，现在变成换行），
按上表本该提升 `spec_version`。没有提升的理由：

1. 旧行为是**错的** —— 它把 ``<br>`` 分段的正文压成一整行，任何依赖这个行为的
   书源本来就没法用；
2. 实际影响范围是「用了 `remove_html` 且内容含 `<br>`」的书源，这类书源
   此前都在用 `regex_replace` 自己补一遍，改动后那些补偿规则会变成无害的
   重复操作（`<br>` 已经不在字符串里了）；
3. 提升 `spec_version` 会让所有现存书源立刻失效，代价远大于收益。

这条决定记在这里备查。若后续再发现类似情况，应当优先考虑提升版本而非再次例外。
