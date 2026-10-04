# 第三方依赖许可证

> 对应[原始规划书](docs/planning/项目规划书.md)（历史存档，非规范）：§43
> 生成日期：2026-10-04
> 项目许可证：GPL-3.0-only

本文件记录 MoGrab 使用的第三方依赖及其许可证，用于满足 GPL-3.0 的分发要求
（分发二进制产物时须随附本清单与各依赖的许可证全文）。

---

## 1. 许可证兼容性结论

**全部运行时依赖均与 GPL-3.0-only 兼容。**

| 类别 | 结论 |
|------|------|
| 宽松许可证（MIT / BSD / ISC / Apache-2.0 / PSF） | 兼容，可并入 GPL-3.0 作品 |
| 弱 copyleft（MPL-2.0：`certifi`） | 兼容。MPL-2.0 为文件级 copyleft，作为独立库使用不影响本项目整体许可 |
| 强 copyleft（GPL / AGPL） | **无此类依赖** |

> 重要约束：本项目**禁止**引入 AGPL-3.0 依赖（如 `ebooklib`）。
> AGPL 会给 GPL-3.0-only 项目带来额外的网络分发义务，与「个人工具」定位不符。
> 详见 [ADR-0003](docs/architecture/decisions/ADR-0003-parser-and-epub-deps.md)。

---

## 2. 核心库 `mograb` 运行时依赖

| 依赖 | 版本 | 许可证 | 项目地址 | 用途 |
|------|------|--------|---------|------|
| `httpx` | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx | 异步 HTTP 客户端 |
| `httpcore` | 1.0.9 | BSD-3-Clause | https://github.com/encode/httpcore | httpx 传输层 |
| `h11` | 0.16.0 | MIT | https://github.com/python-hyper/h11 | HTTP/1.1 协议实现 |
| `anyio` | 4.15.1 | MIT | https://github.com/agronholm/anyio | 异步抽象层 |
| `idna` | 3.20 | BSD-3-Clause | https://github.com/kjd/idna | 国际化域名 |
| `certifi` | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi | CA 证书包 |
| `lxml` | 6.1.3 | BSD-3-Clause | https://github.com/lxml/lxml | HTML/XML 解析（CSS + XPath） |
| `cssselect` | 1.5.0 | BSD-3-Clause | https://github.com/scrapy/cssselect | CSS 选择器 → XPath 转换 |
| `jsonpath-ng` | 1.8.0 | Apache-2.0 | https://github.com/h2non/jsonpath-ng | JSONPath 提取 |
| `pydantic` | 2.13.5 | MIT | https://github.com/pydantic/pydantic | 数据校验与模型 |
| `pydantic-core` | 2.46.5 | MIT | https://github.com/pydantic/pydantic-core | pydantic 核心（Rust） |
| `pydantic-settings` | 2.15.0 | MIT | https://github.com/pydantic/pydantic-settings | 配置管理 |
| `annotated-types` | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types | 类型标注扩展 |
| `typing-inspection` | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection | 类型内省 |
| `typing-extensions` | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions | 类型特性回填 |
| `PyYAML` | 6.0.3 | MIT | https://github.com/yaml/pyyaml | 书源 YAML 解析 |
| `SQLAlchemy` | 2.1.3 | MIT | https://github.com/sqlalchemy/sqlalchemy | ORM |
| `greenlet` | 3.5.6 | MIT AND PSF-2.0 | https://github.com/python-greenlet/greenlet | SQLAlchemy async 依赖 |
| `aiosqlite` | 0.22.1 | MIT | https://github.com/omnilib/aiosqlite | SQLite 异步驱动 |
| `alembic` | 1.20.0 | MIT | https://github.com/sqlalchemy/alembic | 数据库迁移 |
| `Mako` | 1.4.3 | MIT | https://github.com/sqlalchemy/mako | Alembic 模板引擎 |
| `MarkupSafe` | 3.0.4 | BSD-3-Clause | https://github.com/pallets/markupsafe | Mako 依赖 |
| `structlog` | 26.1.0 | Apache-2.0 OR MIT | https://github.com/hynek/structlog | 结构化日志 |

---

## 3. CLI `mograb-cli` 运行时依赖

| 依赖 | 版本 | 许可证 | 项目地址 | 用途 |
|------|------|--------|---------|------|
| `typer` | 0.27.2 | MIT | https://github.com/fastapi/typer | CLI 框架 |
| `click` | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click | Typer 依赖 |
| `shellingham` | 1.5.4 | ISC | https://github.com/sarugaku/shellingham | Shell 探测 |
| `rich` | 15.0.0 | MIT | https://github.com/Textualize/rich | 终端渲染 |
| `markdown-it-py` | 4.2.0 | MIT | https://github.com/executablebooks/markdown-it-py | Rich Markdown 渲染 |
| `mdurl` | 0.1.2 | MIT | https://github.com/executablebooks/mdurl | URL 工具 |
| `Pygments` | 2.21.0 | BSD-2-Clause | https://github.com/pygments/pygments | 语法高亮 |
| `colorama` | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama | Windows 终端颜色 |

---

## 4. API `mograb-api` 运行时依赖

