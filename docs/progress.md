# 项目进度

> 更新于 2026-10-05 · 当前版本 `1.0.0rc4`（预发布）
>
> **这份文档是进度的唯一出处。** README、CHANGELOG、架构总览里只放一句话摘要，
> 细节都看这里 —— 之前进度信息散在四个文件里，改一处忘三处。

## 一句话

核心链路已经跑通，而且**在真实站点上验证过**：`bqgnovels.com` 的书源取到完整
目录 1453 章，端到端下载 7 章 / 76,725 字，三种格式导出正常。
命令行、本地 API、桌面端三条路都通了；API 的所有业务端点都要求 Bearer 令牌；
本地全文搜索（`mog find` / `GET /api/v1/search/local`）两条路都有；
桌面端目前只做到最小闭环，书架、书源管理、设置还是占位页。

> **rc1 的发布包是坏的，rc2 修掉了。** 两个产物都打不开数据库
> （`ModuleNotFoundError: aiosqlite`），而三道关都没拦住 —— 因为都只验
> 「构建成功」，没人真执行过产物。现在构建会自跑冒烟测试。

## 质量指标

| 指标 | 当前 | 怎么刷新 |
|------|------|---------|
| 测试用例 | 713 | `uv run pytest --collect-only -q \| tail -1` |
| 覆盖率 | 85.7% | `uv run pytest --cov --cov-report=term` |
| 覆盖率门槛 | 70%（`fail_under`） | 见根 `pyproject.toml` |
| 源码行数 | 约 13,400（另有桌面端 TS 约 1,500 行） | `find packages apps/cli apps/api -name "*.py" -not -path "*/node_modules/*" \| xargs wc -l \| tail -1` |
| 测试行数 | 约 7,700 | `find tests packages -name "test_*.py" \| xargs wc -l \| tail -1` |
| 未实现桩 | 0 | `grep -rn NotImplementedError packages apps --include="*.py" \| grep -v node_modules` |
| 桌面端测试 | 14 | `cd apps/desktop && npm test` |
| CI | 全绿（8 个 job） | `gh run list` |

## 里程碑

对照[原始规划书](planning/项目规划书.md) §57 的版本规划。

| 版本 | 主题 | 状态 | 差什么 |
|------|------|------|-------|
| v0.1.0 | Core Prototype | **达成** | — |
| v0.2.0 | Task System | **达成** | 真实站点验证过 1453 章目录 |
| v0.3.0 | Source Ecosystem | **达成（有取舍）** | Registry / 回滚 / 远端更新已明确不做，改用 `repository` 字段 |
| v0.4.0 | API | **达成** | — |
| v0.5.0 | CLI | **达成** | 独立可执行包的跨机器验证 |
| v0.6.0 | Desktop | **进行中** | 书架 / 书源管理 / 设置三个页面 |
| v0.7.0 | EPUB / Polish | **部分** | 封面、元数据模板、性能优化 |
| v1.0.0 | Stable | **rc** | 真实站点验证、桌面端三个页面 |

### v0.1.0 逐项

规划书列的清单全部完成：

```
✓ Source Schema          ✓ SQLite
✓ YAML Loader            ✓ TXT Export
✓ HTTP Client            ✓ Book
✓ CSS Selector           ✓ Chapter
✓ Basic Search           ✓ Content
```

### v0.2.0 逐项

```
✓ Async Task             ✓ Cancel
✓ Worker Pool            ✓ Cache
✓ Retry                  ✓ Logging
✓ Pause                  ✓ Incremental Update
✓ Resume
```

### v0.3.0 逐项

目标：第三方开发者可以编写和维护 Source。

```
✓ Source Linter          ✓ Source Test（mog source test）
✓ Fixture Test           ✗ Registry（已明确不做，见下）
✓ Source Version         ✓ Install
✓ Update（覆盖式）        ✗ Rollback（已明确不做，见下）
```

