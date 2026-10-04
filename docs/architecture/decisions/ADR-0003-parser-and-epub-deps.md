# ADR-0003　解析器与 EPUB 依赖选型

> 状态：已接受
> 日期：2026-10-04
> 关联：规划书 §8.2、§27、§58；评估报告 P2-04、P2-05

---

## 背景

规划书在技术栈中留下了两个未决的依赖选型：

### 问题 1：HTML 解析器

§58 写作「`selectolax / lxml`」——**给出了两个选项但未做选择**。
而 §8.2 明确要求 v1 支持六种提取方式：

```
CSS Selector · XPath · JSONPath · Regex · Attribute · Text
```

### 问题 2：EPUB 生成库

§27 要求生成规范 EPUB（metadata / cover / toc / stylesheet / chapters），
但 §58 的技术栈中**完全没有列出 EPUB 库**。

常见选择 `ebooklib` 的许可证为 **AGPL-3.0**。MoGrab 主仓库为
**GPL-3.0-only**。虽然 GPLv3 §13 允许与 AGPLv3 组合，但组合后的整体
需承担 AGPL 的网络分发义务（即：若有人把 MoGrab 部署为网络服务，
必须向用户提供源代码）。

对于「个人工具」定位的项目，这引入了一个**与产品定位不匹配的合规负担**。

---

## 选项

### 问题 1：解析器

| 选项 | 优点 | 缺点 |
|------|------|------|
| **lxml** + cssselect | 单引擎同时支持 CSS 与 XPath；成熟稳定；C 实现性能好；`html_clean` 生态 | 依赖 libxml2/libxslt 原生库 |
| selectolax | 更快的 CSS 解析 | **不支持 XPath**（规范要求） |
| lxml + selectolax 双引擎 | 各取所长 | 两套语义需保持一致，维护成本高；`@attr` 等语法需实现两次 |
| BeautifulSoup | 容错性强 | 慢；XPath 需额外后端 |

### 问题 2：EPUB

| 选项 | 优点 | 缺点 |
|------|------|------|
| `ebooklib` | 功能完整 | **AGPL-3.0**，引入分发义务 |
| `pypub` | 简单 | 依赖已过时，维护停滞 |
| 自研（`zipfile` + OPF/NCX 模板） | 零依赖、零许可证问题、完全可控 | 需自行维护约 200 行代码 |

---

## 决策

### 决策 1：统一使用 `lxml`

```
lxml + cssselect + jsonpath-ng
```

理由：

1. **§8.2 明确要求支持 XPath**，而 selectolax 不支持。这是决定性因素。
2. **单引擎覆盖 CSS + XPath** 意味着 `ExtractRule` 的解析与执行只需一套语义，
   避免「同一书源在 CSS 与 XPath 规则下行为不一致」的隐患。
3. `lxml` 成熟稳定，且 `cssselect` 与 `lxml` 同源（lxml 内置 `cssselect()` 方法）。

**`selectolax` 保留为可选加速依赖**（`mograb[fast]`），但不作为默认。
引入条件：出现明确性能瓶颈（如单本书 5000+ 章节的目录解析）。

**JSONPath** 由 `jsonpath-ng` 提供（支持 `$.data[*].title` 等扩展语法）。
**Regex** 使用标准库 `re`。

### 决策 2：自研 EPUB 写入器

不引入 `ebooklib`。EPUB 的本质是：

```
EPUB (ZIP)
├── mimetype                     ← 必须第一个写入且不压缩
├── META-INF/container.xml
└── OEBPS/
    ├── content.opf              ← metadata + manifest + spine
    ├── toc.xhtml                ← EPUB3 导航
    ├── toc.ncx                  ← EPUB2 兼容
    ├── style.css
    └── chapter_NNNN.xhtml
```

自研实现约 200 行（`mograb/export/epub.py`），成本可控，且：

- **零许可证风险**
- **完全可控**：可精确控制输出结构，便于后续支持自定义模板（§27 要求）
- **无依赖膨胀**

已通过测试验证结构规范性，包括 `mimetype` 必须为第一个且未压缩的条目。

---

## 后果

### 正面

- 解析层语义统一，`ExtractRule` 实现只需一套
- 无 AGPL 依赖，GPL-3.0-only 定位清晰
- 依赖树更小，打包体积可控（对 PyInstaller onedir 有利）

### 负面

- `lxml` 依赖原生库（libxml2），打包时需确保正确捆绑
  —— PyInstaller 对 lxml 支持良好，风险低
- 自研 EPUB 需自行维护，未来若需支持 EPUB 高级特性
  （如 `mediaOverlays`、DRM 相关元数据）成本上升
- 放弃 selectolax 的解析性能优势

### 需要跟进

1. **EPUB 兼容性验证**：自研 EPUB 需在真实阅读器上验证
   （Calibre、Apple Books、微信读书、多看）。
   建议加入 `tests/fixtures/` 的 EPUB 结构快照测试。
2. **性能基线**：记录 `lxml` 在典型目录页（1000 章）的解析耗时。
   若超过 200ms，再评估引入 selectolax 加速路径。
3. **`epubcheck` 集成**：考虑在 CI 中对生成的 EPUB 运行
   [epubcheck](https://github.com/w3c/epubcheck) 验证。
