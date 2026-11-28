# 写书源从入门到实战教程

> 本教程面向想为自己常看的网站编写 MoGrab 书源的读者，配合已冻结规范 [Source Specification v1](source-spec-v1.md) 与官方参考示例 [example-source](../../tests/fixtures/example-source/README.md) 使用。

---

## 0. 在开始前先搞懂 MoGrab 书源是怎么工作的

很多小说工具的书源实质上是在配置文件里写 JS / BeanShell 脚本；而 **MoGrab 书源是一份纯粹的声明式 YAML（或 JSON）配置**，不允许执行任何第三方代码。

书源**只描述 4 件事**：

```text
请求什么（request） → 返回什么格式（response） → 怎么提取（fields / list / body） → 怎么清洗变换（clean / transform）
```

以下 6 件事全部由 **MoGrab Core** 自动接管，书源里不需要、也不能写：

- **并发控制与限流**：只需声明单源 `concurrency` 与 `request_interval_ms`，Core 自动配好令牌桶限流与 `min(全局并发, 单源并发)`。
- **失败重试与退避**：只需声明 `retry` 次数，指数退避 + 抖动由网络层统一处理。
- **HTTP 缓存与断点续传**：章节目录、书籍页响应按 URL+Query 缓存，中断后重跑按三路标识增量跳过已下载章节。
- **HTML 编码探测**：自动识别 HTTP `Content-Type` 与 `<meta charset>`，并把 `gb2312` / `gbk` 自动提升为 `gb18030` 解码生僻字。
- **通用正文去噪**：零宽字符、伪缩进（`&nbsp;` / 全角空格）、行首空白、`请记住本站` 等常见水印行会自动清洗。
- **持久化与导出**：入库 SQLite WAL、下载封面、TXT / Markdown / EPUB3 生成全由 Core 完成。

### 运行一次完整抓取的数据流

```text
1. 搜索       search.request   ──▶ 提取 title / author / url / cover / intro ──▶ url_join 补全相对链接
2. 详情       book.request     ──▶ 用 {{book.url}} 请求详情页 ──▶ 提取 title(必填) / author / intro / cover / status
3. 章节目录   chapters.request ──▶ 抓取目录（支持 paginate 翻页与 reverse 倒序修正）──▶ 产出有序章节列表
4. 章节正文   content.request  ──▶ 遍历章节 {{chapter.url}} ──▶ clean.remove 删节点 ──▶ body 取 HTML ──▶ remove_html 转纯文本
```

> 仓库约定：**主仓库不收录针对任何真实站点的书源**。请在仓库根目录下的 `sources/`（已在 `.gitignore` 中排除）或任意独立目录编写和保存你自己的书源。

---

## 1. 第一步：生成书源脚手架（`mog source init`）

MoGrab CLI 自带脚手架生成、静态检查、离线快照测试与在线体检工具链。先用一行命令生成标准目录：

```bash
mog source init my_site --dir sources
```

命令执行后会在 `sources/my_site/` 下生成 3 个文件：

```text
sources/my_site/
├── source.yaml              # 书源规则主文件
└── fixtures/
    ├── cases.yaml           # 离线测试用例清单（供 mog source test 读取）
    └── search.html          # 示例 HTML 快照
```

### 命名与顶层必填字段规范

1. **`id`**：必须匹配正则 `^[a-z][a-z0-9]*([-_][a-z0-9]+)*$`（小写字母开头，可含小写字母、数字、单 `-` 或 `_`，不能大写或连续分隔符）。
2. **`spec_version`**：固定写整数 `1`（表示遵循 Source Spec v1，并非书源自己的版本号）。
3. **`version`**：遵循 SemVer 2.0.0（如 `0.1.0`、`1.0.0`），代表你这个书源本身的修订版本。
4. **`capabilities`**：声明支持的能力列表（`search`、`book`、`chapters`、`content` 四选多），**强制一致性约束**：
   - `capabilities` 里列出的能力，下面必须写出对应的配置块；
   - 下面写了某个配置块，`capabilities` 里也必须包含它，否则校验直接报错。
5. **严格禁止未知字段**：书源模型开启了 `deny_unknown_fields`。把 `capabilities` 拼错成 `capabilites` 等问题会在加载阶段立刻暴露，不会静默失效。

---

## 2. 第二步：用浏览器抓包并准备离线快照

