# SPDX-License-Identifier: GPL-3.0-only
"""``mog source`` —— 书源管理（规划书 §11、§12、§13、§51、§54）。"""

from __future__ import annotations

from pathlib import Path

import typer

from mograb.errors import MoGrabError
from mograb.source import lint, load_source_file

from ._common import console, emit, fail

app = typer.Typer(no_args_is_help=True, help="书源管理")


@app.command("list")
def list_sources(
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """列出已安装书源。"""
    # TODO(storage): 接入 SourceRepository.list_all()
    emit([], json_output=json_output)
    if not json_output:
        console.print("[yellow]尚未安装任何书源[/yellow]")


@app.command("lint")
def lint_source(
    path: Path = typer.Argument(..., help="书源 YAML 文件路径"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """校验书源（Schema + 语义）。

    输出格式遵循 §11：错误包含位置、字段路径、原因与解决建议。
    """
    try:
        spec = load_source_file(path)
        report = lint(spec)
    except MoGrabError as exc:
        fail(exc, json_output=json_output)
        return

    if json_output:
        emit(report.to_dict(), json_output=True)
    else:
        console.print(f"Source: [bold]{report.source_id}[/bold]")
        console.print(f"Schema: {'[green]PASS[/green]' if report.is_ready else '[red]FAIL[/red]'}")
        console.print(
            f"Semantic: {'[green]PASS[/green]' if report.is_ready else '[red]FAIL[/red]'}"
        )
        if report.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for diag in report.warnings:
                console.print(f"- {diag.format()}")
        if report.errors:
            console.print("\n[red]Errors:[/red]")
            for diag in report.errors:
                console.print(f"- {diag.format()}")
        console.print(
            f"\nResult: {'[green]READY[/green]' if report.is_ready else '[red]BROKEN[/red]'}"
        )

    if not report.is_ready:
        raise typer.Exit(code=4)


@app.command("test")
def test_source(
    target: str = typer.Argument(..., help="书源 ID 或路径"),
    fixture: bool = typer.Option(False, "--fixture", help="使用本地 fixture 离线测试"),
) -> None:
    """测试书源（规划书 §12）。"""
    raise NotImplementedError("source test 待 Fixture 测试框架实现")


@app.command("install")
def install_source(source_id: str = typer.Argument(..., help="要安装的书源 ID")) -> None:
    """从 Source Registry 安装书源（规划书 §13）。"""
    raise NotImplementedError("source install 待 Source Registry 实现")


@app.command("doctor")
def doctor(
    source_id: str | None = typer.Argument(None, help="书源 ID；省略则检查全部"),
) -> None:
    """书源健康检查（规划书 §54）。"""
    raise NotImplementedError("source doctor 待网络层接入后实现")


@app.command("init")
def init_source(name: str = typer.Argument(..., help="新书源目录名")) -> None:
    """生成书源脚手架（规划书 §51）。"""
    raise NotImplementedError("source init 待模板实现")


__all__ = ["app"]
