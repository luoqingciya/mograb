# ADR-0001　Monorepo 布局与包划分

> 状态：已接受
> 日期：2026-10-04
> 关联：规划书 §4、§5、§59；评估报告 P0-01

---

## 背景

规划书在三个位置给出了**互相冲突**的仓库结构，且冲突是实质性的
（包数量、命名规范、模块划分均不一致）：

| 位置 | 结构 |
|------|------|
| §4 | `packages/mograb-core/`、`mograb-source/`、`mograb-storage/`、`mograb-http/`、`mograb-parser/`、`mograb-task/`、`mograb-exporter/` —— 7 个可分发包 |
| §5 | 单个 `packages/mograb-core/mograb/{domain,source,network,task,storage,content,export,config,logging}` |
| §59 | `packages/core/`、`source/`、`network/`、`parser/`、`task/`、`storage/`、`exporter/` —— 7 个目录，无包名规范 |

矛盾点：

- §4 有 `mograb-http`，§59 是 `network`，§5 是 `network` —— 命名不统一
- §4/§59 无 `content` 包，§5 有 `content` —— 模块划分不统一
- §4/§59 的 7 个包 vs §5 的 1 个包 —— 层级模型不同

**这是阻断性的**：导入路径、构建配置、CI 缓存策略、依赖声明全部依赖此决策，
且一旦落地后重构成本极高。

---

## 选项

### 选项 A：7 个独立可分发包（§4 / §59）

| 优点 | 缺点 |
|------|------|
| 理论上每个模块可单独发布复用 | 7 份 `pyproject.toml`、7 组版本号 |
| 强制模块间显式依赖声明 | 跨包依赖约束复杂（`mograb-task` 依赖 `mograb-storage` 与 `mograb-network`） |
| 编译期即可发现循环依赖 | 每次改动可能需同时 bump 多个包版本 |
| | 而这些模块（network/task/storage）**实际不具备独立复用价值**——它们服务于同一产品的同一流程 |

### 选项 B：纯单包（§5）

| 优点 | 缺点 |
|------|------|
| 依赖管理最简单 | 丢失 `apps/` 与 `packages/` 的语义分离 |
| 导入路径短、重构成本低 | 未来若某模块需独立发布，需较大重构 |
| 构建快 | |

### 选项 C：单核心包 + 双应用（本决策）

```
packages/mograb/        唯一核心库（模块划分取自 §5）
apps/cli/               mograb-cli
apps/api/               mograb-api
apps/desktop/           Electron
```

| 优点 | 缺点 |
|------|------|
| 取 §5 的具体模块划分（更可落地） | 核心库内部模块无法单独发布 |
| 保留 §59 的 `packages/` 与 `apps/` 语义分离 | |
| uv workspace 原生支持，零额外工具 | |
| 未来可平滑提升某模块为独立 workspace 成员 | |
| 模块边界通过「领域层不依赖基础设施」的导入约束保证，而非包边界 | |

---

## 决策

**采用选项 C。**

理由：

1. **§4/§59 的 7 包方案在当前阶段是过度设计。** 独立发布能力是「理论上可能有用」，
   而非「已识别的需求」。为不存在的需求付出持续成本（版本管理、依赖约束）
   不符合项目「个人工具」的定位。
2. **§5 的模块划分是三者中最具体的**，且与 §59 的目录名基本同构
   （只是层级表达不同）。以 §5 为蓝本、置于 §59 的目录语义下，是自然的融合。
3. **模块边界不依赖包边界。** §61 要求的架构边界（如「Exporter 不得请求网络」）
   通过**导入约束**保证（`mograb.export` 不导入 `mograb.network`），
   而非通过物理分包。包边界带来的强制力并非不可替代。
4. **`apps/` 与 `packages/` 分离保留了演进空间。** 若未来某个模块确需独立发布，
   将其从 `packages/mograb/src/mograb/X` 提升为 `packages/mograb-X/` 是机械操作。

### 命名规范

| 项目 | 规范 |
|------|------|
| 核心库分发包名 | `mograb` |
| 核心库导入名 | `mograb` |
| CLI 分发包名 | `mograb-cli`，导入名 `mograb_cli`，命令 `mog` |
| API 分发包名 | `mograb-api`，导入名 `mograb_api`，命令 `mograb-api` |
| 源码布局 | **src-layout**（`src/<pkg>/`） |

src-layout 的理由：防止「未安装却能导入」的假象——测试必须在包已安装的前提下运行，
更贴近真实使用。

---

## 后果

### 正面

- 依赖管理简单：`uv sync` 一次装齐全部
- 重构成本低：跨模块移动代码不涉及版本 bump
- CI 简单：单一 lockfile

### 负面

- 核心库无法按模块单独发布（当前无此需求）
- 模块边界依赖代码审查而非编译期强制

### 需要跟进

1. **建立导入边界检查**：考虑在 CI 中加入规则，禁止
   `mograb.domain` 导入 pydantic 之外的第三方库、
   禁止 `mograb.export` 导入 `mograb.network`。
   可考虑使用 `import-linter`。
2. **若核心库规模显著增长**（如超过 30 个模块），重新评估是否提升为多包。
