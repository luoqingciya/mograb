# 开发约定与容易踩的坑

> 这份文档回答一个问题：**照着 [CONTRIBUTING](../../CONTRIBUTING.md) 写完代码之后，
> 还有什么会让我白忙一场？**
>
> 代码风格、提交规范、PR 流程都在 CONTRIBUTING 里。这里只放两样东西：
> **约定背后的理由**，和**踩过一次不想再踩的坑**。

## 1. 文档纪律

### 规范文档是契约，不是说明

`docs/` 下的四份规范 —— [Source Spec](../source-spec/source-spec-v1.md)、
[Domain Model](../domain-model/domain-model-v1.md)、
[Storage](../storage/storage-v1.md)、[API](../api/api-v1.md) —— 是**契约**。

**改行为要先改文档、再改代码。** 反过来做的话，规范和实现会分叉，
而分叉之后没人知道该信哪个。

`docs/planning/项目规划书.md` 是**历史存档不是规范** —— 写代码一律以四份规范为准，
它只用来追溯出处。

### 进度只在一个地方维护

[`docs/progress.md`](../progress.md) 是进度的**唯一出处**。
README 和 CHANGELOG 不要各维护一份 —— 两份必然对不上，而且没人知道哪份是新的。

### 写文档前先去看代码

数字和状态类的内容最容易过时。栽过好几次：

| 文档说 | 实际 |
|--------|------|
| 「端到端下载 7 章 / 76,725 字」 | 2036 章 / 451 万字 |
| 桌面端书架能用 | 只有 search / tasks 两个页面，其余是占位页 |
| `SECURITY.md`「v0.x 阶段，支持 0.1.x」 | 仓库从来没发过 0.x，`VERSION` 一直是 `1.0.0rc*` |

**改完代码回头核对文档；写之前去读代码** —— 桌面端有哪些页面看
`apps/desktop/src/renderer/main.ts` 的 `pages` 数组，别凭印象。

## 2. 质量门禁