对着线上网站直接试错往往被限流或难定位选择器，推荐先用浏览器 **F12 开发者工具**把目标站点的 4 个典型页面抓到本地 `fixtures/`：

1. **找搜索接口（`search`）**：打开站点搜索一本书，看 `Network` 面板（注意看是普通 HTML 页还是 XHR/Fetch 返回的 JSON）：
   - 记录请求方法（`GET` / `POST`）、完整 URL、参数名（例如 `?keyword=三体&page=1`）。
2. **找详情页与目录页（`book` / `chapters`）**：打开某本书主页：
   - 如果章节目录和书籍信息在同一个 HTML 上，只需要保存一份 `book.html`；
   - 如果目录在独立页面（如 `/book/1001/catalog.html`）或分成第 1 页/第 2 页，分别保存 `chapters-1.html`、`chapters-2.html`。
   - 检查章节列表是不是倒序（最新章节在最上面）—— 如果是，后面在 `chapters.result` 里设 `reverse: true`。
3. **找正文页（`content`）**：打开任意一章，确认：
   - 正文容器选择器（常见 `#content`、`.read-content`、`#chaptercontent`）；
   - 容器里面有哪些广告、章节导航按钮、`script`、`style` 等无关节点（用于填进 `clean.remove`）。
4. **看清网页编码与封面域名**：
   - 查看响应头 `Content-Type` 或 `<meta charset="...">`，确认是否为 UTF-8 或 GBK；
   - 右键复制封面图片地址，如果封面托管在单独的 CDN 域名（例如 `img.example.com`），一定要一起写进 `permissions.network`。

用 `curl` 把示例页面存进 `sources/my_site/fixtures/`（若站点是 GBK 编码，保存原始字节即可，不要用编辑器转码破坏原样）：

```bash
curl -sL "https://www.example.com/search?q=%E4%B8%89%E4%BD%93" -o sources/my_site/fixtures/search.html
curl -sL "https://www.example.com/book/1001/" -o sources/my_site/fixtures/book.html
curl -sL "https://www.example.com/book/1001/1.html" -o sources/my_site/fixtures/chapter.html
```

---

## 3. 第三步：逐块编写 `source.yaml`

下面按从上到下的顺序拆解一份完整 HTML 书源的每个字段，说明「为什么这么写」以及常见陷阱。

### 3.1 元信息、网络策略与权限白名单

```yaml
spec_version: 1
id: my_site
name: 示例小说站
version: 1.0.0
homepage: https://www.example.com          # 被抓取站点的首页
repository: null                           # 如果你公开发布此书源，可填仓库 URL 方便用户更新
description: 示例站 HTML 书源
license: GPL-3.0-only
authors:
  - YourName

engine_min_version: 1.0.0

capabilities: [search, book, chapters, content]

network:
  concurrency: 2                           # 单源并发上限 (1..=32)，建议保持 2
  request_interval_ms: 500                 # 请求最小间隔（毫秒），礼貌抓取
  timeout_ms: 15000
  retry: 3                                 # 失败重试次数 (0..=10)
  headers:
    User-Agent: "{{user_agent}}"           # 由引擎统一注入，不要硬编码死 UA

permissions:
  network:
    - www.example.com                      # 主站域名
    - cdn.example.com                      # 如果封面在 CDN 上，必须列出来！
  cookies: false
  filesystem: false                        # v1 必须为 false
  script: false                            # v1 必须为 false
```

> **重要提醒**：`permissions.network` 同样约束封面下载与所有请求地址。如果 `cover` 返回 `https://cdn.example.com/1.jpg` 但白名单里漏了 `cdn.example.com`，`mog source lint` 或运行时下载封面就会报白名单拦截。若需要允许所有子域名，可写 `*.example.com`。

### 3.2 `search`：搜索能力

```yaml
search:
  request:
    method: GET
    url: "https://www.example.com/search"
    query:
      q: "{{keyword}}"
      page: "{{page}}"
  response:
    format: html                           # html | json，默认 html
  result:
    list: ".book-item"                     # 定位每一条搜索结果的外层容器
    fields:
      title: ".title@text"                 # 必需：缺了这一条结果会被跳过
      url: "a@href"                        # 必需：缺了这一条结果会被跳过
      author: ".author@text"               # 可选
      cover: "img@src"                     # 可选
      intro: ".intro@text"                 # 可选
  transform:
    - trim
    - normalize_whitespace
    - url_join                             # 自动把 /book/1001 补全为 https://www.example.com/book/1001
```