| 依赖 | 版本 | 许可证 | 项目地址 | 用途 |
|------|------|--------|---------|------|
| `fastapi` | 0.142.2 | MIT | https://github.com/fastapi/fastapi | Web 框架 |
| `starlette` | 1.7.0 | BSD-3-Clause | https://github.com/encode/starlette | FastAPI 底层 |
| `uvicorn` | 0.54.0 | BSD-3-Clause | https://github.com/encode/uvicorn | ASGI 服务器 |
| `sse-starlette` | 3.5.0 | BSD-3-Clause | https://github.com/sysid/sse-starlette | SSE 支持 |
| `httptools` | 0.8.0 | MIT | https://github.com/MagicStack/httptools | 高性能 HTTP 解析 |
| `watchfiles` | 1.3.0 | MIT | https://github.com/samuelcolvin/watchfiles | 文件监听（开发热重载） |
| `websockets` | 17.2 | BSD-3-Clause | https://github.com/python-websockets/websockets | WebSocket 支持 |
| `python-dotenv` | 1.2.4 | BSD-3-Clause | https://github.com/theskumar/python-dotenv | 环境变量加载 |

---

## 5. Desktop `apps/desktop` 运行时依赖

> 待 Electron 依赖锁定后补充。**发布 Desktop 前必须完成本节。**

| 依赖 | 版本 | 许可证 | 用途 |
|------|------|--------|------|
| `electron` | 待定 | MIT | 桌面运行时 |
| `electron-builder` | 待定 | MIT | 打包 |

**Electron 分发的 GPL 合规要求**：

Electron 包含 Chromium 与 Node.js，二者均为宽松许可证（BSD / MIT 等），
与 GPL-3.0 兼容。但分发 Electron 应用时须：

1. 随附 Electron 自身的许可证文件
2. 随附 Chromium 的版权声明
3. 若修改了 Electron 源码，须公开修改后的源码

---

## 6. 开发与构建依赖（不随产物分发）

以下依赖仅用于开发与 CI，**不进入发布产物**，因此不触发 GPL 分发义务。

| 依赖 | 版本 | 许可证 | 用途 |
|------|------|--------|------|
| `pytest` | 9.1.1 | MIT | 测试框架 |
| `pytest-asyncio` | 1.4.0 | Apache-2.0 | 异步测试 |
| `pytest-cov` | 7.1.0 | MIT | 覆盖率 |
| `coverage` | 7.16.2 | Apache-2.0 | 覆盖率核心 |
| `ruff` | 0.16.10 | MIT | Lint + 格式化 |
| `pyright` | 1.1.414 | MIT | 类型检查 |
| `pre-commit` | 4.6.2 | MIT | Git 钩子 |
| `virtualenv` | 21.14.5 | MIT | 环境管理 |
| `distlib` | 0.4.3 | PSF-2.0 | virtualenv 依赖 |
| `filelock` | 4.0.10 | Unlicense | 文件锁 |
| `cfgv` | 3.5.0 | MIT | 配置校验 |
| `identify` | 2.6.20 | MIT | 文件类型识别 |
| `nodeenv` | 1.11.0 | BSD-3-Clause | Node 环境管理 |
| `platformdirs` | 4.12.3 | MIT | virtualenv 的传递依赖，项目本身不使用 |
| `Faker` | 40.40.0 | MIT | 测试数据 |
| `freezegun` | 1.5.5 | Apache-2.0 | 时间冻结 |
| `python-dateutil` | 2.9.0.post0 | BSD-3-Clause OR Apache-2.0 | 日期解析 |
| `six` | 1.17.0 | MIT | 兼容层 |
| `iniconfig` | 2.3.0 | MIT | pytest 配置 |
| `pluggy` | 1.6.0 | MIT | pytest 插件系统 |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | 版本比较，`scripts/version.py` 与测试用 |
| `tzdata` | 2026.5 | Apache-2.0 | 时区数据 |

构建后端（`[build-system] requires`，同样不进产物）：

| 依赖 | 许可证 | 用途 |
|------|--------|------|
| `hatchling` | MIT | 三个包的构建后端，负责从 `VERSION` 读版本号 |
| `PyInstaller` | 待定 | GPL-2.0-or-later **with bootloader exception** | 打包（见下） |

### 6.1 PyInstaller 的许可证说明

PyInstaller 采用 **GPL-2.0-or-later**，但附带**明确的例外条款**：
打包生成的**可执行产物不受 GPL 约束**，可自由分发。

> "As a special exception to the GNU General Public License, if you
> distribute this software, you may use the bootloader in your own
> executables without any restriction."
> —— PyInstaller 许可证例外条款

因此使用 PyInstaller 打包 MoGrab **不会**影响 MoGrab 自身的 GPL-3.0-only 许可。

---

## 7. 分发检查清单

发布 Windows / Linux 产物前，请确认：

- [ ] 本文件已更新为实际锁定的版本
- [ ] 随产物提供 `LICENSE`（GPL-3.0 全文）
- [ ] 随产物提供本文件（第三方许可证清单）
- [ ] 若含 Electron：提供 Electron / Chromium 的版权声明
- [ ] 确认无新增 AGPL 依赖
- [ ] 确认无新增许可证不兼容的依赖
- [ ] `SHA256SUMS.txt` 已生成

---

## 8. 维护说明

本文件应随依赖变更同步更新。可用以下命令枚举当前锁定版本：

```bash
uv tree --package mograb --depth 1
uv run python -c "
import importlib.metadata as md
for d in sorted(md.distributions(), key=lambda x: (x.metadata['Name'] or '').lower()):
    n = d.metadata['Name']
    if n:
        print(f\"{n} {d.version} {d.metadata.get('License-Expression') or d.metadata.get('License') or ''}\")
"
```

建议在 CI 中加入自动化检查（见 `docs/development/ci.md` 待补项）。
