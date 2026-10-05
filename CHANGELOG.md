# 变更日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [PEP 440](https://peps.python.org/pep-0440/)。

版本号只有一个来源：仓库根的 `VERSION` 文件。改它，三个包一起变。

## [1.0.0rc5] - 2026-10-05

把 rc4 修的那个补全功能真正做完整。

### 修复

**补全脚本注册的命令名带 `.exe`，所以根本不会触发。** rc4 让
`--install-completion` 不崩了，但生成的脚本是：

```bash
complete -o default -F _mogexe_completion mog.exe
_MOG.EXE_COMPLETE=complete_bash
```

而用户敲的是 `mog` —— bash 补全按字面匹配命令名，`mog <TAB>` 不会触发。
环境变量名里还带个点（`_MOG.EXE_COMPLETE`），也很容易出问题。

顺带一提，帮助里的用法行也写成 `用法: mog.exe [OPTIONS] ...`。

根因是 Click 用 `sys.argv[0]` 推导 `prog_name`，而打包后的 `argv[0]` 是
`mog.exe`。现在在 CLI 模块导入时把结尾的 `.exe` 去掉：

```bash
complete -o default -F _mog_completion mog
_MOG_COMPLETE=complete_bash
```

> **改 `argv[0]` 而不是改 Click 的调用点**，是因为全项目没有别处依赖它 ——
> 数据目录走的是 `sys.executable`（见 `runtime_dir()`）。

> 这一处**第一次改错了**：我把它放在 `if __name__ == "__main__":` 里，
> 而那个块在两条真实入口上都不执行 —— 打包走 `scripts/entry_cli.py`
> （它自己调 `app()`），开发走 console script `mog = "mograb_cli.main:app"`。
> 只有 `python -m mograb_cli.main` 会走到。现在放模块级，和
> `force_utf8_stdio()`、`localize_typer()` 一致。

## [1.0.0rc4] - 2026-10-05

修一个 rc3 产物的崩溃，并给这类问题补上防线。

### 修复

**`mog --install-completion` 在发布包里直接崩。** 用户报告：

```
ModuleNotFoundError: No module named 'shellingham.nt'
RuntimeError: Shell detection not implemented for 'nt'
```

根因和 rc1 的 `aiosqlite` **是同一个坑**：PyInstaller 只做静态分析，
而 shellingham 的入口是

```python
importlib.import_module(".{}".format(os.name), __name__)
```

字符串动态导入 —— 分析看不见，`shellingham/nt.py` 没被打进去。
Typer 的 `--install-completion` / `--show-completion` 都要走这条路探测 shell，
于是必崩。

`HIDDEN_IMPORTS` 补上 `shellingham.nt` 和 `shellingham.posix`。

**这类问题的表现很有欺骗性**：`--version`、`--help`、下载、导出全都正常，
只有碰到那条特定路径才炸 —— 很容易以为包是好的。

### 测试

**冒烟测试加了一类「允许非零退出、但绝不能抛异常」的探测。**
原先每条检查都要求退出码为 0，而 `--show-completion` 在没有可探测父进程的
环境里本来就退 1（`Shell not supported.`）—— 「不可用」和「崩了」是两回事。
现在跑一遍它，只断言输出里没有 `Traceback` / `ModuleNotFoundError`。

**验证过这条检查真的能抓到**：临时注释掉 `shellingham.nt` 重新构建，
它确实报出了 Traceback。

`tests/unit/test_build_script.py` 加 `TestHiddenImports`：逐个确认那些
**已知的动态导入目标**都在清单里（`shellingham.{os.name}`、`aiosqlite`），
并验证清单里的模块都能导入（防写错名字 —— PyInstaller 对写错只会警告）。

不测「清单有几条」，因为那个数字不说明任何事。

## [1.0.0rc3] - 2026-10-05

**第三个预发布版本，也是内容最多的一版。** 主线是「把 API 和 CLI 拉齐」——
27 个端点逐个核对，补齐三处能力差，顺手挖出并修掉两个**用户看不见但会咬人**
的 bug。

**先记一笔好消息**：第一次真实站点全量下载跑通了 ——
`bqgnovels.com` 的《斗罗大陆3龙王传说》，2036 章 / 451 万字，**0 失败**。
数据是干净的：2036 章对应 2036 个不同 URL、index 连续无缺口、0 空正文；
EPUB 通过结构校验（`mimetype` 是 STORED、container / OPF / NCX 齐全、
2037 个 xhtml）、正文无 HTML 残留；TXT 与 EPUB 都是合法 UTF-8。