**关键语义**：`result.fields` 采取**逐项下钻**模式——`.title`、`a@href` 都是在每一个 `.book-item` 节点**内部**匹配，而不是整页匹配。

### 3.3 `book`：书籍详情

```yaml
book:
  request:
    method: GET
    url: "{{book.url}}"
  fields:
    id: "regex:/book/(\\d+)"               # 可选：建议显式提取站内书号；未填时自动用规范化后的 URL 兜底
    title: "h1.book-title@text"            # 必需：缺失时直接视为致命错误
    author: ".book-author@text"
    intro: ".book-intro@text"
    cover: ".book-cover img@src"
    latest_chapter: ".latest-chapter@text"
    status: ".book-status@text"
  transform:
    - trim
    - normalize_whitespace
    - url_join
```

#### 如果站点状态或作者带前缀怎么办？

- **带前缀**（如 `作者：唐家三少`、`最新：第100章`）：在 `book.transform` 里用锚定正则 `regex_replace` 清理：

  ```yaml
  transform:
    - trim
    - regex_replace: { pattern: "^作者[：:]\\s*", replacement: "" }
    - normalize_whitespace
    - url_join
  ```

- **数字状态码**（如 `status` 提取出 `"0"` / `"1"`）：引擎内部认识 `连载中`、`已完结`、`完本`、`ongoing`、`completed` 等常见中文与英文词，**但不会猜测 `"0"` / `"1"` 的含义**。请在 `book.transform` 中用精确锚定正则 `^1$` / `^0$` 自己转换：

  ```yaml
  transform:
    - regex_replace: { pattern: "^1$", replacement: "completed" }
    - regex_replace: { pattern: "^0$", replacement: "ongoing" }
  ```

### 3.4 `chapters`：章节目录

```yaml
chapters:
  request:
    method: GET
    url: "{{book.url}}"                    # 如果目录在独立页，可在 url 写独立页规则
  result:
    list: "#chapter-list li a"             # 可以直接定位到 <a> 本身
    fields:
      title: "@text"                       # 当前节点就是 <a> 时，用 @text / @href 直接取自身文本和属性
      url: "@href"
      id: "@data-cid"                      # 可选：站内章节 ID，用于增量更新更稳健的三路 diff
    reverse: false                         # 若网站把最新章节排在最上面，改为 true
  transform:
    - trim
    - url_join
```

### 3.5 `content`：章节正文（最容易踩坑的地方）

```yaml
content:
  request:
    method: GET
    url: "{{chapter.url}}"
  body: "#content@html"                    # 【坑 1】必须写 @html！千万别写成 "#content"
  clean:
    remove:
      - "script"
      - "style"
      - ".advert"
      - ".chapter-nav"
  transform:
    - trim
    - remove_html                          # 【坑 2】remove_html 后面不要接 normalize_whitespace！
```

**写正文规则必记的 3 条铁律**：

1. **`body` 必须带 `@html`**：默认不写后缀时，CSS 提取器调用纯文本提取并压缩空白——所有 `<p>` 和 `<br>` 在那一步就已经消失了！后面即使写了 `remove_html` 也救不回来，导出的整章小说会粘成一大段。另外，如果写成字典格式 `{ selector: "#content@html" }` 也可，但**不要误写成 `{ selector: "#content", html: true }`**（`html` 键不存在，只读 `selector`）。
2. **`clean.remove` 发生在 `body` 提取之前**：它是 DOM 级删除，所以能精准删掉广告 `div`、`script`、`style` 与底部翻页栏；推荐**至少包含 `"script"`**（否则 `mog source lint` 会提示警告）。
3. **`content.transform` 中 `remove_html` 之后绝对不要接 `normalize_whitespace`**：`remove_html` 会贴心地把 `<br>`、`</p>`、`</div>` 转成换行 `\n` 后再删标签并反转义 HTML 实体；而 `normalize_whitespace` 会把所有 `\s+`（**包含 `\n`**）折叠成单个空格，让段落换行前功尽弃。行首伪缩进（`&nbsp;` / 全角空格）与多余空行会由 Core 内置正文清洗管线统一整理。

---

## 4. 进阶场景 Cookbook（直接拿来改）

### 场景 A：纯 JSON 接口书源（`response.format: json` + `jsonpath:`）

