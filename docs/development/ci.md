# 持续集成与发布

> 对应[原始规划书](../planning/项目规划书.md)（历史存档，非规范）：§48、§57
> 工作流：`.github/workflows/ci.yml`、`.github/workflows/release.yml`

---

## 1. CI 流程

```
push / PR → main
        ↓
┌───────────────────────────────────────────┐
│ lint          ruff check + format --check │
│               + 文档内链校验               │
│ version       VERSION 格式与来源唯一性     │
│ type-check    pyright                     │
│ test          矩阵：{3.11,3.12} × {linux,windows} │
│ source-lint   参考书源 lint + 真跑一遍提取 │
│ build         uv build --all-packages     │
│ package-smoke 打 PyInstaller 产物并真跑一遍 │
│ desktop       npm ci + tsc + SSE 解析器测试 │
└───────────────────────────────────────────┘
```

### 1.1 设计要点

| 决策 | 理由 |
|------|------|
| `uv sync --locked` | 强制 lock 与 pyproject 一致，防止本地能跑 CI 不能跑 |
| 测试矩阵含 Windows | 桌面端只支持 Windows，路径和编码问题要早发现 |
| desktop job 设 `ELECTRON_SKIP_BINARY_DOWNLOAD` | 类型检查、tsc 编译和 SSE 解析器测试都用不到 Electron 二进制，省一次上百兆的下载 |
| `version` 独立成 job | 版本号来源出问题会让发版直接失败，值得单独可见 |
| 文档内链校验并入 `lint` | 纯标准库脚本，不需要单独装环境；归在 lint 语义下也说得通 |
| `source-lint` 独立成 job | 书源问题与代码问题分开定位。这一步既跑 `lint` 也跑 `source test` —— 前者只查规则能不能编译，后者真跑一遍提取，才查得出「选择器写错了、匹配不到东西」 |
| `package-smoke` 独立成 job | **rc1 发出去的 CLI 和桌面端都是坏的**，而构建、CI、发布三道关全都没拦住 —— 因为都只验「构建成功」，没人真执行过产物。这个 job 打一遍 PyInstaller 产物并真的跑起来 |
| `package-smoke` 只在 Linux 上打 | 这类问题的根因是「模块没被打进去」，与平台无关。Windows 的打包由 Release 工作流在发版前验证 |
| `-m "not network"` | 测试默认离线，不依赖外部站点可用性 |
| `concurrency.cancel-in-progress` | 同分支的旧运行自动取消，省额度 |

### 1.2 测试标记

| 标记 | 含义 | CI 中 |
|------|------|-------|
| `unit` | 纯单元测试 | 运行 |
| `integration` | 跨层集成 | 运行 |
| `source` | 书源 fixture（离线） | 运行 |
| `e2e` | 端到端 | 待补 |
| `network` | 需要真实网络 | 默认跳过 |

---

## 2. 本地复现 CI

```bash
uv sync --locked --all-packages

uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_docs.py
uv run pyright
uv run pytest -m "not network" --cov

# 书源
for f in tests/fixtures/**/source.yaml; do uv run mog source lint "$f"; done

# 桌面端（测的是编译产物，所以 build 必须排在 test 前面）
cd apps/desktop && npm run typecheck && npm run build && npm test && cd -

# 构建
uv build --all-packages --out-dir dist
```

---

## 3. 发布流程

### 3.1 版本号

版本号只有一个来源：仓库根的 `VERSION` 文件。三个包构建时都读它。

发版前先改版本号：

```bash
uv run python scripts/version.py set 1.0.0rc3   # 写进去的是规范化形式
uv run python scripts/version.py check          # 确认来源唯一、格式合规
```

`set` 会把输入规范化成 PEP 440 的规范形式（`1.0.0.rc3` → `1.0.0rc3`，
`1.0.0.DEV0` → `1.0.0.dev0`），所以 `VERSION` 里的值就是最终值。
`check` 验证三件事：VERSION 内容符合 PEP 440、三个包的 `pyproject.toml`
用的是 dynamic version 且指向同一个文件、源码里没有硬编码的 `__version__`。

**改完必须强制重装一次**，否则打出来的产物会带旧版本号：

```bash
uv sync --all-packages --group build \
  --reinstall-package mograb --reinstall-package mograb-cli --reinstall-package mograb-api
```