**`mog source test` 已实现。** 用 `fixtures/cases.yaml` 声明「每个能力用哪个
快照」，逐能力真跑一遍提取。比 lint 多查一层：**提取结果是否为空** ——
选择器写错时 lint 发现不了，规则照样能编译，只是匹配不到东西，
而站点改版最常见的失效方式正是这个。

只接受路径不接受 ID：快照是开发期产物，安装时不复制到数据目录。
规划书 §51 写的是传 ID，这里裁决为统一成路径，传 ID 时给明确指引。

### 明确不做的三件事（2026-10-05 决定）

| 项 | 决定 | 理由 |
|----|------|------|
| 远端版本检查 / 下载 | **不做** | 需要一整套分发协议（Registry、版本协商、签名校验），是个独立课题 |
| 版本回滚 | **不做** | 要改磁盘布局保留多版本定义，收益不抵复杂度 |
| 升级失败保留旧版本 | **不做** | 同上 |

**替代方案：`repository` 字段。** `SourceSpec` 新增可选的 `repository`
（书源自身的发布地址），`mog source show` 会显示它并提示「需要新版就去这里取，
重新 install 即可覆盖」。更新入口交给用户，不做自动化。

**同时修掉了一处误导。** 原先 `mog source show` 会打印「可回滚到 1.0.0」——
但 `rollback` 命令不存在，旧版本定义文件也被直接覆盖（磁盘上只有单个
`source.yaml`，规划书 §56 要的 `1.2.0/` `1.1.0/` `current` 目录结构不存在）。
那句话给了错误的安全感。现在改成中性的「版本变更 1.0.0 → 1.0.1」，
`previous_version` 降级为纯诊断字段。

**Registry 仍然空着。** 它和「远端版本检查/下载」是同一件事的两面 ——
既然后者明确不做，Registry 也就没有存在的基础。全仓库目前零实现。

### v0.4.0 逐项

```
✓ FastAPI                ✓ API Error Model
✓ /api/v1                ✓ OpenAPI
✓ SSE                    ✓ 认证（Bearer token）
```

## 各模块完成度

`packages/mograb/` 下九个模块：

| 模块 | 状态 | 说明 |
|------|------|------|
| `domain` | 完成 | 领域模型 + 枚举 + ULID |
| `source` | 完成 | 加载、校验、提取、变换、执行 |
| `network` | 完成 | 客户端、缓存、限流、重试 |
| `task` | 完成 | 队列、Worker、调度、生命周期 |
| `storage` | 完成 | 8 张表、7 个仓储 |
| `content` | 完成 | 清洗、规范化、校验 |
| `export` | 完成 | TXT / Markdown / EPUB |
| `config` | 完成 | 路径、设置 |
| `logging` | 完成 | 结构化日志 + 脱敏 |

应用层：

| 应用 | 状态 | 说明 |
|------|------|------|
| `apps/cli` | 完成 | 11 组命令 |
| `apps/api` | 完成 | 22 个端点 + SSE，全部要求 Bearer 令牌 |
| `apps/desktop` | 最小闭环 | 搜索 → 下载 → 任务进度可用；书架 / 书源 / 设置是占位 |

## 已知缺口

按影响排。

### 高

**桌面端只做了最小闭环。** 搜索、下载、任务进度能用，书架 / 书源管理 / 设置
还是占位页。先跑通闭环是为了验证「Electron + 本地 API + SSE」这套架构真的成立 ——
现在验证过了，剩下的是照着补页面。

### 中

**真实站点只验证过两个，而且都是简单类型。** `bqgnovels.com` 的书源跑通了：

| 验证 | 规模 | 结果 |
|------|------|------|
| 目录抓取 | 1453 章 / 15 页 | 分页正确 |
| 全量下载 | 2036 章 / 451 万字 | **0 失败**，35 分钟 |
| EPUB 导出 | 2037 个 xhtml / 8.7 MB | 结构合规，正文无残留 |

