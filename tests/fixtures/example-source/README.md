# Example —— 参考书源

这个目录是 MoGrab Source Specification v1 的参考实现，兼测试数据。它同时是：

1. 规范的活样例 —— 四种能力、条件化 `url_join`、正文清洗都演示到了
2. fixture 测试的基准（`tests/source/test_example_source.py`）
3. 写新书源时的起步模板，直接拷走改

## 为什么放在 tests/ 而不是 sources/

书源不进远程仓库 —— 涉及第三方站点的抓取规则不适合随主仓库分发。
`sources/` 已经加进 `.gitignore`，留给本地开发调试用。

这个示例用的是 `example.com`（IANA 保留域名），不会产生真实请求，
所以放在测试夹具里既安全又能被 CI 覆盖。

## 结构

```
example-source/
├── source.yaml         书源定义
├── README.md           本文件
└── fixtures/           离线测试用 HTML 快照
    ├── search.html
    ├── book.html
    └── chapter.html
```

## 验证

```bash
uv run mog source lint tests/fixtures/example-source/source.yaml
uv run pytest tests/source -v
```

## 说明

`spec_version` 和 `version` 是两个语义不同的字段：前者是规范版本，
后者是书源自身的语义化版本。别写混，详见
`docs/source-spec/source-spec-v1.md`。

## 许可证

GPL-3.0-only
