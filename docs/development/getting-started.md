# 开发指南

> 对应[原始规划书](../planning/项目规划书.md)（历史存档，非规范）：§46、§47、§48、§49

---

## 1. 环境准备

### 1.1 前置要求

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | ≥ 3.11 | 使用 `StrEnum`、`datetime.UTC` 等特性 |
| uv | ≥ 0.5 | 依赖与虚拟环境管理 |
| Node.js | ≥ 20 | **仅** Desktop 开发需要 |

> 最终用户**无需**安装 Python、uv 或 Node.js（见[规划书](../planning/项目规划书.md) §57.1）。
> 上述工具仅属于开发与构建链路。

### 1.2 初始化

```bash
git clone https://github.com/luoqingciya/mograb.git
cd mograb

uv sync --all-packages          # 安装核心库 + CLI + API + 开发依赖

uv run pre-commit install       # 安装 Git 钩子
```

### 1.3 验证环境

```bash
uv run mog --version            # mog (MoGrab) 1.0.0rc7
uv run pytest -q                # 786 passed, 1 skipped
uv run ruff check .             # All checks passed!
uv run pyright                  # 0 errors
```

---

## 2. 工作区结构

采用 **uv workspace**（见 [ADR-0001](../architecture/decisions/ADR-0001-monorepo-layout.md)）。

```
pyproject.toml                 工作区根（package = false，不可安装）
├── packages/mograb            核心库
├── apps/cli                   命令行（mog）
└── apps/api                   本地 API（mograb-api）
```

### 2.1 依赖管理

| 位置 | 内容 |
|------|------|
| `pyproject.toml`（根） | 工作区成员声明 + `[dependency-groups] dev` + 全局工具配置 |
| `packages/mograb/pyproject.toml` | 核心库运行时依赖 |
| `apps/*/pyproject.toml` | 应用依赖（通过 `[tool.uv.sources]` 引用工作区内的 `mograb`） |

**添加依赖**：

```bash
uv add --package mograb httpx          # 加到核心库
uv add --package mograb-cli rich       # 加到 CLI
uv add --group dev pytest-benchmark    # 加到开发依赖组
```

### 2.2 `uv.lock` 提交策略

`uv.lock` **必须提交**。CI 使用 `uv sync --locked`，要求 lock 与
`pyproject.toml` 完全一致。

何时需要更新 lock：

| 场景 | 是否需更新 |
|------|-----------|
| 修改任何 `pyproject.toml` 的依赖 | 必须（`uv sync` 会自动更新） |
| 仅修改代码 | 不需要 |
| 想升级依赖版本 | 显式执行 `uv lock --upgrade-package <name>` |

> CI 会因 lock 不一致而失败。提交前请确认 `uv lock --check` 通过。

### 2.3 版本号

版本号只有一个来源：仓库根的 `VERSION` 文件。三个包的 `pyproject.toml` 都用
`dynamic = ["version"]`，构建时通过 hatchling 的 regex source 读这个文件。
运行时从包元数据读（`mograb._version`），所以源码里没有第二份版本号。

```bash
uv run python scripts/version.py show           # 看当前版本
uv run python scripts/version.py check          # 校验格式和来源唯一性
uv run python scripts/version.py set 1.0.0rc7   # 改版本
uv run python scripts/version.py flags          # 输出版本属性（CI 用）
```

`set` 会把输入规范化成 PEP 440 的标准写法（比如 `1.0.0.rc1` 会变成
`1.0.0rc7`）。**改完必须强制重装工作区包**，否则产物带旧版本号且不报错：

```bash
uv sync --all-packages --group build \
  --reinstall-package mograb --reinstall-package mograb-cli --reinstall-package mograb-api
```

