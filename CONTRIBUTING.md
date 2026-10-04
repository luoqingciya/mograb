# 贡献指南

感谢你考虑为 MoGrab 贡献代码或书源。

---

## 目录

- [行为准则](#行为准则)
- [我可以贡献什么](#我可以贡献什么)
- [开发环境](#开发环境)
- [代码规范](#代码规范)
- [提交与 PR](#提交与-pr)
- [贡献书源](#贡献书源)
- [贡献文档](#贡献文档)
- [许可证](#许可证)

---

## 行为准则

参与本项目即表示你同意遵守 [行为准则](CODE_OF_CONDUCT.md)。

---

## 我可以贡献什么

| 类型 | 说明 | 难度 |
|------|------|------|
| 报告缺陷 | 提交 Issue，附最小复现 | 低 |
| 改进文档 | 修正错误、补充示例、澄清歧义 | 低 |
| 贡献书源 | 编写并测试新书源 | 中 |
| 修复缺陷 | 从 `good first issue` 开始 | 中 |
| 实现功能 | 参考 [开发优先级](docs/architecture/overview.md#8-开发优先级) | 中高 |
| 架构决策 | 提交 ADR 讨论 | 高 |

**优先事项**：请遵循规划书的开发优先级
（Source Spec → Domain Model → Parser → HTTP → Storage → Task → Export → API → CLI → Desktop）。

> **不要先开发 Electron UI。** UI 是最容易看到成果、但最难决定核心架构的部分。

---

## 开发环境

### 前置要求

| 工具 | 版本 |
|------|------|
| Python | ≥ 3.11 |
| uv | ≥ 0.5 |
| Node.js | ≥ 20（**仅** Desktop 开发需要） |

### 初始化

```bash
git clone https://github.com/<your-fork>/mograb.git
cd mograb

uv sync --all-packages
uv run pre-commit install
```

### 验证

```bash
uv run mog --version
uv run pytest -q
uv run ruff check .
uv run pyright
```

### 常用命令

```bash
uv run pytest tests/unit -q                    # 仅单元测试
uv run pytest -m "not network"                 # 排除需网络的测试
uv run pytest --cov --cov-report=term-missing  # 覆盖率
uv run ruff check . --fix                      # lint + 自动修复
uv run ruff format .                           # 格式化
```

详见 [开发指南](docs/development/getting-started.md)。

---

## 代码规范

### 强制要求

| 项 | 要求 |
|----|------|
| 类型标注 | 所有公开函数必须有完整标注 |
| Docstring | 所有 public API 必须有，说明**为什么**而非仅「做什么」 |
| 文件头 | `# SPDX-License-Identifier: GPL-3.0-only` |
| 行宽 | 100 字符 |
| 覆盖率 | 新增功能需附带测试（项目门槛 70%） |

### 架构边界（重要）

`mograb.domain` **只允许**导入 pydantic 与标准库。禁止导入
httpx / sqlalchemy / fastapi 等基础设施库。

其他边界见[架构总览 §3](docs/architecture/overview.md#3-架构边界不可越权)。

**禁止的越权示例**：

```python
# 错误写法：Exporter 直接请求网络
class MyExporter:
    async def export(self, book, chapters, target):
        response = await httpx.get(...)  # 违反边界


# 错误写法：Source 直接操作数据库
class MySourceEngine:
    async def search(self, source, keyword):
        await self.book_repo.save(...)  # 违反边界
```

### 提交前自检

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
```

---

## 提交与 PR

### 分支策略

```
main         稳定版本
develop      PR 的目标分支
feature/*    新功能
fix/*        缺陷修复
release/*    发布准备
```

### 提交信息

采用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>
```

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档 |
| `refactor` | 重构（不改变行为） |
| `perf` | 性能优化 |
| `test` | 测试 |
| `build` / `ci` | 构建与 CI |
| `chore` | 杂项 | | scope | 范围 |
|-------|------|
| `core` `source` `network` `task` `storage` `content` `export` | 核心模块 |
| `cli` `api` `desktop` | 应用 |
| `spec` `docs` | 规范与文档 |

示例：

```
feat(source): 支持 JSONPath 提取规则
fix(network): 修正 GBK 站点编码探测
docs(spec): 冻结 Source Specification v1
```

### PR 检查清单

- [ ] 从 `develop` 创建分支
- [ ] 代码通过全部本地检查
- [ ] 新增/修改的功能有对应测试
- [ ] 涉及公开接口变更时同步更新 `docs/`
- [ ] 涉及架构决策时提交 ADR（见 `docs/architecture/decisions/README.md`）
- [ ] 提交信息符合 Conventional Commits
- [ ] 未提交密钥、本地配置或大文件

---

## 写书源

书源是本项目最重要的产出，但**不进这个仓库** —— 涉及第三方站点的抓取规则
不适合随主仓库分发。`sources/` 已经在 `.gitignore` 里，是纯本地的开发目录。

要分享书源，直接发 `source.yaml` 文件，或者打包成 `.mgs`（格式见[规范](docs/source-spec/source-spec-v1.md) §11）。
想在本地留个备份，自己开个私有仓库放着。

### 目录结构

本地开发时按这个结构放，`mog source lint` 和 fixture 测试都认：

```
sources/<id>/
├── source.yaml          书源定义
├── README.md            说明：站点、能力、注意事项
└── fixtures/
    ├── search.html      搜索结果页快照
    ├── book.html        书籍详情页快照
    └── chapter.html     章节正文页快照
```

完整的参考实现在 `tests/fixtures/example-source/`，可以直接拷走改。

### 步骤

1. **阅读规范**：[Source Specification v1](docs/source-spec/source-spec-v1.md)

2. **编写书源**。注意两个版本字段语义不同：
   ```yaml
   spec_version: 1        # 规范版本（整数）
   version: 1.0.0         # 书源自身版本（语义化版本）
   ```

3. **收集 fixture**：把真实的页面 HTML 保存到 `fixtures/`
   （**务必移除 Cookie、Token、个人信息**）

4. **静态校验**：
   ```bash
   uv run mog source lint sources/<id>/source.yaml
   ```
   必须输出 `Result: READY`。

5. **跑 fixture 测试**：参考 `tests/source/test_example_source.py` 写一份，
   然后 `uv run pytest tests/source -v`。

### 想给项目提交书源相关代码

如果改的是 linter、提取器、变换算子这类**框架能力**，欢迎提 PR ——
这类改动需要带上 `tests/fixtures/` 下的测试数据。

如果只是想加一个新站点的书源，不用提 PR，自己留着就行。

### 书源要求

| 要求 | 说明 |
|------|------|
| 不硬编码 UA | 使用 `{{user_agent}}` |
| 声明权限 | `permissions.network` 列出所有访问域名 |
| 声明清洗规则 | `content.clean.remove` 至少包含 `script` 与 `style` |
| 不含敏感信息 | fixture 中不得有 Cookie / Token / 个人数据 |
| 附带 README | 说明站点、支持的能力、已知限制 |

### 常见问题

| 问题 | 处理 |
|------|------|
| 站点用 GBK 编码 | 引擎自动探测；如失败可在 `request.encoding` 强制指定 |
| 目录倒序 | 设置 `result.reverse: true` |
| 标题被拼成 URL | 检查 `url_join`；v1 仅在值「像 URL」时拼接 |
| 正文含广告 | 在 `clean.remove` 中加入对应选择器 |

---

## 贡献文档

文档改进同样是重要贡献。请特别关注：

- **规范文档**（`docs/source-spec/` 等）的**歧义**与**遗漏** —— 这类问题比错误更危险
- 示例代码是否可直接运行
- 术语是否前后一致

> 若发现规范中存在需要裁决的歧义，请提交 ADR 而非直接修改规范。

---

## 许可证

贡献即表示你同意以 [GPL-3.0-only](LICENSE) 授权你的贡献。

若你的贡献引入新的第三方依赖，请同步更新
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)，并确认其许可证与
GPL-3.0-only **兼容**。

**注意**：AGPL-3.0 依赖会给项目带来额外分发义务，引入前请先讨论。