当站点搜索或目录是前后端分离的 JSON API 时：

```yaml
search:
  request:
    method: GET
    url: "https://api.example.com/v1/books/search"
    query:
      kw: "{{keyword}}"
      page: "{{page}}"
  response:
    format: json
  result:
    list: "jsonpath:$.data.items[*]"       # 也支持写 jsonpath:$.data.items
    fields:
      title: "jsonpath:$.bookName"
      author: "jsonpath:$.authorName"
      url: "jsonpath:$.bookId"             # 先取出纯 ID，例如 "10086"
  transform:
    - trim
    - regex_replace: { pattern: "^(\\d+)$", replacement: "https://api.example.com/v1/books/$1" }
```

> **JSON 下钻提示**：`list` 选中每个对象元素后，`fields` 里的 `jsonpath:$.bookName` 针对的是**单个元素自身**，而不是整份 JSON 根对象。若接口只返回纯数字 ID 而没有完整 URL，如上所示用**全锚定 `regex_replace`** `^(\d+)$` 将纯数字 ID 拼成详情 URL（注意锚定，以免误伤含中文或非数字的 `title` / `author`）。

### 场景 B：POST 请求书源（表单提交 / JSON 请求体）

很多站点搜索接口要求 `POST` 请求：

- **方式 1：JSON Payload（传入 Map）**：

  ```yaml
  search:
    request:
      method: POST
      url: "https://www.example.com/api/search"
      headers:
        Content-Type: "application/json"
      body:
        keyword: "{{keyword}}"
        page: "{{page}}"
    response:
      format: html
    result:
      list: ".item"
      fields:
        title: ".name@text"
        url: "a@href"
  ```

- **方式 2：URL 编码表单（传入字符串）**：

  ```yaml
  search:
    request:
      method: POST
      url: "https://www.example.com/search.php"
      headers:
        Content-Type: "application/x-www-form-urlencoded"
      body: "searchkey={{keyword}}&searchtype=all"
    result:
      list: "table.grid tr"
      fields:
        title: "td:nth-child(1) a@text"
        url: "td:nth-child(1) a@href"
        author: "td:nth-child(3)@text"
    transform:
      - trim
      - url_join
  ```

### 场景 C：分页目录与倒序合并

很多网站每 100 章翻一页（甚至最新 100 章在首页还倒序）。`result.paginate` 只采用「跟着下一页链接走」策略：

```yaml
chapters:
  request:
    method: GET
    url: "{{book.url}}"
  result:
    list: ".chapter-list a"
    fields:
      title: "@text"
      url: "@href"
    reverse: true                          # 全部页面抓完后再统一反转！
    paginate:
      next: ".pagination a.next@href"      # 下一页链接为空、已访问过或达 max_pages 即停止
      max_pages: 50                        # 默认 20，超过此数会打 WARNING 日志提示调大
  transform:
    - trim
    - url_join
```

对应的 `fixtures/cases.yaml` 需按**请求顺序**提供每一页的快照：

```yaml
- capability: chapters
  url: "https://www.example.com/book/1001/"
  files:
    - chapters-page1.html
    - chapters-page2.html
```

### 场景 D：GBK / GB2312 老站点与 XPath / 正则 / `@own_text`

1. **编码问题**：老式笔趣阁站点常声明 `<meta charset="gbk">` 或 `gb2312`。引擎会自动探测并统一提升到 `gb18030` 解码。如果网页响应头没写 charset、HTML 里也没有 `<meta>`，导致中文乱码，只需在对应能力下显式指定：

   ```yaml
   request:
     method: GET
     url: "{{chapter.url}}"
     encoding: "gb18030"
   ```

2. **`@own_text` 去掉子标签干扰**：如果 HTML 是 `<h1 class="title">书名<span>完本</span></h1>`，写 `h1.title@text` 会取成 `书名完本`；改写 `h1.title@own_text` 只提取 `书名`。

3. **XPath 与正则提取器**：

   ```yaml
   fields:
     author: "xpath://meta[@property='og:novel:author']/@content"
     id: "regex:bookid\\s*=\\s*(\\d+)"     # 取第 1 捕获组；若无括号则取整个匹配
   ```

### 场景 E：广告文本替换与 `default` 兜底

若广告文字不是独立标签（没有 `class` / `id` 供 `clean.remove` 删除），而是混在正文文字里的固定文本，可在 `content.transform` 中配合 `replace` / `regex_replace`：

