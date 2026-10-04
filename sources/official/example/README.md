# Example —— 官方参考书源

本目录是 MoGrab 官方示例书源，用于：

1. 演示 MoGrab Source Specification v1 的全部能力
2. 作为 fixture 测试的基准（`tests/source/`）
3. 作为新书源开发者的起步模板

## 结构

```
example/
├── source.yaml         书源定义
├── README.md           本文件
└── fixtures/           离线测试用 HTML 快照
    ├── search.html
    ├── book.html
    └── chapter.html
```

## 验证

```bash
mog source lint sources/official/example/source.yaml
mog source test example --fixture
```

## 说明

- 域名 `example.com` 由 IANA 保留，不会产生真实网络请求。
- 本示例使用 `spec_version: 1` 与 `version: 1.0.0` 两个**语义不同**的字段：
  前者是规范版本，后者是书源自身版本。详见 `docs/source-spec/source-spec-v1.md`。

## 许可证

GPL-3.0-only