原因见下面的「踩过的坑」。`scripts/build.py` 现在会拦这种情况，版本对不上直接
报错并给出上面这条命令。

改完提交，再打 tag。tag 名要和 VERSION 一致，Release 工作流会用它命名产物。

### 3.2 触发

```bash
git tag v1.0.0rc3
git push origin v1.0.0rc3
```

推 tag 就是发布 —— 工作流会直接建一个**公开**的 Release。
版本号里带预发布段（`a` / `b` / `rc` / `dev`）时自动标成 **pre-release**，
不标的话它会被当成正式版挂在 releases 页首，还会被 GitHub 当成 latest。

想要只建 draft 不公开，走 Actions 页面手动触发（Release → Run workflow），
填版本号并把 `draft` 勾上。手动触发同样校验版本号与 `VERSION` 文件是否一致。

### 3.3 流水线

```
Verify（质量门禁 + 解析版本属性）
    ↓
┌──────────────────────┬──────────────────────┬──────────────────────┐
│ CLI Windows          │ Desktop Windows      │ CLI Linux            │
│ PyInstaller onedir   │ backend + Electron   │ PyInstaller onedir   │
│ → ZIP                │ → ZIP + NSIS         │ → tar.gz             │
└──────────────────────┴──────────────────────┴──────────────────────┘
    ↓
SHA256SUMS.txt
    ↓
GitHub Release（预发布版本自动标 prerelease）
```

`Verify` 会把 `version` 和 `prerelease` 两个属性导出给后面的 job ——
后者由 `scripts/version.py flags` 判定（内部用 `packaging`，
不手写正则：「哪些后缀算预发布」是 PEP 440 定义的，手写迟早漏掉 `.post` 之类）。

### 3.4 产物清单

以 `1.0.0rc3` 为例：

| 产物 | 类型 | 说明 |
|------|------|------|
| `MoGrab-CLI-v1.0.0rc3-win-x64.zip` | 目录型便携 CLI | 解压即用，含完整运行时 |
| `MoGrab-v1.0.0rc3-win-x64.zip` | Portable Desktop | Electron + 后端 sidecar |
| `MoGrab-Setup-v1.0.0rc3-win-x64.exe` | NSIS 安装包 | 安装 / 卸载 / 快捷方式 |
| `MoGrab-CLI-v1.0.0rc3-linux-x64.tar.gz` | Linux CLI | |
| `SHA256SUMS.txt` | 校验和 | 用于验证下载完整性 |

命名统一带 `v` 前缀，桌面端两个产物用 `MoGrab-` 和 `MoGrab-Setup-` 区分 ——
一个 Portable 一个安装包，名字一样只靠扩展名区分太容易拿错。
产物名在 `apps/desktop/package.json` 的 `win.artifactName` / `nsis.artifactName`
里配，CLI 侧在 Release 工作流里拼。

桌面端产物来自 `npm run build` + `electron-builder`，后端 sidecar 单独打包后
放进 `resources/backend/`。版本号通过 `--config.extraMetadata.version` 从 tag 传入，
不去改 `package.json` —— 改了会让 `package-lock.json` 里的版本对不上。

### 3.5 打包原则

| 原则 | 说明 |
|------|------|
| uv 不进产物 | uv 仅属于开发与构建链路 |
| 用户无需安装 Python | 运行时随产物分发 |
| 用户无需安装 Node.js | Electron 打包后自带 |
| 不要求单文件 EXE | 优先保证启动稳定性、依赖完整性、升级便利性 |
| 数据在程序目录下的 `data/` | 便携模式，升级时只替换程序文件，`data/` 原样保留 |

为什么不用单文件 EXE：单文件模式每次启动都要解压到临时目录，启动慢，
而且容易被杀软误报。目录型（onedir）启动更快、体积可预期、升级也容易 ——
换个可执行文件就行。

---

## 4. 本地构建预演