这一版修掉的三个「静默做错事」：

| 问题 | 表现 |
|------|------|
| 打包漏了 `aiosqlite` | rc1 的 CLI 和桌面端都打不开数据库 |
| SSE 从来不发进度事件 | 桌面端进度条从 0 直接跳到完成 |
| 取消停不下正在进行的下载 | 命令说成功了，下载照跑 |

三个都是**不报错**的那种 —— 命令返回成功、界面看着正常，但实际没做对。

### 新增

**`mog task watch` —— 走 SSE 实时跟踪任务。** 补上最后一块 API/CLI 能力差：
`GET /tasks/events` 和 `GET /tasks/{id}/events` 两个事件流端点，CLI 一直没有
对应的东西。给 ID 就盯着那一个、进终态自动退出；不给则跟着所有任务。

传输层不用 `EventSource`（它设不了请求头，令牌只能走 `Authorization`），
和桌面端一样手写 SSE 解析。心跳帧要丢掉 —— 它只有 `task_id`、没有 `status`，
当成事件推出去会渲染出空行，而心跳每 15 秒来一次。

**`mog book <ID> --chapter <序号>` —— 读单章正文。** 对应
`GET /books/{id}/chapters/{cid}`，CLI 原先没有这条路，想读一章只能先导出整本。

仓储层加了 `ChapterRepository.get_by_index()`：**不能拿 `list_by_book` 再筛**，
那个会把整本书的正文读进内存 —— 几千章就是几十兆，只为读一章不值得。

正文渲染带 `soft_wrap` —— Rich 默认按终端宽度硬折，会在句子中间插换行
（实测「所以
，我决定」）。正文已经按段落分好行了。

**`mog task show` 显示任务参数。** 导出任务的**输出路径**就在参数里，
原先不显示 —— 用户关掉终端就再也找不回导出的文件了（API 的 `GET /exports`
是有 `path` 的）。

**`mog book` 不给 ID 时列出书架。** 用户报的：「导出书籍需要 `book_id`，
但是我们没有查看的命令」。

确实是断的：`mog export` / `mog update` 都要 `book_id`，而那个 ID 是 ULID
（`book_01M459...`），没人记得住。原先只有一个「必须给 ID」的命令，
下载完关掉终端就再也找不回自己的书了。

API 那边一直有 `GET /api/v1/books`，CLI 没暴露 —— **API-First 的反向缺口**。

实现上有一条容易忽略：**ID 必须完整显示。** Rich 的表格默认把列压到终端宽度
以内，第一版渲染出来是 `book_01M4590…` —— 看着有输出，实际没法复制，
这个命令就白做了。ID 列加了 `no_wrap=True`，`tests/integration/test_cli.py`
的 `test_ID_完整显示不被截断` 钉住这条（用真实 ULID 长度，`book_t` 那种短 ID
测不出来）。

同时去掉了「字数」列 —— 6 列在 80 列的终端里会把书名挤成 4 行。
字数在 `mog book <ID>` 的详情里有。

### 修复

**取消停不下正在进行的下载。** `mog task cancel` 返回 200、数据库里状态也变成
`cancelled`，但**下载还在继续** —— 实测取消后事件流仍推进
`174/2036 → 188/2036`。

根因是 `TaskRunner` 只在**进入 handler 之前**检查一次 `is_cancelled`，
而 `DownloadScheduler` 的逐章循环里没有任何取消检查。表现是「静默地做错事」：
命令说成功了，任务却没停。

修法是给调度器加 `should_stop` 回调（和 `on_progress` 同形状，**同步的**），
在**拿到并发信号量之后、发请求之前**检查。位置有讲究 —— 放在最前面的话，
所有协程在开工那一刻就检查完了，后来的取消谁也看不见。

同时把 `asyncio.gather` 换成 `TaskGroup`：取消时 gather 会把其余协程
**丢在后台继续跑**（它只抛第一个异常，不取消兄弟）。注意 TaskGroup 会把异常
包成 `ExceptionGroup`，而 `TaskRunner` 是按 `except TaskCancelledError` 判断的，
得先拆开 —— 否则取消会被当成「意料之外的失败」标成 FAILED。

**SSE 从来不发进度事件。** 这是第六处「声明了没接线」，而且是用户看不见的那种：