```yaml
content:
  request:
    method: GET
    url: "{{chapter.url}}"
  body: "#content@html"
  clean:
    remove: ["script", "style", ".ads"]
  transform:
    - trim
    - remove_html
    - replace:
        pattern: "本章未完，点击下一页继续阅读"
        replacement: ""
    - regex_replace:
        pattern: "(?m)^手机用户请浏览阅读.*$"
        replacement: ""
```

> 若某字段允许缺省兜底（例如作者缺失），可在能力级 `transform` 中加入 `- default: "佚名"`——注意和 `url_join` 一样，能力级 `transform` 对该能力的所有字段生效，不要让必填字段或 URL 字段被 `default` 误填。

---

## 5. 第四步：校验、离线测试、安装与上线（完整闭环）

写好 `source.yaml` 和 `fixtures/` 后，按下面 5 步验收：

### 5.1 编写 `fixtures/cases.yaml`

在 `sources/my_site/fixtures/cases.yaml` 中为每个声明的能力配置输入 URL 与快照列表：

```yaml
- capability: search
  url: "https://www.example.com/search?q=%E4%B8%89%E4%BD%93"
  keyword: 三体
  files: [search.html]

- capability: book
  url: "https://www.example.com/book/1001/"
  files: [book.html]

# 目录和详情共用同一页面时直接复用 book.html
- capability: chapters
  url: "https://www.example.com/book/1001/"
  files: [book.html]

- capability: content
  url: "https://www.example.com/book/1001/1.html"
  files: [chapter.html]
```

> **为什么 `cases.yaml` 一定要写 `url`？** 引擎要用它作为 `url_join` 的 `base_url`，才能验证 `/book/1001` 是否正确补全为完整地址；同时也用于匹配模板变量 `{{book.url}}`、`{{chapter.url}}`。

### 5.2 五步验证命令行

```bash
# 1. 静态检查（Schema + 选择器编译 + 模板变量 + 白名单 + clean 建议），无需联网
mog source lint sources/my_site

# 2. 离线快照提取测试（验证每个能力真正提取到非空内容），无需联网
mog source test sources/my_site

# 3. 安装到本地数据目录（覆盖已有旧版本加 --force）
mog source install sources/my_site --force

# 4. 在线体检（实际请求站点首页与搜索接口，更新健康状态为 healthy / degraded / broken）
mog source doctor my_site --live

# 5. 小范围实战联调
mog search -s my_site 三体
mog download --source my_site --url "https://www.example.com/book/1001/"
mog book                           # 复制输出的 book_id
mog book <book_id> --chapter 1     # 检查正文换行与清洁度是否理想
mog export --format epub <book_id> # 检验 EPUB 封面与章节输出
```

**也可以在桌面端直接安装**：打开 MoGrab Desktop → 左侧「书源」→ 展开「+ 安装 / 更新书源」→ 直接粘贴 `source.yaml` 全文或填写本机 `source.yaml` 路径 → 点击「校验并安装」→ 点击书源卡片上的「体检」即可。

---

## 6. 常见问题与排错速查（Troubleshooting）

| 现象 / 报错 | 原因 | 解决办法 |
|------------|------|---------|
| 导出小说每章全都粘成一整段，没有分段换行 | `content.body` 漏写了 `@html`，或在 `remove_html` 后面误加了 `normalize_whitespace` | 改成 `body: "#content@html"`，并从 `content.transform` 删除 `normalize_whitespace` |
| `unknown field ...` 加载报错 | 字段拼写错误，或写了规范未定义的扩展键 | 对照 [Source Spec v1](source-spec-v1.md) 核对拼写；不要写 `{selector: ..., html: true}` |
| `声明了能力 ... 但未提供 ... 规格` | `capabilities` 与下方的能力块不匹配 | 删去未实现的能力名，或补全对应配置块 |
| 封面没有下载进 EPUB，日志报域名未授权 | 封面图放在 CDN 域名上，但 `permissions.network` 只写了主站 | 把封面域名（或通配 `*.cdn.com`）加入 `permissions.network` |
| `mog source test` 报「引擎请求了第 2 个页面，但用例只给了 1 个快照」 | 启用了 `paginate`，`cases.yaml` 只给了 1 个文件 | 按请求顺序列齐每页快照，或调整测试快照中的下一页链接 |
| 长篇小说只下了一部分目录 | 站点目录分页超过了默认的 `max_pages: 20` | 查看日志是否有 `source.pagination_limit_reached` 警告，在 `paginate` 下调大 `max_pages` |
| 目录顺序反了（第 1000 章排在最前面） | 站点把最新章节展示在最顶部 | 在 `chapters.result` 下加 `reverse: true` |
| 标题或中文值被 `url_join` 拼成了 URL 或漏拼 URL | `url_join` 按保守规则判定（含 `/`、`./`、常见文件名后缀才拼） | 若是纯数字 ID 拼 URL，改用锚定正则 `regex_replace: { pattern: "^(\\d+)$", replacement: "https://.../book/$1" }` |
| `未定义的模板变量: {{foo}}` | 写了规范之外的变量或作用域不对（如在 `search` 用 `{{book.url}}`） | 只使用下表中的变量并核对可用范围 |
| 章节正文出现乱码字符（``） | 响应未声明编码且探测失败 | 在对应能力的 `request` 下显式加上 `encoding: gb18030` 或 `utf-8` |