```bash
# 安装打包依赖，并强制重装工作区包（版本号改了就必须做，见 §6）
uv sync --all-packages --group build \
  --reinstall-package mograb --reinstall-package mograb-cli --reinstall-package mograb-api

VERSION=$(uv run python scripts/version.py show)

# 构建 CLI（PyInstaller onedir）
uv run python scripts/build.py cli --version "$VERSION"

# 构建 Desktop 后端 sidecar（必须在 electron-builder 之前，它要放进 resources/）
uv run python scripts/build.py backend --version "$VERSION"

# 验证产物里的版本号没写错
./release-artifacts/MoGrab-CLI/mog.exe --version    # 应输出 $VERSION

# 桌面端（NSIS + ZIP）
(cd apps/desktop && npx electron-builder --win --publish never \
  --config.extraMetadata.version="$VERSION")

# 生成校验和
uv run python scripts/release.py checksums --dir release-artifacts

# 校验
uv run python scripts/release.py verify --dir release-artifacts

# 提取发布说明
uv run python scripts/release.py notes --version "$VERSION"

# 清理
uv run python scripts/build.py clean
```

---

## 5. 待补项

| 项 | 说明 | 关联 |
|----|------|------|
| E2E 测试 job | `CLI → API → Task → DB → Export` 全链路 | 见测试策略 |
| 依赖漏洞扫描 | `pip-audit` 或 GitHub Dependabot | 评估报告 P3-06 |
| EPUB 规范校验 | 对生成的 EPUB 运行 `epubcheck` | ADR-0003 |
| 导入边界检查 | 禁止 `mograb.domain` 依赖基础设施、`mograb.export` 依赖 `mograb.network` | ADR-0001 |
| Desktop lint | 目前只有 tsc 类型检查 + SSE 解析器测试，没有 ESLint | CI |
| 缓存 CI 产物 | 加速重复构建 | — |

---

## 6. 踩过的坑

这几条都是实际踩出来的，改回去会再挂一次。

**`astral-sh/setup-uv` 别用 `@v8` 以上。** 这个仓库从 v8 开始不再打 major tag，
只有 `v10.2.0` 这种具体版本号。引用 `@v10` 会直接 Not Found，job 在
"Set up job" 阶段就挂，而且错误信息里看不出原因 —— 表现是多个 job 同时秒失败。
当前用 `@v7`，这是最后一个有 major tag 的版本。

**Windows runner 上跑 Python 脚本要处理编码。** 控制台默认 cp1252，
`print` 中文直接抛 `UnicodeEncodeError`。`scripts/_console.py` 里有
`force_utf8_stdio()`，脚本开头都调用它，新加脚本记得带上
（只在输出被重定向时改，直接连控制台时不动 —— 那时 CPython 走宽字符 API
本来就正确）。

**PyInstaller 打出来的 exe 版本号会变成 `0.0.0+unknown`。** 因为它默认不复制
dist-info，运行时 `importlib.metadata` 找不到包元数据。必须加 `--copy-metadata`。

**Linux 上拍平 PyInstaller 产物会撞名。** 产物固定是 `<distpath>/<name>/`，
Windows 上目录叫 `mog`、可执行文件叫 `mog.exe`，不冲突；Linux 上两者都是
`mog`，逐个往外搬时第一个就撞上自己。`scripts/build.py` 的 `flatten_dist()`
先挪到临时目录再搬，`tests/unit/test_build_script.py` 盯着这段逻辑。

**CI 上的 CLI 输出带 ANSI 颜色，本地不带 —— 断言前必须剥掉。**
Typer 的 `rich_utils` 里有一句：

```python
FORCE_TERMINAL = True if getenv("GITHUB_ACTIONS") or getenv("FORCE_COLOR") or getenv("PY_COLORS") else None
```

CI 里 `GITHUB_ACTIONS` 恒为 true，于是**强制开终端模式**，输出全是转义序列。
断言 `"─ 选项 ─" in output` 在本地过、在 CI 挂 —— 实际拿到的是
`─ \x1b[1m选项\x1b[0m ─`。

已经在 `tests/unit/test_localize.py` 上炸过一次。**写涉及 CLI 输出的断言时，
先剥 ANSI**（那个文件里的 `_plain()`），并且**本地用 `GITHUB_ACTIONS=true` 跑一遍**：

```bash
GITHUB_ACTIONS=true uv run pytest tests/integration/test_cli.py tests/unit/test_localize.py
```

**`uvicorn.run` 别传字符串。** `uvicorn.run("mograb_api.main:app", ...)` 靠运行时
导入，PyInstaller 静态分析看不到，打出来的 exe 启动就报找不到模块。传 app 对象。

**「构建成功」不等于「产物能用」—— 必须真跑一遍。** rc1 发出去的 CLI 和
桌面端**都是坏的**：SQLAlchemy 按字符串导入驱动包 `aiosqlite`，静态分析看不见，
于是产物能跑 `--version`、能出 `--help`，一碰数据库就
`ModuleNotFoundError`。构建、CI、发布三道关全都没拦住，因为都只验「构建成功」。