`Application._progress` 的 docstring 写着「API server 推 SSE 时读的是同一个
对象」，但进度变化**没有任何广播** —— 状态通知（`TaskRunner._notify`）只在
状态跃迁时触发。于是整个下载过程只在「开始」和「结束」各推一条，
中间什么都没有。

而桌面端的任务页写着「进页面时拉一次 /tasks，之后靠 SSE 推更新」、
**没有轮询** —— 它的进度条会从 0 直接跳到完成。

修法是给 `Application` 加一个 `_progress_listener`，API 把它接到自己的
`publish_task` 上。**限流 1 秒一条**：逐章推会把事件流灌满（三千章就是三千条），
而进度条 1 秒刷一次已经够顺；最后一次不受限流约束，免得进度停在 99%。

实测验证：真跑一次下载，`mog task watch` 收到
`1/2036 → 119/2036 → … → 149/2036` 连续事件。

**API 文档里的 SSE 契约和实现对不上。** 文档写的是
`event: progress` / `data: {"speed":3.4}` 和四种事件类型
（`progress` / `status` / `error` / `done`），实现里只有 `task` + `heartbeat`
两种，也没有 `speed`、没有 `seq`。按实际改正了。

**`mog --help` 中英混排。** 面板标题是 `Options` / `Commands`，三条选项说明是
英文：

```
│ --install-completion   Install completion for the current shell. │
│ --help                 Show this message and exit.               │
```

这些是 Typer / Click **写死在库里的**，没有配置项。Typer 的 `_()` 就是
`gettext.gettext`，走那条路要装 gettext 目录、配 locale、带 `.mo` 文件 ——
对一个自带运行时的便携程序太重。

新增 `mograb_cli/_localize.py`，改模块级变量和几个函数引用。连同错误文案
（`Missing argument 'source_id'.` → `缺少参数 'source_id'。`）一起换成中文。
`tests/unit/test_localize.py` 逐条钉住 —— **只断言「不该出现英文」不够，
还要断言「该出现中文」**，否则补丁没生效时两条都过。

> 这是**猴补丁**，Typer 升级后可能失效，而且失效方式是静默的：文案悄悄变回
> 英文，不报错也不崩溃。所以那 11 条测试是必需的，不是锦上添花。

**`download.proxy` 是第五处「声明了没接线」。** `HttpClientConfig.proxy`
一直存在、也传给了 httpx，但 settings 里没有它、`config.toml` 模板里也没有 ——
所以**永远是 `None`**。用户实测时「不挂代理搜索失败、挂了才成功」，
撞的正是这里。

现在接进 `[download] proxy`，并在 README 里写清两条路：配置文件，
或者环境变量 `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`（httpx 的
`trust_env` 默认开着，这条**本来就可用，只是没人知道**）。

**日志糊在进度条中间。** 长下载时看到的输出是这样：

```
⠴ 下载章节 ━━━━ 339/2036 0:06:062026-10-05T13:42:38 [warning] http.retry attempt=1 …
```

进度条在 stdout 上不停重画当前行，日志另写 stderr，两个写入者不协调。
现在 CLI 把日志交给**同一个 Rich console**（`configure_logging(console_sink=...)`），
Rich 知道有 Live 区域，会把日志排在进度条**上方**。

核心库不依赖 Rich，所以这里传的是回调而不是 Console 对象。

**`configure_logging` 会静默失效。** `logging.basicConfig()` 在根 logger
已有 handler 时**什么都不做** —— 不带 `force=True` 的话整个日志配置被跳过，
一个 handler 都装不上，而且不报错。写这批测试时撞到过：
pytest 先挂了自己的 handler，注入的通道完全没生效。

「配了等于没配，还不报错」正是这个项目反复在防的那类问题。

### 文档

**README 重写。** 加了两块内容：

- **「怎么用」** —— 三条路（CLI 发布包 / 源码 / 桌面端）分开讲，
  并**明确推荐命令行**。桌面端只有搜索和下载两页能用，书架、书源管理、
  设置都还是占位页 —— 这一点之前 README 没说，读者容易误判。
- **命令行教程** —— 从装书源到导出走一遍完整流程，配真实输出。

同时修掉几处过时信息：

