# mograb-cli —— MoGrab 命令行界面

提供 `mog` 命令。CLI 只做命令行交互，业务逻辑一律通过 Core / API 完成。

## 安装与运行

```bash
uv run mog --help
uv run mog source lint tests/fixtures/example-source/source.yaml
uv run mog search "三体" --json
```

## 命令结构

```
mog source   list | lint | test | install | doctor | init
mog search   <keyword>
mog book     <book-id>
mog download <book-id>
mog task     list | show | pause | resume | cancel | retry
mog update   <book-id>
mog export   <book-id> --format epub
mog cache    stats | clear | clear-source
mog config   init | path | show
mog server   start | status | stop
mog logs
```

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数错误 |
| 3 | 未找到 |
| 4 | 校验失败 |
| 5 | 网络错误 |
| 130 | 用户中断 |

## 许可证

GPL-3.0-only