但那是 Nuxt SSR 站点、内容直出 HTML，属于**最简单的一类**。
还没遇到过的：需要 JS 渲染的、有真实反爬的、用 GBK 编码的、
目录分页方式不是「下一页链接」的。书源分页目前只支持「跟着下一页链接走」，
遇到靠页码规律翻页的站点还需要扩展。

**站点是抖的，长下载必然遇到重试。** 那次 2036 章的下载里，
`http.retry` 警告出现了 8 次（全部重试成功，最终 0 失败）。
这不算缺陷，但意味着**重试是常态而不是异常** —— 相关的输出、日志级别、
以及「重试期间进度条要正常」都得按常态对待。

**Source Registry 没实现 —— 这是明确的决定，不是遗漏。** 书源分发只有本地安装
（`mog source install <file>`）能用。原始规划书 §13、§55、§56 描述的远端流程
（检查版本 / 下载 / 回滚）与 Registry 是同一件事的两面，2026-10-05 决定都不做：
需要一整套分发协议（版本协商、签名校验），收益不抵复杂度。替代方案是
`repository` 字段 + 用户自行安装，见 v0.3.0 一节。

**打包漏动态导入的模块 —— 栽过两次。** rc1 的 CLI 和桌面端都是坏的
（SQLAlchemy 按字符串导入 `aiosqlite`，PyInstaller 静态分析看不见）；
rc3 又漏了 `shellingham.nt`（Typer 的补全探测按 `os.name` 动态导入平台实现），
`mog --install-completion` 直接崩。

表现都很欺骗：`--version`、`--help`、下载、导出全都正常，
只有碰到那条特定路径才炸。

现在有三道防线：

1. 构建完自动跑一遍产物（`scripts/build.py` 的 `smoke_test()`），
   CI 有独立的 `package-smoke` job，Release 工作流也会跑
2. 冒烟测试里有一类「**允许非零退出、但绝不能抛异常**」的探测 ——
   `--show-completion` 走的就是 shellingham 那条路。rc3 那版冒烟测试
   要求所有检查都退 0，所以**没拦住**；现在分开了
3. `tests/unit/test_build_script.py` 的 `TestHiddenImports` 逐个确认
   已知的动态导入目标都在 `HIDDEN_IMPORTS` 里

**「构建成功」不等于「产物能用」** 这条依然是这里最贵的教训。

**CLI 与 API 的能力要对齐 —— 两个方向都要查。** 已经各栽过三次：

- `mog find` 只有 CLI，API 没有对应端点（补了 `GET /api/v1/search/local`）
- 书架列表只有 API 有（`GET /api/v1/books`），CLI 没有 ——
  于是用户下载完就再也找不回 `book_id`，`mog export` 用不了
- 章节正文、导出作业的输出路径、任务事件流，都只有 API 有

项目的原则是 **API-First，API 是正式产品接口**，但「CLI 有的 API 也得有」
只是其中一半；**API 有的 CLI 也得有**，否则命令行用户寸步难行。
加新能力时两边都过一遍。2026-10-05 全量核对过一次，27 个端点逐个对，
结果记在下面。

### API ↔ CLI 能力对照（2026-10-05 核对）

| API 能力 | CLI |
|---------|-----|
| `GET /health` | `mog server status` |
| 书源：列出/详情/安装/卸载/启停/体检/重扫 | `mog source *` |
| 搜索（书源 / 本地正文） | `mog search` / `mog find` |
| 书架 / 详情 / 章节列表 | `mog book [<ID>] [--chapters]` |
| 章节正文 | `mog book <ID> --chapter <序号>` |
| 增量更新 | `mog update` |
| 导出（创建） | `mog export`（本地跑，不经 API） |
| 导出作业列表 / 状态（含输出路径） | `mog task list` / `mog task show` |
| 任务列表 / 详情 / 暂停 / 继续 / 取消 / 重试 | `mog task *` |
| 任务事件流（SSE ×2） | `mog task watch` |

**已知的实现路径差异（不是缺陷）**：`mog export` 和 `mog download` 在 CLI 里
**就地跑**（进程结束就退出），不走 server。导出作业照样写 `exports` 表，
所以 `GET /exports` 和 `mog task list` 都能看到。

