# 开发指南

> 对应[原始规划书](../planning/项目规划书.md)（历史存档，非规范）：§46、§47、§48、§49

---

## 1. 环境准备

### 1.1 前置要求

| 工具 | 版本 | 说明 |
|------|------|------|
| Rust (`rustc` / `cargo`) | ≥ 1.85（支持 `edition = "2024"`） | 附带 `rustfmt` 与 `clippy` |
| Node.js | ≥ 20 | **仅** Desktop 开发需要 |

> 最终用户**无需**安装 Rust 或 Node.js —— Release 产出原生单二进制与 Electron 安装包。
> 上述工具仅属于开发与构建链路。

### 1.2 初始化

```bash
git clone https://github.com/luoqingciya/mograb.git
cd mograb

cargo fetch                     # 拉取工作区依赖（可选，build/test 会自动拉取）
pre-commit install              # 安装 Git 钩子（可选）
```

### 1.3 验证环境

```bash
cargo run --bin mog -- --version     # mog (MoGrab) 1.0.0-rc11
cargo run --bin mog -- init          # 建出数据目录，幂等
cargo test --workspace               # 运行全部单元 / 集成 / CLI 测试
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
```

---

## 2. 工作区结构

采用 **Cargo workspace**（见 [ADR-0001](../architecture/decisions/ADR-0001-monorepo-layout.md)）。

```
Cargo.toml                     工作区根（[workspace.package] + [workspace.dependencies]）
├── crates/mograb-core         核心库（领域模型、书源引擎、网络、存储、任务、导出）
├── crates/mograb-api          本地 REST API / SSE 服务（Axum，产物 mograb-api）
└── crates/mograb-cli          命令行（clap，产物 mog）
```

### 2.1 依赖管理

| 位置 | 内容 |
|------|------|
| `Cargo.toml`（根） | 工作区成员声明、`[workspace.package]` 与共享 `[workspace.dependencies]` |
| `crates/*/Cargo.toml` | 各 crate 依赖（通过 `*.workspace = true` 引用工作区版本） |

### 2.2 `Cargo.lock` 提交策略

`Cargo.lock` **必须提交**。CI 使用 `--locked`，要求锁文件与 `Cargo.toml` 完全一致。

### 2.3 版本号

版本号在根 [`Cargo.toml`](../../Cargo.toml)（`[workspace.package].version`）与根 [`VERSION`](../../VERSION)
保持一致；`crates/mograb-core` 的单元测试会自动校验两处完全匹配，CI Release 门禁也会核对 Tag、
`VERSION` 与 `Cargo.toml` 三者一致。

---

## 3. 常用命令

```bash
# 测试与质量检查
cargo test --workspace                                      # 全部测试
cargo test -p mograb-core                                   # 仅核心库
cargo clippy --workspace --all-targets -- -D warnings       # 严格 lint
cargo fmt --all                                             # 格式化
cargo fmt --all -- --check                                  # 格式检查

# CLI
cargo run --bin mog -- --help
cargo run --bin mog -- source lint tests/fixtures/example-source/source.yaml   # 校验规则
cargo run --bin mog -- source test tests/fixtures/example-source               # 跑离线夹具
cargo run --bin mog -- find 关键词                                             # 搜本地已下载的正文
cargo run --bin mog -- task watch                                              # 实时跟踪任务（需 server 在跑）
cargo run --bin mog -- config path

# API
cargo run --bin mograb-api                                  # 启动（127.0.0.1:48721）
cargo run --bin mog -- server token                         # 打印访问令牌（手工 curl 用）
```

接口都要求 `Authorization: Bearer <token>`，令牌在 `data/token`，首次启动时
自动生成。CLI 和 Desktop 会自己读，平时不用管；只有手工调接口才需要：

```bash
TOKEN=$(cargo run --quiet --bin mog -- server token)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:48721/api/v1/sources
```

浏览器里打开 `http://127.0.0.1:48721/docs` 不需要令牌，可以直接看 Swagger UI 文档。

---

## 4. 测试策略

测试默认完全离线，并把 `MOGRAB_HOME` 隔离到 `tempfile::TempDir`，避免污染仓库根的 `data/` 目录：

| 层 | 位置 | 说明 |
|----|------|------|
| 核心库单测 & 集成测 | `crates/mograb-core/src/**` | Schema、Extractor（CSS/XPath/JSONPath/Regex）、Transformer、Cleaner、EPUB/TXT/MD 导出、SQLite 仓储、Task 状态机与模拟 HTTP 端到端下载 |
| API 集成测 | `crates/mograb-api/src/lib.rs` | `/health`、Bearer 鉴权、24 条 OpenAPI 路径、SSE 事件流、任务状态机与错误码映射 |
| CLI 集成测 | `crates/mograb-cli/tests/cli_integration.rs` | 直接执行编译出的 `mog` 二进制，覆盖 exit code、UTF-8 `--json`、`source lint/test/install` |
| Desktop 测试 | `apps/desktop/test/*.test.mjs` | Tauri 前端 SSE 解析等单元测试 |

---

## 5. 代码规范

| 项 | 要求 |
|----|------|
| 警告零容忍 | `cargo clippy --workspace --all-targets -- -D warnings` |
| 格式化 | `cargo fmt --all -- --check` |
| 文件头 | `// SPDX-License-Identifier: GPL-3.0-only` |
| 领域层边界 | `crates/mograb-core/src/domain` 不依赖网络/存储实现 |

### 5.1 pre-commit 钩子

| 钩子 | 作用 |
|------|------|
| `trailing-whitespace` / `end-of-file-fixer` | 文件卫生 |
| `check-yaml` / `check-toml` / `check-json` | 配置文件语法 |
| `check-added-large-files` | 阻止 >1MB 文件入库 |
| `detect-private-key` | 阻止密钥泄漏 |
| `cargo-fmt` / `cargo-clippy` | Rust 格式化与 lint |
| `source-lint` | 校验改动的书源 YAML |

---

## 6. Git 分支与提交规范

```
main         唯一长期分支。PR 都合到这里，发布也从这里打 tag
feature/*    新功能
fix/*        缺陷修复
release/*    发布准备（可选，通常直接在 main 上打 tag）
```

采用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

类型：feat | fix | docs | style | refactor | perf | test | build | ci | chore
范围：core | source | network | task | storage | content | export | cli | api | desktop | docs
```

发版只需同步 `VERSION` 与 `Cargo.toml` 版本号、更新 `CHANGELOG.md` 后打 `v*` tag 推送即可，详情见 [CI 与发布](ci.md)。

---

## 7. 贡献流程

1. Fork 并从 `main` 创建 `feature/*` 分支
2. 实现功能 + 补充测试
3. 本地通过全部检查：
   ```bash
   cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
   python3 scripts/check_docs.py    # 改过文档才需要
   ```
4. 提交 PR 到 `main`，说明动机、方案与测试情况
5. 涉及架构决策的改动，需同时提交 ADR

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
