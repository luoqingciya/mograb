# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab CLI 入口（规划书 §31）。

命令结构::

    mog source   ...   书源管理（list/install/lint/test/doctor/enable/disable）
    mog search   ...   搜索
    mog book     ...   书籍信息
    mog download ...   下载
    mog task     ...   任务控制（list/pause/resume/cancel/retry）
    mog update   ...   增量更新
    mog export   ...   导出
    mog cache    ...   缓存管理（stats/clear）
    mog config   ...   配置管理
    mog server   ...   本地 API Server 控制
    mog find     ...   在已下载的书里搜正文（纯本地）
    mog logs     ...   日志查看

通用约定：

- 所有命令支持 ``--json`` 输出（便于脚本调用）
- 退出码：0 成功 / 1 一般错误 / 2 参数错误 / 3 未找到 / 4 校验失败 / 130 用户中断
"""

from __future__ import annotations

import typer

from mograb import __version__

from .commands import (
    book,
    cache,
    config,
    download,
    export,
    find,
    logs,
    search,
    server,
    source,
    task,
    update,
)
from .commands._common import console, set_verbose

app = typer.Typer(
    name="mog",
    help="MoGrab —— 开源、API-First 的小说获取与电子书整理工具。",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=True,
)

# 注册子命令组
app.add_typer(source.app, name="source", help="书源管理")
app.add_typer(task.app, name="task", help="任务控制")
app.add_typer(cache.app, name="cache", help="缓存管理")
app.add_typer(config.app, name="config", help="配置管理")
app.add_typer(server.app, name="server", help="本地 API Server")

# 注册单命令
app.command("search", help="搜索小说")(search.search)
app.command("book", help="查看书籍信息")(book.info)
app.command("download", help="下载书籍")(download.download)
app.command("update", help="增量更新书籍")(update.update)
app.command("export", help="导出书籍")(export.export)
app.command("logs", help="查看日志")(logs.logs)
app.command("find", help="在已下载的书里搜正文")(find.find)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"mog (MoGrab) {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="显示版本并退出",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出详细日志"),
) -> None:
    """MoGrab CLI。"""
    # 各命令用 --json 自己声明；这里只处理影响全局日志级别的 --verbose
    set_verbose(verbose)


if __name__ == "__main__":  # pragma: no cover
    app()