### 取消跑不动正在进行的下载 —— 已修

`mog task cancel` 原先返回 200、数据库里状态也变成 `cancelled`，
但**下载还在继续**（实测：取消后事件流仍推进 `174/2036 → 188/2036`）。

根因是 `TaskRunner` 只在**进入 handler 之前**检查一次 `is_cancelled`，
而 `DownloadScheduler` 的逐章循环里没有任何取消检查 ——
`_pool.cancel_task()` 设的那个标志中途没人看。

修法：给调度器加 `should_stop` 回调（和 `on_progress` 同形状，**同步的**），
在**拿到并发信号量之后、发请求之前**检查。位置有讲究：放在最前面的话，
所有协程在开工那一刻就检查完了，后来的取消谁也看不见。

同时把 `asyncio.gather` 换成 `TaskGroup` —— 取消时 gather 会把其余协程
**丢在后台继续跑**（它只抛第一个异常，不取消兄弟）。注意 TaskGroup 会把
异常包成 `ExceptionGroup`，而 `TaskRunner` 是按 `except TaskCancelledError`
判断的，得先拆开，否则取消会被当成「意料之外的失败」标成 FAILED。

实测：取消后任务标成 `cancelled [TASK_CANCELLED]`，事件流也停了。

**Alembic 迁移目录没建。** 依赖声明了，但 `alembic/` 目录和首个迁移脚本还没有。
现在 schema 是 `create_all` 建的，改表就得手写迁移。

**EPUB 的封面和元数据模板没做。** 导出结构是规范的（有离线测试验证
`mimetype` 顺序、OPF、NCX），但封面图不下载，元数据也不能按模板配。

**没有字段级 transform。** `transform` 作用于能力下的所有字段，
所以 `url_join` 只能用「像不像 URL」来条件化（规范 §6.4 的折中）。
原始规划书说 v1.1 会加字段级，目前还没做。状态字段的 `"1"`→`completed`
映射也因此只能用「锚定整值的正则」绕（见规范 §5.5）。

**本地全文搜索是 `LIKE` 全表扫描。** `mog find` 用 `LIKE '%kw%'`，
用不上索引。个人书库规模够用（几十兆正文约百毫秒级），
库再大就该上 FTS5 虚拟表 —— 那需要动 schema，而
[storage-v1](storage/storage-v1.md) 是冻结的契约文档，得先改文档。

**书源搜索的合规代价。** `bqgnovels` 的 search 走 `/api/query/search`，
而该站点 robots.txt 的 `Disallow: /api*` 与 `Disallow: /search*` 两条都命中它。
使用它等于绕过站方表态，已由使用者决定并承担。这不是技术限制，
是每个书源各自要面对的取舍 —— 写新书源时应当先看 robots.txt。

### 低

**`mog source test` 没实现。** fixture 测试在 `tests/` 里有基础设施，
但没做成 CLI 命令。原始规划书 §12 列了这个命令。

**`.mgs` 打包格式没做。** 第一阶段只支持裸 `.yaml`（这是原计划）。

**书源健康监控没做。** `mog source doctor` 能手动跑，但没有定时体检。

**API 令牌不能轮换。** 只有「删掉 `data/token` 重启」这一种方式。
单机场景下够用，等真有需求再说。

**Electron 侧没有 lint。** 只有 tsc 类型检查。渲染层的 SSE 解析器有单元测试
（`apps/desktop/test/sse.test.mjs`），其余靠类型和人工验证。

## 真实站点验证怎么做

每验证一个新站点，按这个清单走一遍。**光看「命令没报错」是不够的** ——
下载能跑完但内容残缺、章节重复、编码坏掉，都不会报错。

**一、抓取层**

```bash
mog source test sources/<id>      # 离线快照：提取结果是否为空
mog search <关键词>                # 真实搜索能不能出结果
mog download --url <书籍页> --source <id>
```

