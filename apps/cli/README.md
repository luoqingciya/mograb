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
mog source   list | show | lint | test | install | remove
             enable | disable | rescan | doctor | init
mog search   <keyword>              去书源上搜书
mog find     <keyword>              在本地已下载的正文里搜
mog book     [<book-id>]            不给 ID 时列出书架
mog download <book-id> | --url <URL> --source <ID>
mog task     list | show | pause | resume | cancel | retry
mog update   <book-id>
mog export   <book-id> --format txt|markdown|epub
mog cache    stats | clear | clear-source
mog config   init | path | show
mog server   start | status | stop | token
mog logs
```

`mog search` 和 `mog find` 是两件事：前者去**书源**上找「哪本书」，
后者在**本地已下载的正文**里找「哪一章」，纯本地、不联网。

`mog book` 不给 ID 就是书架列表 —— `mog export` / `mog update` 都要 `book_id`，
而那个 ID 是 ULID（`book_01M459...`），没人记得住。所以列表里 **ID 一定完整显示**，
不会被终端宽度截断（表格里那条列设了 `no_wrap`）。

`mog source test` 只接受**路径**不接受 ID —— 快照是开发期产物，
安装时不复制到数据目录。详见规范 §12.3。

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
