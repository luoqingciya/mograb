# 持续集成与发布

> 对应[原始规划书](../planning/项目规划书.md)（历史存档，非规范）：§48、§57
> 工作流：`.github/workflows/ci.yml`、`.github/workflows/release.yml`

---

## 1. CI 流程

```
push / PR → main, develop
        ↓
┌───────────────────────────────────────────┐
│ lint          ruff check + format --check │
│               + 文档内链校验               │
│ version       VERSION 格式与来源唯一性     │
│ type-check    pyright                     │
│ test          矩阵：{3.11,3.12} × {linux,windows} │
│ source-lint   tests/fixtures 下的参考书源   │
│ build         uv build --all-packages     │
│ desktop       npm ci + tsc 类型检查与编译  │
└───────────────────────────────────────────┘
```

### 1.1 设计要点

| 决策 | 理由 |
|------|------|
| `uv sync --locked` | 强制 lock 与 pyproject 一致，防止本地能跑 CI 不能跑 |
| 测试矩阵含 Windows | 桌面端只支持 Windows，路径和编码问题要早发现 |
| desktop job 设 `ELECTRON_SKIP_BINARY_DOWNLOAD` | 类型检查和 tsc 编译用不到 Electron 二进制，省一次上百兆的下载 |
| `version` 独立成 job | 版本号来源出问题会让发版直接失败，值得单独可见 |
| 文档内链校验并入 `lint` | 纯标准库脚本，不需要单独装环境；归在 lint 语义下也说得通 |
| `source-lint` 独立成 job | 书源问题与代码问题分开定位 |
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

# 构建
uv build --all-packages --out-dir dist
```

---

## 3. 发布流程

### 3.1 版本号

版本号只有一个来源：仓库根的 `VERSION` 文件。三个包构建时都读它。

发版前先改版本号：

```bash
uv run python scripts/version.py set 0.1.0     # 从 0.1.0.dev0 转正式版
uv run python scripts/version.py check         # 确认来源唯一、格式合规
```

`check` 会验证三件事：VERSION 内容符合 PEP 440、三个包的 `pyproject.toml`
用的是 dynamic version 且指向同一个文件、源码里没有硬编码的 `__version__`。

改完提交，再打 tag。tag 名要和 VERSION 一致，Release 工作流会用它命名产物。

### 3.2 触发

```bash
git tag v0.1.0
git push origin v0.1.0
```

也可以在 Actions 页面手动跑（选 Release → Run workflow），填版本号即可。
手动触发同样会校验版本号与 `VERSION` 文件是否一致，所以适合拿来做预演 ——
但注意它最后也会建一个 draft release，预演完记得删掉。

### 3.3 流水线

```
Verify（质量门禁）
    ↓
┌──────────────────────┬──────────────────────┬──────────────────────┐
│ CLI Windows          │ Desktop Windows      │ CLI Linux            │
│ PyInstaller onedir   │ backend + Electron   │ PyInstaller onedir   │
│ → ZIP                │ → ZIP + NSIS         │ → tar.gz             │
└──────────────────────┴──────────────────────┴──────────────────────┘
    ↓
SHA256SUMS.txt
    ↓
GitHub Release（draft）
```

### 3.4 产物清单

| 产物 | 类型 | 说明 |
|------|------|------|
| `MoGrab-CLI-v0.1.0-win-x64.zip` | 目录型便携 CLI | 解压即用，含完整运行时 |
| `MoGrab-v0.1.0-win-x64.zip` | Portable Desktop | Electron + 后端 sidecar |
| `MoGrab-Setup-v0.1.0-win-x64.exe` | NSIS 安装包 | 安装 / 卸载 / 快捷方式 |
| `MoGrab-CLI-v0.1.0-linux-x64.tar.gz` | Linux CLI | |
| `SHA256SUMS.txt` | 校验和 | 用于验证下载完整性 |

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
# 安装打包依赖
uv sync --all-packages --group build

# 构建 CLI（PyInstaller onedir）
uv run python scripts/build.py cli --version 0.1.0

# 构建 Desktop 后端 sidecar
uv run python scripts/build.py backend --version 0.1.0

# 生成校验和
uv run python scripts/release.py checksums --dir release-artifacts

# 校验
uv run python scripts/release.py verify --dir release-artifacts

# 提取发布说明
uv run python scripts/release.py notes --version 0.1.0

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
| Desktop CI（lint/build） | Electron 侧的 lint 与打包验证 | CI |
| 缓存 CI 产物 | 加速重复构建 | — |

---

## 6. 踩过的坑

这几条都是实际踩出来的，改回去会再挂一次。

**`astral-sh/setup-uv` 别用 `@v8` 以上。** 这个仓库从 v8 开始不再打 major tag，
只有 `v10.2.0` 这种具体版本号。引用 `@v10` 会直接 Not Found，job 在
"Set up job" 阶段就挂，而且错误信息里看不出原因 —— 表现是九个 job 同时秒失败。
当前用 `@v7`，这是最后一个有 major tag 的版本。

**Windows runner 上跑 Python 脚本要处理编码。** 控制台默认 cp1252，
`print` 中文直接抛 `UnicodeEncodeError`。`scripts/` 下的脚本开头都有
`_force_utf8_output()`，新加脚本记得带上。

**PyInstaller 打出来的 exe 版本号会变成 `0.0.0+unknown`。** 因为它默认不复制
dist-info，运行时 `importlib.metadata` 找不到包元数据。必须加 `--copy-metadata`。

**Linux 上拍平 PyInstaller 产物会撞名。** 产物固定是 `<distpath>/<name>/`，
Windows 上目录叫 `mog`、可执行文件叫 `mog.exe`，不冲突；Linux 上两者都是
`mog`，逐个往外搬时第一个就撞上自己。`scripts/build.py` 的 `flatten_dist()`
先挪到临时目录再搬，`tests/unit/test_build_script.py` 盯着这段逻辑。

**`uvicorn.run` 别传字符串。** `uvicorn.run("mograb_api.main:app", ...)` 靠运行时
导入，PyInstaller 静态分析看不到，打出来的 exe 启动就报找不到模块。传 app 对象。

**扫文档别把 `node_modules` 扫进来。** 第一版内链校验用 `rglob('*.md')` 一路扫下去，
结果报了 521 条断链 —— 全部来自 `apps/desktop/node_modules/` 里第三方包自带的
README，它们本来就不保证自己的相对链接有效。`scripts/check_docs.py` 里有一份
`SKIP_DIRS`，新加需要排除的目录时改那里。
