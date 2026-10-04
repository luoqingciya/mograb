# MoGrab

开源的小说抓取与电子书整理工具。Python 写的，后端 + 命令行 + Windows 桌面端。

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0--only-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

## 这个项目想解决什么

现有的小说下载工具大多围绕 Legado 书源格式做兼容，结果是书源规则越写越复杂，
一个站点改版就要靠一堆正则和脚本去救。MoGrab 换个思路：不兼容 Legado，
自己定一套书源规范，规则只描述"请求什么、从哪取、怎么提取、怎么转换"，
重试、并发、缓存、调度全部交给程序。

书源是一份 YAML 配置，不是 Python 插件，不允许执行任意代码。表达力换来的是
可静态检查、可安全分发、可以离线测试。

```yaml
spec_version: 1
id: example
version: 1.0.0
capabilities: [search, book, chapters, content]

search:
  request: { method: GET, url: "https://example.com/search", query: { q: "{{keyword}}" } }
  result:
    list: ".book-item"
    fields:
      title: ".title"
      author: ".author"
      url: "a@href"

content:
  request: { method: GET, url: "{{chapter.url}}" }
  body: { selector: "#content" }
  clean:
    remove: ["script", "style", ".advert"]
```

## 现在做到哪了

版本 `1.0.0rc0`（**预发布**）。规范已经定下来，**整条链路都通了** ——
命令行能装书源、搜书、下载、增量更新、导出，还能在已下载的正文里搜关键词
（`mog find`，纯本地）；本地 API 在同一套 Core 上跑起来了；
桌面端最小闭环可用。

标成 rc 而不是正式版，是因为**所有测试都是离线的** —— 还没在真实站点上
跑过完整下载。

```
规范与领域模型    已冻结
书源引擎 · 网络层  已实现
内容管线 · 导出    已实现
存储 · 任务引擎    已实现
CLI · API        已实现（含鉴权）
桌面端           最小闭环
```

626 个测试通过，覆盖率 85%，Ruff 与 Pyright 干净，CI 全绿。

缺口、里程碑对照和下一步看 **[项目进度](docs/progress.md)** —— 进度信息只在那份文档里维护。

## 上手

需要 Python 3.11+ 和 [uv](https://github.com/astral-sh/uv)。
最终用户不用装这些，发布包自带运行时。

```bash
git clone https://github.com/luoqingciya/mograb.git
cd mograb
uv sync --all-packages

# 校验一个书源
uv run mog source lint tests/fixtures/example-source/source.yaml

# 跑测试
uv run pytest -q
```

`mog source lint` 的输出：

```
Source: example
Schema: PASS
Semantic: PASS

Result: READY
```

## 数据放在哪

便携式的，所有运行数据都在程序目录下的 `data/` 里，不写系统目录。
删掉 `data/` 就等于恢复出厂设置，整个程序目录可以直接拷走。

```
<程序目录>/
├── mog.exe
├── _internal/
└── data/
    ├── config.toml
    ├── mograb.db
    ├── cache/
    ├── covers/
    ├── logs/
    ├── exports/
    └── sources/
```

开发时从仓库根运行，数据落在 `<仓库根>/data/`，已经在 `.gitignore` 里排除。

想改位置就设 `MOGRAB_HOME`。

## 结构

```
MoGrab/
├── packages/mograb/     核心库
│   └── src/mograb/
│       ├── domain/      领域模型
│       ├── source/      书源加载、校验、执行
│       ├── network/     HTTP、缓存、限流、重试
│       ├── task/        队列、Worker、调度
│       ├── storage/     ORM、仓储、SQLite
│       ├── content/     清洗、规范化、校验
│       ├── export/      TXT / Markdown / EPUB
│       ├── config/      配置与路径
│       └── logging/     结构化日志
├── apps/
│   ├── cli/             命令行，命令名 mog
│   ├── api/             本地 API，FastAPI
│   └── desktop/         桌面端，Electron
├── sources/             本地书源工作区（不进仓库）
├── tests/               单元 / 集成 / 书源 fixture
└── docs/                文档
```

书源不进远程仓库 —— 涉及第三方站点的抓取规则不适合随主仓库分发。
`sources/` 已在 `.gitignore` 里，留给你本地开发和调试。
规范的参考实现和测试数据放在 `tests/fixtures/example-source/`。

架构上就一条硬规则：CLI 和桌面端都不许自己实现业务逻辑，一切走 Core 或 API。
其他的边界写在[架构总览](docs/architecture/overview.md)里。

版本号只有一个来源，仓库根的 [`VERSION`](VERSION) 文件。三个包构建时都读它，
改一处全局生效。

## 文档

- [项目进度](docs/progress.md) —— **做到哪了、还差什么**，进度只在这里维护
- [架构总览](docs/architecture/overview.md) —— 分层、边界、数据流、技术选型
- [Source Specification v1](docs/source-spec/source-spec-v1.md) —— 书源规范，最重要的一份
- [Domain Model v1](docs/domain-model/domain-model-v1.md) —— 领域模型与任务状态机
- [Storage v1](docs/storage/storage-v1.md) —— 表结构
- [API v1](docs/api/api-v1.md) —— 接口契约
- [开发指南](docs/development/getting-started.md) —— 环境、命令、提交规范
- [CI 与发布](docs/development/ci.md) —— 流水线与打包
- [规划评估报告](docs/evaluation/规划评估报告.md) —— 对原始规划书的评估，以及几个关键裁决的理由
- [原始规划书](docs/planning/项目规划书.md) —— 历史存档，**不是规范**，只用来追溯出处
- [ADR](docs/architecture/decisions/) —— 架构决策记录

## 不做什么

MoGrab 是个人工具，不是通用爬虫框架。以下明确不做：

- 兼容 Legado 全部规则
- 执行任意第三方脚本
- 复杂反爬对抗、验证码破解
- 绕过付费墙或访问控制
- 多用户服务器、移动端、分布式爬虫

## 使用须知

仅供个人学习研究，抓取公开可访问的内容。

使用者需要自己遵守目标站点的服务条款、robots.txt 和所在地法律。
不要用于商业用途、批量分发版权内容，也不要给站点造成不合理负载 ——
程序默认单源并发 2、请求间隔 500ms，别改得比这更激进。

项目本身不提供、不内置任何版权内容。书源只描述如何访问公开页面，
不含内容数据。

按 GPL-3.0 分发，不提供任何担保。

## 许可证

[GNU General Public License v3.0](LICENSE)，`GPL-3.0-only`。

第三方依赖的许可证清单在 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)，
里面也说明了为什么这个项目刻意避开 AGPL 依赖。
