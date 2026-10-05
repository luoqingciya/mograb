# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab CLI 入口（规划书 §31）。

命令结构::

    mog source   ...   书源管理（list/install/lint/test/doctor/enable/disable）
    mog search   ...   搜索
    mog book     ...   书籍详情 / 书架列表
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

import sys

import typer

from mograb import __version__
from mograb.console import force_utf8_stdio

from ._localize import localize_typer
from .commands import (
    book,
    cache,
    config,
    download,
    export,
    find,
    init,
    logs,
    search,
    server,
    source,
    task,
    update,
)
from .commands._common import console, set_verbose


def _strip_exe_suffix() -> None:
    """把 ``sys.argv[0]`` 结尾的 ``.exe`` 去掉。

    Click 用 ``argv[0]`` 推导 ``prog_name``，于是打包后的产物：

    - 帮助里的用法行写成 ``用法: mog.exe [OPTIONS] ...``
    - 生成的补全脚本注册成 ``complete ... mog.exe``，环境变量叫
      ``_MOG.EXE_COMPLETE``（**名字里带点**）—— 而用户敲的是 ``mog``，
      补全根本不会触发

    改 ``argv[0]`` 而不是改 Click 的调用点，是因为全项目没有别处依赖它
    （数据目录走的是 ``sys.executable``，见 ``runtime_dir()``）。
    """
    if sys.argv and sys.argv[0].lower().endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]


# 必须在任何输出之前执行。打包后的 exe 无视 PYTHONUTF8 / PYTHONIOENCODING，
# 默认按控制台代码页（中文 Windows 上是 GBK）输出 —— 于是 --json 产出的
# 不是合法 JSON。详见 mograb.console。
force_utf8_stdio()

# 同理放模块级：`if __name__ == "__main__"` 在两条真实入口上**都不执行** ——
# 打包走 `scripts/entry_cli.py`（它自己调 `app()`），开发走 console script
# `mog = "mograb_cli.main:app"`。只有 `python -m mograb_cli.main` 会走到。
_strip_exe_suffix()

# Typer / Click 的内置文案是写死的英文，没有配置项。换成中文。
# 见 _localize.py 的模块文档。
localize_typer()

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
app.command("init", help="初始化数据目录")(init.init)
app.command("search", help="搜索小说")(search.search)
app.command("book", help="查看书籍（不给 ID 时列出书架）")(book.info)
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