提交前必过（见 [开发指南](getting-started.md) 的「常用命令」）：

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
uv run python scripts/check_docs.py                                  # 动过文档
cd apps/desktop && npm run typecheck && npm run build && npm test     # 动过桌面端
```

覆盖率门槛 70%（实际约 86%）。CI 有 8 个 job，改动后确认全绿。

**`docs/` 在 ruff 的 exclude 里** —— ruff 0.16 起会格式化 Markdown 里的代码块，
而文档里的片段是示意性的，不该被改。

## 3. 测试：两个环境差异

这两条都是**本地和 CI 表现不一样**，都炸过。

### CI 上的 CLI 输出带 ANSI 颜色，本地不带

Typer 的 `rich_utils` 里有：

```python
FORCE_TERMINAL = True if getenv("GITHUB_ACTIONS") or getenv("FORCE_COLOR") or getenv("PY_COLORS") else None
```

CI 里 `GITHUB_ACTIONS` 恒为 true，于是**强制开终端模式**，输出全是转义序列。
断言 `"─ 选项 ─" in output` 在本地过、在 CI 挂 —— 实际拿到的是
`─ \x1b[1m选项\x1b[0m ─`。

**涉及 CLI 输出的断言先剥 ANSI**（见 `tests/unit/test_localize.py` 的 `_plain()`），
并且本地用 `GITHUB_ACTIONS=true` 复验一遍。源码里别写字面 ESC，用 `chr(27)` 拼。

### 沙箱里连本地关闭端口会挂起

httpx 报的是 `ReadTimeout` 而不是 `ConnectionRefused`，于是「没有 server」那类
测试在**本地必挂、CI 正常**。

先确认不是自己的回归：`git stash` 做对照，再靠 CI 判定。

## 4. CLI 开发

### Typer / Click 的内置文案是写死的英文

面板标题、`--help` 说明、错误文案都写在库里，**没有配置项**。
`mograb_cli/_localize.py` 用猴补丁换成中文，改的是模块级变量和几个函数引用。

**失效方式是静默的** —— Typer 升级后文案悄悄变回英文，不报错也不崩溃。
`tests/unit/test_localize.py` 盯着这些。加/改 CLI 输出后跑它。

打补丁要打在 **`typer.main`** 上：它用的是**导入时绑定的引用**，
改 `typer.completion` 里的同名函数不生效。

### Rich 输出的两个坑

```python
# 表格里要复制的列 —— 默认会把列压到终端宽度以内，
# `book_01M4590…` 这种截断看着有输出、实际没法用
table.add_column("ID", no_wrap=True)

# 正文类的输出 —— 默认会按终端宽度硬折（在句子中间插换行），
# 而正文里的 `[...]` 会被当成标记语言吞掉
console.print(text, soft_wrap=True, markup=False)
```

### 中文句末用全角句号

Click 拼的是西文 `.`，`_localize.py` 的 `_translate_error` 里转。

## 5. 异步与取消

### 取消是协作式的，检查点位置有讲究

`TaskRunner` 只在**进入 handler 之前**查一次 `is_cancelled`。一个跑几十分钟的
下载不能只靠这一次 —— 调度器自己要在循环里查（`DownloadScheduler.should_stop`）。

**检查点必须放在拿到并发信号量之后、发请求之前。** 放在最前面的话，
所有协程在开工那一刻就检查完了，后来的取消谁也看不见。

语义见 [Domain Model](../domain-model/domain-model-v1.md) 的「取消什么时候生效」。

### `TaskGroup` 会把异常包成 `ExceptionGroup`

`TaskRunner` 是按 `except TaskCancelledError` 判断的，不拆开的话取消会被当成
「意料之外的失败」，任务标成 FAILED 而不是 CANCELLED：

```python
try:
    async with asyncio.TaskGroup() as group:
        ...
except BaseExceptionGroup as group_error:
    if group_error.subgroup(TaskCancelledError) is not None:
        raise TaskCancelledError("下载已取消") from None
    raise
```

顺带一提：`gather` 在取消时会把其余协程**丢在后台继续跑**（它只抛第一个异常，
不取消兄弟）。要真取消就得用 `TaskGroup`。

## 6. 入口与打包

### `if __name__ == "__main__"` 在两条真实入口上都不执行

| 入口 | 怎么进来的 |
|------|-----------|
| 打包产物 | `scripts/entry_cli.py` 自己调 `app()` |
| 开发态 | console script `mog = "mograb_cli.main:app"` |
| ~~`python -m mograb_cli.main`~~ | 只有这条会走到 `__main__` 块 |

所以 `force_utf8_stdio()` / `localize_typer()` / `_strip_exe_suffix()` 都放在
**模块级**。**改完要构建后实测**，开发态看不出来。

### 打包漏动态导入的模块

PyInstaller 只做静态分析。**按字符串动态导入的模块它看不见**，
而这类漏掉的表现很欺骗：`--version`、`--help`、下载、导出全都正常，
只有碰到那条特定路径才炸。

已经栽过两次（`aiosqlite`、`shellingham.nt`）。现在的做法是**整包收集**
（`scripts/build.py` 的 `COLLECT_SUBMODULES`）而不是逐个列名字 ——
列名字要猜包内部会导入什么，猜漏一次就是一个只有用户能撞见的崩溃。

细节和完整清单见 [CI 与发布](ci.md) 的「踩过的坑」。

### 「构建成功」不等于「产物能用」

构建完必须真跑一遍产物。`scripts/build.py` 的 `smoke_test()` 有**两类**检查：

- 要求退出码为 0 的（版本号、数据库读写、输出编码……）
- **允许非零退出、但绝不能抛异常**的（`crash_free`）——
  `--show-completion` 在没有可探测父进程的环境里本来就退 1，
  「不可用」和「崩了」是两回事，要求退 0 会把真问题放过去

## 7. 操作坑

### `mog server start` 起的服务不会自己退

杀掉后台 shell 任务后服务还在跑、占着 48721，新起的服务**静默绑定失败**
（`[Errno 10048]`），请求全被旧进程处理 —— 会让人以为修复没生效。

**重启服务前先确认端口释放**：`netstat -ano | grep 48721`。

### 批量字符串替换会误伤

用 `s.replace("assert x == 2", "== 3")` 改自己的测试时，打中了另一个恰好也是
`== 2` 的测试。**改完必须跑全量测试**，不能只看自己那个文件。

### 扫仓库的脚本要排除 `node_modules`

那里有大量第三方包自带的 Markdown 和 Python（node-gyp 工具链）。
文档内链校验第一版因此报了 521 条假断链。`scripts/check_docs.py` 有
`SKIP_DIRS` 白名单。