**二、数据层**（直接查库，别只看 CLI 的汇总数字）

| 检查 | 怎么查 | 期望 |
|------|--------|------|
| 章节数 | `COUNT(*)` | 与站点目录一致 |
| URL 唯一 | `COUNT(DISTINCT url)` | 等于章节数 |
| index 连续 | `MAX(index)-MIN(index)+1` | 等于章节数 |
| 空正文 | `content IS NULL OR content=''` | 0 |
| 零字数 | `word_count=0` | 0 |

> 重复**标题**不一定是问题。站点把一章拆成两页时标题会重样 ——
> 要看 URL 和 `content_hash` 是否不同。bqgnovels 的 2036 章里有 54 个重名标题，
> 全是这种拆分，不是重复下载。

**三、导出层**

```bash
mog export --format txt <book_id>
mog export --format epub <book_id>
```

EPUB 逐项验（`unzip` 出来看）：

- `mimetype` 是**第一条**且**未压缩**（`unzip -v` 里显示 `Stored`），内容是
  `application/epub+zip`
- `META-INF/container.xml` 指向 `OEBPS/content.opf`
- `content.opf` 的 manifest 项数 = 章节数 + toc/样式等附属文件；
  **spine 项数 = 章节数**
- `toc.ncx` / `toc.xhtml` 存在
- 抽查若干章：`<p>` 段落正常、无 `&lt;` / `&nbsp;` / `<div>` 残留
- 没有异常小的章节文件（空章会是几百字节）

TXT 检查：开头有书名/作者/简介，章节间有分隔线，文件是合法 UTF-8。

---

## 下一步

按依赖顺序：
1. **再验证几个不同类型的真实站点** —— 补上 JS 渲染、反爬、GBK 编码、
   页码式翻页这几类，才能说「书源规范够用」。
2. **桌面端补全页面** —— 书架、书源管理、设置。架构已验证，照着加就行。
3. **Alembic 迁移** —— 趁 schema 还简单，把迁移链路搭起来。

> Source Registry 原排在第三位，现已明确不做（见 v0.3.0 一节）——
> 它和「远端版本检查/下载」是同一件事的两面，书源分发交给
> `repository` 字段 + 用户自行安装。

## 已完成的重要节点

- **书源的状态与自定义字段接通领域模型**（2026-10-04）。`BookStatus` 枚举的
  文档一直写着「由书源尽力解析」，但 `BookDraft` 里没有 `status` 字段、
  `draft.extra` 也全仓库无人消费 —— 两条链路都是断的，书源写什么都白写。
  现在 `book.fields.status` 会映射成 `Book.status`，规范外的字段进
  `Book.metadata`。见规范 §5.5。
- **首个真实站点书源跑通**（2026-10-04）。`bqgnovels.com` 完整目录 1453 章、
  正文清洗干净。过程中暴露并修掉了四个引擎缺口（分页、`network` 死配置、
  `<br>` 分段、U+00A0 清洗）和一个 httpx `params={}` 清空查询串的真 bug。
- **首个预发布版本 `1.0.0rc0`**（2026-10-04）。规范冻结、核心链路跑通、
  API 与 CLI 接线完成、桌面端最小闭环可用。
- **v0.4.0 的认证缺口已补**（2026-10-04）。API 的所有业务端点现在要求
  `Authorization: Bearer <token>`，令牌自动生成在 `data/token`。
  详见 [ADR-0004](architecture/decisions/ADR-0004-local-api-auth.md)

## 相关文档

- [规划评估报告](evaluation/规划评估报告.md) —— 对原始规划书的评估与裁决
- [原始规划书](planning/项目规划书.md) —— 历史存档，不是规范，只用来追溯出处
- [架构总览](architecture/overview.md) —— 分层、边界、数据流
- [ADR](architecture/decisions/README.md) —— 已定型的架构决策及理由
- [开发指南](development/getting-started.md) —— 环境、命令、提交规范
- [CHANGELOG](../CHANGELOG.md) —— 按版本记录改了什么