| 位置 | 原来 | 实际 |
|------|------|------|
| README「现在做到哪了」 | 端到端下载 **7 章** / 76,725 字 | 2036 章 / 451 万字，0 失败 |
| README 测试数 | 654 个测试 | 708 |
| `SECURITY.md` | 「目前处于 v0.x 阶段」，版本表 `0.1.x` | `1.0.0rc` 预发布 |
| `docs/api/api-v1.md` | `/health` 示例写 `1.0.0rc1` | 当前版本 |

`SECURITY.md` 那份尤其误导 —— 仓库里**从来没有 0.1.x 的发布**，
`VERSION` 一直是 `1.0.0rc*`，那是规划书里的旧编号漏过来的。

领域模型补了「取消什么时候生效」：`cancel` 是**协作式**的，队列里的任务立即
摘掉，正在跑的在下个检查点（下载是每章开始之前）退出。

### 测试

**`test_pause_without_server_explains` 不再依赖「默认端口空闲」。**
它原先跑的是 `mog task pause`，靠「48721 上没人监听」这个隐含假设 ——
开发者本地开着 `mog server start` 就会挂，而且报错信息完全指不到原因。
现在用环境变量指到一个确定空闲的端口。

新增 `tests/unit/test_settings.py`（配置接线）和
`tests/unit/test_logging_sink.py`（日志落点）两个文件，共 13 个用例。

> 顺带记两个写测试时踩的坑：`setup_module` 是 pytest 的**保留钩子名**，
> 拿它当模块别名会被当成钩子调用；断言带颜色的日志前要么剥 ANSI、
> 要么直接用 `json_output=True`，往源码里塞字面 ESC 字符会被编辑器吃掉。

## [1.0.0rc2] - 2026-10-05

**rc1 的发布包是坏的，这一版修掉。** 两个产物都打不开数据库：

```
ModuleNotFoundError: No module named 'aiosqlite'
```

CLI 一碰数据库就崩；桌面端内置的后端在 lifespan 启动阶段直接失败，
整个桌面端都用不了。

**根因**：SQLAlchemy 通过 `import_dbapi()` 按**字符串**导入驱动包，
PyInstaller 的静态分析看不见。构建脚本的 `HIDDEN_IMPORTS` 里只列了
dialect 适配器 `sqlalchemy.dialects.sqlite.aiosqlite`，漏了驱动包本身。

**为什么没拦住**：产物能跑 `--version`、能出 `--help`，看起来是好的 ——
只有真去读数据库才会暴露。而构建、CI、发布三道关都只验「构建成功」，
没有任何一步真的执行过产物。

### 修复

**打包漏模块。** 加回 `aiosqlite`，并且**给构建加上了冒烟测试** ——
这才是真正的修复。现在 `scripts/build.py` 构建完会自动执行产物：

| 检查 | 覆盖什么 |
|------|---------|
| `--version` | 入口 + 版本元数据 |
| `config path` | 配置解析 |
| `source list` | **数据库读写**（当初漏 aiosqlite 的地方） |
| `find <关键词>` | 查询路径（章节仓储） |
| 数据目录 | 首次运行要建全 5 个子目录 |
| 输出编码 | 必须是 UTF-8 字节 |

后端另外起一次服务：探 `/health`，再带令牌打 `/api/v1/sources` ——
**`/health` 不碰数据库，光看它通不出结论**，当初漏 aiosqlite 时它也是好的。

CI 新增 `package-smoke` job，PR 阶段就拦。Release 工作流本来就会跑这个
冒烟测试，所以发版前必然经过一次真执行。

**打包后的产物输出 GBK 而不是 UTF-8。** PyInstaller 的 exe **无视**
`PYTHONUTF8` / `PYTHONIOENCODING`（实测四种组合都无效），默认按控制台代码页
输出，中文 Windows 上就是 GBK。后果是 `--json` 产出的不是合法 JSON
（JSON 规范要求 UTF-8），管道给别的工具也是乱码。

而开发态（`uv run`）是 UTF-8 —— **只有用户拿到的包是坏的**，本地怎么测都测不出来。

修法：新增 `mograb.console.force_utf8_stdio()`，在 CLI 和 API 入口调用。
只在**输出被重定向**时改编码 —— 直接连控制台时 CPython 走宽字符 API
本来就正确，硬改反而会让 cp936 控制台乱码。

**只读命令不会建出完整的数据目录。** `data/` 只建了 `logs/`，缺
`cache` / `covers` / `exports` / `sources` —— 看起来像装坏了。

