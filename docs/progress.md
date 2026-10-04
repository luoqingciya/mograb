# 项目进度

> 更新于 2026-10-04 · 对应版本 `0.1.0.dev0`
>
> **这份文档是进度的唯一出处。** README、CHANGELOG、架构总览里只放一句话摘要，
> 细节都看这里 —— 之前进度信息散在四个文件里，改一处忘三处。

## 一句话

核心链路已经跑通：**能完整下载一本小说**（搜索 → 登记 → 目录 → 增量比对 →
抓正文 → 清洗校验 → 落库 → 导出）。命令行和本地 API 都能用，桌面端还没开始。

## 质量指标

| 指标 | 当前 | 怎么刷新 |
|------|------|---------|
| 测试用例 | 439 | `uv run pytest --collect-only -q \| tail -1` |
| 覆盖率 | 83% | `uv run pytest --cov --cov-report=term` |
| 覆盖率门槛 | 70%（`fail_under`） | 见根 `pyproject.toml` |
| 源码行数 | 约 11,300 | — |
| 测试行数 | 约 4,600 | — |
| 未实现桩 | 0 | `grep -rn NotImplementedError packages apps` |
| CI | 九项全绿 | `gh run list` |

## 里程碑

对照规划书 §57 的版本规划。

| 版本 | 主题 | 状态 | 差什么 |
|------|------|------|-------|
| v0.1.0 | Core Prototype | **达成** | — |
| v0.2.0 | Task System | **基本达成** | 大量章节的稳定性没在真实站点验证过 |
| v0.3.0 | Source Ecosystem | **部分** | Source Registry、`source test`、版本回滚 |
| v0.4.0 | API | **达成**（除认证） | API 认证 |
| v0.5.0 | CLI | **达成** | 独立可执行包的跨机器验证 |
| v0.6.0 | Desktop | **未开始** | 全部 |
| v0.7.0 | EPUB / Polish | **部分** | 封面、元数据模板、性能优化 |
| v1.0.0 | Stable | 未到 | — |

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

```
✓ Source Linter          ✗ Source Test（CLI 命令）
✓ Fixture Test           ✗ Registry
✓ Source Version         ✗ Update / Rollback
✓ Install
```

### v0.4.0 逐项

```
✓ FastAPI                ✓ API Error Model
✓ /api/v1                ✓ OpenAPI
✓ SSE                    ✗ 认证
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
| `apps/api` | 完成 | 22 个端点 + SSE，缺认证 |
| `apps/desktop` | 骨架 | 主进程 / preload / 静态页，UI 未接 |

## 已知缺口

按影响排。

### 高

**API 没有认证。** 当前只靠 CORS。`localhost` 不等于安全 —— 浏览器里的页面
能发简单请求（不需要预检）打到 `127.0.0.1:48721`，这是本地 CSRF。
做法已经定了：随机 token 写进 `config.toml`，CLI 和 Desktop 读它。
**v0.4.0 正式对外之前必须补上。**

**桌面端没开始。** 这是 v0.6.0 的全部内容，也是「最终产品形态」里唯一空着的一角。

**所有测试都是离线的。** fixture 测试用的是 HTML 快照，没有在真实站点上跑过
完整下载。接口之间对得上（端到端测试证明了这一点），但真实站点的
编码、反爬、目录结构差异都还没遇到过。这是下一个该验证的事。

### 中

**Source Registry 没实现。** 书源的分发、安装、更新、回滚这条链路只有本地安装
（`mog source install <file>`）能用。规划书 §13、§55、§56 描述的远端流程都还是空的。

**Alembic 迁移目录没建。** 依赖声明了，但 `alembic/` 目录和首个迁移脚本还没有。
现在 schema 是 `create_all` 建的，改表就得手写迁移。

**EPUB 的封面和元数据模板没做。** 导出结构是规范的（有离线测试验证
`mimetype` 顺序、OPF、NCX），但封面图不下载，元数据也不能按模板配。

### 低

**`mog source test` 没实现。** fixture 测试在 `tests/` 里有基础设施，
但没做成 CLI 命令。规划书 §12 列了这个命令。

**`.mgs` 打包格式没做。** 第一阶段只支持裸 `.yaml`（这是原计划）。

**书源健康监控没做。** `mog source doctor` 能手动跑，但没有定时体检。

## 下一步

按依赖顺序：

1. **补 API 认证** —— 缺口明确、改动小，而且卡着「能不能安全对外」这件事。
   改完就不用再回头动 API 层。
2. **在真实站点上验证一次完整下载** —— 所有测试都离线，这是最大的未知。
3. **桌面端** —— 依赖已经齐了（API 全通），`package-lock.json` 一提交
   发版工作流就自动接管打包。
4. **Source Registry** —— 让书源能分发和更新。

## 相关文档

- [规划评估报告](evaluation/规划评估报告.md) —— 对原始规划书的评估与裁决
- [架构总览](architecture/overview.md) —— 分层、边界、数据流
- [开发指南](development/getting-started.md) —— 环境、命令、提交规范
- [CHANGELOG](../CHANGELOG.md) —— 按版本记录改了什么
