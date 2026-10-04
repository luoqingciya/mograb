# ADR-0002　书源版本字段拆分

> 状态：已接受
> 日期：2026-10-04
> 关联：规划书 §7、§13、§53；评估报告 P0-02

---

## 背景

规划书在三个位置使用了**同一字段名 `version`，但含义不同**：

| 位置 | 写法 | `version` 的实际含义 |
|------|------|---------------------|
| §7 书源示例 | `version: 1` + `version_name: 1.0.0` | **Schema 版本**（1） |
| §13 Source 元数据 | `version: 1.2.0` | **书源版本** |
| §53 版本兼容 | `version: 1` + `engine.min_version: 0.1.0` | **Schema 版本**（1） |

§7 试图用 `version` + `version_name` 区分，但这个命名既不自解释
（`version_name` 听起来像「版本的名字」而非「书源版本」），
也与 §13 / §53 的用法直接矛盾。

### 为什么这是阻断性问题

§53 的整个目的是「防止新版 Source 被旧 Core 静默解析错误」。
其检查逻辑是：

```
Schema Version 检查
        ↓
Engine Compatibility 检查
        ↓
Capabilities 检查
```

如果加载器无法确定 `version: 1` 究竟是 Schema 版本还是书源版本 `1`，
那么：

- 可能把 `version: 1.2.0` 当作 Schema 版本 → 解析失败（还好，是显式错误）
- 可能把 `version: 1` 当作书源版本 1 → **Schema 检查被完全跳过**，
  旧引擎会尝试解析新版书源并静默产生错误的提取结果

后者正是 §53 要防的场景。属于数据契约层面的歧义，一旦有书源按错误理解编写，
修正需要破坏性变更。

---

## 选项

### 选项 A：保留 `version` + `version_name`

| 优点 | 缺点 |
|------|------|
| 与 §7 示例一致 | 命名不自解释；与 §13 矛盾；`version_name` 语义模糊 |
| 无需新增字段 | 需要额外文档说明，易被误用 |

### 选项 B：`spec_version` + `version`（本决策）

```yaml
spec_version: 1        # 整数：Source Specification 版本
version: 1.0.0         # 字符串：书源自身的语义化版本
```

| 优点 | 缺点 |
|------|------|
| 两个字段名均自解释 | 与 §7 的示例字面不一致（但语义更清晰） |
| 与 §53 的语义完全对齐 | 需同步更新书源模板与文档 |
| 类型区分明显（int vs str），误用会被 Pydantic 捕获 | |

### 选项 C：`spec_version` + `source_version`

| 优点 | 缺点 |
|------|------|
| 更加显式 | `source.version` 已是书源内部字段，`source_version` 冗余 |
| | 与 §13 的 `version: 1.2.0` 不一致 |

---

## 决策

**采用选项 B。**

```yaml
spec_version: 1        # int，必填，默认 1
version: 1.0.0         # str，必填，必须符合 SemVer
```

### 实现要点

| 项 | 规则 |
|----|------|
| `spec_version` 类型 | `int`，默认 `1` |
| `spec_version` 校验 | 必须等于引擎支持的 `SPEC_VERSION`，否则抛 `SourceUnsupportedError` |
| `version` 类型 | `str`，必须匹配 SemVer（`^\d+\.\d+\.\d+...$`） |
| `version` 校验 | 不符合 SemVer 抛 `SourceSchemaError` |

类型差异（int vs str）本身就是一道防线：
`version: 1` 会被 SemVer 正则拒绝并给出明确错误信息。

### 与 `engine_min_version` / `engine_max_version` 的分工

| 字段 | 回答的问题 |
|------|-----------|
| `spec_version` | 「这份书源遵循哪一版**规范**？」 |
| `version` | 「这份书源是**第几版**？」 |
| `engine_min_version` | 「至少需要哪个**引擎版本**？」 |
| `engine_max_version` | 「最高兼容哪个引擎版本？」 |

---

## 后果

### 正面

- 消除歧义：Schema 检查与引擎兼容检查各司其职，均可独立生效
- 类型安全：`spec_version: "1"` 或 `version: 1` 都会被 Pydantic 明确拒绝
- 命名自解释：新书源作者无需阅读文档即可正确填写

### 负面

- 与规划书 §7 的示例字面不一致 —— 已在
  `docs/source-spec/source-spec-v1.md` 与
  `sources/official/example/source.yaml` 中同步说明
- 若已有按 §7 写法编写的书源，需迁移（当前无存量书源，成本为零）

### 需要跟进

1. `mog source lint` 应在遇到 `version: <int>` 时给出**明确的迁移提示**，
   而非仅报「非法版本号」。建议提示语：
   「检测到 `version` 为整数。若表示规范版本请改用 `spec_version`；
   若表示书源版本请使用语义化版本如 `1.0.0`。」
2. 书源脚手架（`mog source init`）生成的模板必须使用新字段。