原因是 `create_application` 有个 `ensure_paths` 开关，10 个只读命令都传了
`False`。但日志初始化**无论如何都会建 `logs/`**，所以「不建目录」的意图
根本没达成，结果是建了一半。

现在**总是创建**，参数整个去掉。要么全建要么不建，全建的成本是几个空目录。

### 新增

**`GET /api/v1/search/local` —— 本地全文搜索的 API 端点。**
`mog find` 之前只有 CLI，API 没有对应接口，而项目的原则是 API-First、
API 才是正式产品接口。桌面端因此做不了本地搜索。现在补上了，
仓储层的 `search_content` 本来就绪，只是没接线。

和 `GET /search` 是两件事，所以分成两个端点而不是加个开关：
前者去书源上搜书（找「哪本书」），后者只查本地库（找「哪一章」），
一行网络请求都不发。

### 工程

**`scripts/` 纳入 pyright 检查。** 之前 `include` 只列了三个源码目录，
发版脚本不在检查范围内 —— 而发版脚本恰恰是产出发布包的那段代码。
补上后暴露 3 处 `sys.stdout.reconfigure` 的类型问题（运行时无碍），已修。

**三个脚本里重复的 `_force_utf8_output` 收敛成 `scripts/_console.py` 一份。**
脚本刻意保持独立（`version.py` 要在 `uv sync` 之前能跑），所以不和
`mograb.console` 共用实现，但至少不再各写一遍。

**测试夹具加 `load_script`。** 脚本之间是平级导入，用
`spec_from_file_location` 加载时 `scripts/` 不在 `sys.path` 里，
每个测试文件各写一遍 `sys.path.insert` 迟早会漏。

## [1.0.0rc1] - 2026-10-05

**第二个预发布版本。** 主线是「把书源做成一个能长期维护的东西」——
补齐了书源作者需要的工具链，并修掉写第一个真实站点书源时暴露的问题。

装上之后能干的事比 rc0 多了三样：**列表分页**（长目录不再静默截断）、
**`mog source test`**（用离线快照真跑一遍提取）、
**`mog find`**（在已下载的正文里搜关键词，纯本地）。

首次在真实站点上完整验证：`bqgnovels.com` 的书源取到 **1453 章**目录，
端到端下载 7 章 / 76,725 字，三种格式导出正常。

这一版还修掉了**四个「声明了没接线」**——`network.headers`、`network.retry`、
`BookStatus`、`draft.extra`，以及 `format: json` 的列表提取。它们的共同点是
文档和类型都声明了、链路断在半路，而失效方式是**静默**的：
书源作者配了自定义 UA 以为生效了，实际没有。

以及**三个只有真跑一遍才暴露的 bug**：`params={}` 清空查询串、
面包屑选择器命中全部元素、导出扩展名不跟 `--format`。
它们离线测试都测不出来 —— 离线 fixture 只覆盖了测试结构本身能覆盖的组合。

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

**`mog source test` —— 用离线快照跑一遍书源规则。** 比 `lint` 多查一层：
**提取结果是否为空**。

选择器写错时 lint 是发现不了的 —— 规则照样能编译，只是匹配不到东西，
而站点改版最常见的失效方式正是这个。所以必须真跑一遍提取。

用例写在书源目录的 `fixtures/cases.yaml`，声明每个能力用哪个 URL 触发、
喂哪些快照：

```yaml
- capability: chapters
  url: https://example.com/book/1001
  # 分页时按**请求顺序**依次提供
  files: [book.html, book-page2.html]
```

`url` 必须显式写：`chapters` 的目录常常就在书籍页上（请求 URL 是
`{{book.url}}`），从文件名猜不出来；而且 `url_join` 需要真实的 base URL
才能验出「相对地址有没有被补全」。

**只接受路径，不接受书源 ID。** 快照是开发期产物，`install` 只复制
`source.yaml`，不会把 `fixtures/` 带进数据目录 —— 否则每个已安装书源都拖着
一份会随版本变旧的测试数据。所以测试在开发目录里跑：`mog source test .`。
（规划书 §51 写的是传 ID，这里裁决为统一成路径，传 ID 时给出明确指引。）

**`repository` 字段 —— 更新入口交给用户。** 书源可以声明自己的发布地址，
`mog source show` 会显示它并提示「需要新版就去这里取，重新 install 即可覆盖」。
MoGrab **不做远端版本检查、不做自动下载、不做回滚** —— 那需要一整套分发协议
（Registry、版本协商、签名校验），是个独立课题，收益不抵复杂度。
不填就什么都不显示。