---

## 7. 语法速查卡（Cheat Sheet）

### 7.1 提取器规则语法

| 写法 | 类型 | 说明 |
|------|------|------|
| `.title` / `h1.title` | CSS | 取匹配节点文本并归一化空白 |
| `a@href` | CSS + 属性 | 取匹配元素的指定属性值 |
| `@href` / `@data-id` | 当前节点属性 | `list` 已定位到目标元素时直接取其属性 |
| `@text` | 当前节点文本 | 等同默认行为，用于 `list` 直接指向文本元素时 |
| `@own_text` | 直接文本 | 仅取节点自身直属文本，忽略子标签内文本 |
| `#content@html` | CSS + HTML | 返回包含子节点的 innerHTML（写正文 `body` 必用） |
| `xpath://div[@id='main']` | XPath | 标准 XPath 表达式 |
| `jsonpath:$.data.list[*]` | JSONPath | 针对 `response.format: json` 响应 |
| `regex:第(\d+)章` | 正则表达式 | 有捕获组取第 1 组，无捕获组取全匹配 |

### 7.2 模板变量作用域

| 变量 | 可用能力 / 位置 | 说明 |
|------|----------------|------|
| `{{keyword}}` | `search` | 用户输入的搜索关键词 |
| `{{page}}` | `search` | 当前页码（默认从 `1` 开始） |
| `{{book.url}}` | `book` / `chapters` | 书籍详情页完整 URL |
| `{{book.id}}` | `book`（校验已知） | 来源站书籍 ID |
| `{{book.title}}` | `book`（校验已知） | 书名 |
| `{{chapter.url}}` | `content` | 章节页完整 URL |
| `{{chapter.index}}` | `content` | 章节从 0 起的内部序号 |
| `{{chapter.id}}` | `content`（校验已知） | 来源站章节 ID |
| `{{user_agent}}` | 全部 `request` | Core 统一注入的浏览器 UA |
| `{{config.<key>}}` | 全部 `request` | 用户配置文件中的键值 |

### 7.3 `transform` 算子一览

| 算子 | 写法示例 | 作用 |
|------|---------|------|
| `trim` | `- trim` | 去掉首尾空白 |
| `normalize_whitespace` | `- normalize_whitespace` | 将连续空白（**含换行**）折叠为单个空格；勿用于正文 `remove_html` 之后 |
| `remove_html` | `- remove_html` | 把 `<br>` 与常见块级闭合标签转 `\n`，删除标签并反转义 HTML 实体 |
| `replace` | `- replace: { pattern: "旧", replacement: "新" }` | 字面字符串替换 |
| `regex_replace` | `- regex_replace: { pattern: "^作者：", replacement: "" }` | 正则替换（使用 `$1` `$2` 引用捕获组） |
| `prepend` | `- prepend: "https://example.com"` | 在值前拼接前缀 |
| `append` | `- append: ".html"` | 在值后拼接后缀 |
| `url_join` | `- url_join` | 条件化将相对 URL 基于当前请求 `base_url` 解析为绝对地址 |
| `default` | `- default: "未知"` | 值为 `null` 或空串时填默认值 |
| `join` | `- join: ", "` | 列表拼接（保留算子） |

（全部字段边界与演进约束以 [Source Specification v1](source-spec-v1.md) 为准。）