现在 `scripts/build.py` 构建完会自动跑冒烟测试（`smoke_test()`），
真的执行产物：验版本号、**数据库读写**、数据目录创建、输出编码；
后端还会起一次服务并带令牌打一个走数据库的端点 ——
**`/health` 不碰数据库，光看它通不出结论**。CI 的 `package-smoke` job 和
Release 工作流都会跑它。

**打包后的 exe 会无视 `PYTHONUTF8` / `PYTHONIOENCODING`。** 实测四种组合
（含 `PYTHONLEGACYWINDOWSSTDIO=0`）全部无效，它按控制台代码页输出，
中文 Windows 上就是 GBK。于是 `--json` 产出的不是合法 JSON，管道也乱码。
**而开发态 `uv run` 是 UTF-8** —— 只有用户拿到的包是坏的，本地测不出来。
修法是代码里显式设，见 `mograb.console.force_utf8_stdio()`。

**PyInstaller 会漏掉动态导入的模块。** 上面那条 aiosqlite 就是。
判断一个包有没有被打进去**不能看 `_internal/` 里有没有同名目录** ——
纯 Python 包会被塞进 PYZ，目录里根本不出现。只能真跑一遍。

**扫文档别把 `node_modules` 扫进来。** 第一版内链校验用 `rglob('*.md')` 一路扫下去，
结果报了 521 条断链 —— 全部来自 `apps/desktop/node_modules/` 里第三方包自带的
README，它们本来就不保证自己的相对链接有效。`scripts/check_docs.py` 里有一份
`SKIP_DIRS`，新加需要排除的目录时改那里。

**改了 `VERSION` 之后必须强制重装工作区包。** editable 安装的元数据是缓存的：
`uv sync` 不会因为 `VERSION` 变了就重装，`.dist-info` 里还是旧版本号。
而 PyInstaller 用 `--copy-metadata` 把那份元数据拷进产物 —— 于是打出来的 exe
报一个**错误的版本号，而且不报错**。CI 是全新环境所以碰不到，本地反复构建时
必踩。`scripts/build.py` 的 `verify_metadata_version()` 现在会拦下来并打印
该执行的重装命令。

**发布说明别用内联 awk 提取。** 原先在 Release 工作流里用 awk 从 CHANGELOG
切段落，正则里的反斜杠要穿过 YAML → bash → awk 三层转义。少一层就变成
`^## [?1.0.0rc3]?`，`[` 不再是转义字符而是字符组 —— 于是匹配不到标题，
`flag` 永远是 0，最后把**整份 CHANGELOG（连版本规划表）**当成发布说明，
而且不报错。现在走 `scripts/release.py notes`，`re.escape` 过的正则，
`tests/unit/test_release_script.py` 盯着。

**PEP 440 和 semver 对预发布版本的写法不一样。** Python 侧是 `1.0.0rc0`，
Node 生态要的是 `1.0.0-rc.0`。项目只有一个 `VERSION` 文件，所以**统一用
PEP 440**，不去转换：转换只会让产物名和包内版本不一致，而换来的好处有限 ——
electron-builder 本来就接受 `1.0.0rc0`（它内部用 `parseInt` 切版本号，
`0rc0` 被截成 `0`，不报错）。

代价是 Windows PE 的 `ProductVersion` 字段：它只能是数值四元组，
所以 `1.0.0rc0` 会被写成 `1.0.0.0`。**`FileVersion` 字段是对的**（保留 `rc0`），
在文件属性里能看到。这是 Windows 的固有限制，不是可以绕过的 bug。

**产物里绝不能带 `data/`。** 程序跑起来会在可执行文件旁边建 `data/`
（数据库、缓存、**API 令牌**）。打包前只要有人跑过一次那个 exe，
这份数据就会被原样打进发布包 —— `data/token` 是访问令牌，
**所有装这个包的用户会共用同一个**，鉴权等于没做。

两道防线：`scripts/build.py` 的 `strip_runtime_data()` 在构建收尾时删掉它
（并打印警告 —— CI 里出现这行日志就说明有人提前跑了 exe），
`apps/desktop/package.json` 的 `extraResources.filter` 里再排一次 `!data/**`。