### 修复

**`mog source show` 声称「可回滚到 X」，但回滚根本不存在。** `sources` 表里
`installed_version` / `previous_version` 两列都在且已接线，install 确实会记
旧版本号，于是 CLI 会打印「可回滚到 1.0.0」。但：

- `mog source rollback` **命令不存在**（实测报 `No such command`）
- **旧版本定义文件也没保留** —— 磁盘上只有单个 `data/sources/<id>/source.yaml`，
  新版本直接覆盖。规划书 §56 要的 `1.2.0/` `1.1.0/` `current` 目录结构不存在

这比单纯缺失更糟：它给了错误的安全感。既然回滚已明确不做，就改成中性的
「版本变更 1.0.0 → 1.0.1」，`previous_version` 降级为纯诊断字段。

**`mog source lint <不存在的路径>` 报「Schema 校验失败」。** 真正的原因是
路径写错了。现在先在 CLI 层查存在性，提示「路径不存在」，退出码从 4
（校验失败）改成 2（参数错误）。

**`mog source test` 的实现里踩了自己的坑**：一开始测试直接往共享的
示例书源目录里写用例，一条用例把 `cases.yaml` 覆盖了，后续测试全崩。
现在所有会改文件的测试都在 `tmp_path` 的副本上做 —— 共享夹具只能读。

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

### 文档

全量过了一遍文档，修掉几处**会让人照做就失败**的错误：

**分支策略是错的。** `CONTRIBUTING.md`、开发指南、CI 文档三处都写着
「从 `develop` 创建分支、PR 到 `develop`」，但**仓库从来只有 `main`**。
照着做的人在第一步就卡住。CI 工作流自己也列了 `develop` 作为触发分支 ——
死配置，一并清掉。

**README 说「所有测试都是离线的，还没在真实站点跑过完整下载」。** 这已经
不对了：真实站点跑通过一本（`bqgnovels.com`，1453 章目录 + 端到端下载）。
rc 的理由改成准确的版本：**真实站点只验证过一个，而且是最简单的一类**。

**存储文档说 `previous_version`「用于回滚」。** 回滚已明确不做。改成
「纯诊断用」并说明原因。

**API README 完全没提认证。** 所有业务端点都要求 Bearer 令牌，这是调用者
最需要知道的事。补上了令牌来源、为什么不用查询参数、以及回环地址为什么
不构成信任边界。

其余修正：`/health` 示例里的版本号、`mog source lint` 的示例输出、
CLI 命令清单（补 `show` / `remove` / `enable` / `disable` / `rescan` /
`token` / `find`）、模块地图补 `app.py`、领域模型补 `BookStatus` 的取值来源、
存储文档补本地全文搜索一节、CI 文档补 `source test` 步骤。

`CONTRIBUTING.md` 里还有一处 Markdown 表格串行（`chore` 那行和 scope 表
粘成了一行），也修了。

649 个测试，覆盖率 85%。

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
| v0.2.0 | 能稳定下载大量章节 | 已达成（真实站点 1453 章验证） |
| v0.3.0 | 第三方能写书源并维护 | 已达成（Registry / 回滚明确不做） |
| v0.4.0 | API 成为正式接口 | 已达成 |
| v0.5.0 | CLI 在 Windows / Linux 上独立可用 | 已达成 |
| v0.6.0 | Windows 桌面端 Beta | 进行中 |
| v0.7.0 | 输出质量和性能 | 部分（缺封面与元数据模板） |
| v1.0.0 | 规范、API、CLI 命令全部稳定 | 本版是它的 rc |

各版本的实际达成情况以 [docs/progress.md](docs/progress.md) 为准。

[1.0.0rc5]: https://github.com/luoqingciya/mograb/releases/tag/v1.0.0rc5
[1.0.0rc4]: https://github.com/luoqingciya/mograb/releases/tag/v1.0.0rc4
[1.0.0rc3]: https://github.com/luoqingciya/mograb/releases/tag/v1.0.0rc3
[1.0.0rc2]: https://github.com/luoqingciya/mograb/releases/tag/v1.0.0rc2
[1.0.0rc1]: https://github.com/luoqingciya/mograb/releases/tag/v1.0.0rc1
[1.0.0rc0]: https://github.com/luoqingciya/mograb/releases/tag/v1.0.0rc0
