# SPDX-License-Identifier: GPL-3.0-only
"""``mog init`` —— 初始化数据目录。

数据目录原先只在**第一次跑某个命令**时顺带建出来（``create_application()``
里的 ``paths.ensure()`` + ``init_schema()``）。这留下一个空档：

- 没有任何一条命令的职责是「把环境准备好」。想在跑别的命令之前先往
  ``data/sources/`` 里放几个书源，只能自己 mkdir。
- ``mog config init`` **只写 config.toml，不建子目录** —— 名字容易被当成
  初始化命令，实际不是。

所以给一个显式入口。它走的是同一条路：``create_application()`` —— 项目规定
那是唯一的 composition root，CLI 和 API 都得走它，初始化步骤不该有第二份实现。

**刻意不做成 API 端点。** API server 启动时自己就会初始化（它得先有数据目录
才起得来），再暴露一个「帮我建数据目录」的端点没有意义 —— 那是先有鸡还是先有蛋。
"""

from __future__ import annotations

import typer

from mograb.config import ensure_token, get_paths

from ._common import command, console, emit, open_app


@command
async def init(
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """初始化数据目录（幂等，可重复执行）。"""
    paths = get_paths()
    created = not paths.root.is_dir()

    # create_application 里已经做了：建目录树 + 配日志 + 建数据库表。
    # 这里不自己重复一遍 —— 初始化步骤只能有一份实现。
    async with open_app():
        pass

    # 令牌按需生成，create_application 不碰它，单独补一下。
    ensure_token(paths)

    directories = {
        "covers": paths.covers_dir,
        "exports": paths.exports_dir,
        "logs": paths.logs_dir,
        "sources": paths.sources_dir,
    }

    if json_output:
        emit(
            {
                "data_dir": str(paths.root),
                "created": created,
                "config": str(paths.config_file),
                "database": str(paths.database),
                "directories": {name: str(path) for name, path in directories.items()},
            },
            json_output=True,
        )
        return

    console.print(f"[green]{'已创建' if created else '已就绪'}[/green] 数据目录 {paths.root}")
    for name, path in directories.items():
        console.print(f"[dim]  {name:<8} {path}[/dim]")
    console.print("[dim]  数据库表已建好，API 令牌已就位[/dim]")
    console.print("[dim]  查看令牌：`mog server token`　生成配置模板：`mog config init`[/dim]")