`scripts/build.py` 会拦这种情况，版本对不上直接报错。原因见
[CI 与发布 §6](ci.md#6-踩过的坑)。

别在源码里写 `__version__ = "..."`，`scripts/version.py check` 会报错，
`tests/unit/test_version.py` 也会失败。

---

## 3. 常用命令

```bash
# 测试
uv run pytest                                  # 全部
uv run pytest tests/unit -q                    # 仅单元测试
uv run pytest -m "not network"                 # 排除需网络的测试
uv run pytest --cov --cov-report=term-missing  # 覆盖率

# 代码质量
uv run ruff check . --fix                      # lint + 自动修复
uv run ruff format .                           # 格式化
uv run pyright                                 # 类型检查

# CLI
uv run mog --help
uv run mog source lint tests/fixtures/example-source/source.yaml   # 只查规则能否编译
uv run mog source test tests/fixtures/example-source               # 真跑一遍提取
uv run mog find 关键词                                             # 搜本地已下载的正文
uv run mog task watch                                             # 实时跟踪任务（需 server 在跑）
uv run mog config path

# API
uv run mograb-api                              # 启动（127.0.0.1:48721）
uv run mog server token                        # 打印访问令牌（手工 curl 用）
uv run python -c "from mograb_api.main import create_app; print(len(create_app().openapi()['paths']))"
```

接口都要求 `Authorization: Bearer <token>`，令牌在 `data/token`，首次启动时
自动生成。CLI 和 Desktop 会自己读，平时不用管；只有手工调接口才需要：

```bash
TOKEN=$(uv run mog server token)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:48721/api/v1/sources
```

浏览器里打开 `http://127.0.0.1:48721/docs` 不需要令牌，可以直接看接口文档。

---

## 4. 测试策略

测试分四层。

| 层 | 目录 | 标记 | 说明 |
|----|------|------|------|
| Unit | `tests/unit/` | `@pytest.mark.unit` | 纯函数与模型：Source Schema、Extractor、Transformer、Content Cleaner、Chapter Identity、Task 状态机、文件名模板 |
| Integration | `tests/integration/` | `@pytest.mark.integration` | 跨层协作：API 应用、Storage ↔ Domain |
| Fixture | `tests/source/` | `@pytest.mark.source` | 真实 HTML 快照 → 书源规则 → 期望结果（**完全离线**） |
| E2E | `tests/e2e/` | `@pytest.mark.e2e` | CLI → API → Task → DB → Export（待补） |

### 4.1 离线优先

测试默认离线。需要真实网络的测试必须标 `@pytest.mark.network`，CI 里默认跳过。

书源测试用 `tests/fixtures/` 下的 HTML 快照。站点改版后先用 fixture 复现问题，
再改规则。

### 4.2 数据目录隔离

`tests/conftest.py` 里有个 autouse fixture，会把 `MOGRAB_HOME` 指到临时目录。
不加这个的话，任何调用 `Paths.ensure()` 的测试（比如 API 冒烟测试触发 lifespan）
都会在仓库根建出 `data/` 来。

要测默认解析行为的用例可以自己 `monkeypatch.delenv("MOGRAB_HOME")` 覆盖掉，
`tests/unit/test_paths.py` 就是这么做的。

### 4.3 覆盖率门槛

`fail_under = 70`。新增功能要带测试；纯骨架代码（只有 `NotImplementedError`
的那些）不算。

---

## 5. 代码规范

要求：type hints、public API 的 docstring、小函数、依赖倒置。

### 5.1 强制项

| 项 | 要求 |
|----|------|
| 类型标注 | 所有公开函数必须有完整标注 |
| Docstring | 所有 public API 必须有；说明「为什么」而非仅「做什么」 |
| 文件头 | `# SPDX-License-Identifier: GPL-3.0-only` |
| 行宽 | 100 |
| 导入 | 由 Ruff 的 isort 规则管理 |

### 5.2 领域层额外约束

`mograb.domain` **只允许**导入 pydantic 与标准库。禁止导入 httpx / sqlalchemy /
fastapi 等基础设施库。这是架构边界的核心（见架构总览 §3.2）。

### 5.3 pre-commit 钩子

| 钩子 | 作用 |
|------|------|
| `trailing-whitespace` / `end-of-file-fixer` | 文件卫生 |
| `check-yaml` / `check-toml` / `check-json` | 配置文件语法 |
| `check-added-large-files` | 阻止 >1MB 文件入库 |
| `detect-private-key` | 阻止密钥泄漏 |
| `ruff` / `ruff-format` | lint + 格式化 |
| `pyright` | 类型检查（仅核心包） |
| `source-lint` | 校验改动的书源 YAML |

---

## 6. Git 分支策略

**不搞过于复杂的 Git Flow。**

```
main         唯一长期分支。PR 都合到这里，发布也从这里打 tag
feature/*    新功能
fix/*        缺陷修复
release/*    发布准备（可选，通常直接在 main 上打 tag）
```

**没有 `develop` 分支** —— 早期文档里写过，但仓库从来只有 `main`。
照着那份文档做的人会在第一步就卡住。

### 6.1 提交信息

采用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

类型：feat | fix | docs | style | refactor | perf | test | build | ci | chore
范围：core | source | network | task | storage | content | export | cli | api | desktop | docs
```

示例：

```
feat(source): 支持 JSONPath 提取规则
fix(network): 修正 GBK 站点编码探测
docs(spec): 冻结 Source Specification v1
```

### 6.2 版本与发布

各里程碑的**实际**达成情况看 [项目进度](../progress.md) —— 那里是唯一出处，
这里不再重复维护一份状态表（之前散在四处，改一处忘三处）。

发版流程见 [CI 与发布 §3](ci.md#3-发布流程)。要点：

```bash
uv run python scripts/version.py set X.Y.Z   # 改 VERSION
uv sync --all-packages --group build \
  --reinstall-package mograb --reinstall-package mograb-cli --reinstall-package mograb-api
git commit -am "chore(release): ..."
git tag vX.Y.Z && git push origin vX.Y.Z     # 推 tag 即发布
```

版本号里带 `a` / `b` / `rc` / `dev` 时会自动标成 GitHub prerelease。

---

## 7. 贡献流程

1. Fork 并从 `main` 创建 `feature/*` 分支
2. 实现功能 + 补充测试
3. 本地通过全部检查：
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
   uv run python scripts/check_docs.py    # 改过文档才需要
   ```
4. 提交 PR 到 `main`，说明动机、方案与测试情况
5. 涉及架构决策的改动，需同时提交 ADR

### 7.1 书源

书源不进这个仓库，`sources/` 已经在 `.gitignore` 里，是你本地的开发目录。

如果改的是 linter、提取器、变换算子这类框架能力，欢迎提 PR。
这类改动需要带上 `tests/fixtures/` 下的测试数据，结构是：

```
tests/fixtures/<name>-source/
├── source.yaml
├── README.md
└── fixtures/
    ├── search.html
    ├── book.html
    └── chapter.html
```

并附带 `tests/source/test_<name>_source.py`。
`tests/fixtures/example-source/` 就是照着这个来的。

如果只是想加一个新站点的书源，不用提 PR，自己留着用就行。

---

## 8. 参考文档

| 文档 | 内容 |
|------|------|
| [架构总览](../architecture/overview.md) | 分层、边界、数据流 |
| [Source Specification v1](../source-spec/source-spec-v1.md) | 书源规范 |
| [Domain Model v1](../domain-model/domain-model-v1.md) | 领域模型 |
| [Storage v1](../storage/storage-v1.md) | 表结构 |
| [API v1](../api/api-v1.md) | 接口契约 |
| [CI](ci.md) | 持续集成 |
