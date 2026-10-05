# SPDX-License-Identifier: GPL-3.0-only
"""Typer / Click 内置文案的本地化测试。

``_localize.py`` 是一堆**猴补丁** —— 改的是第三方库的模块级变量和几个函数引用。
Typer 一升级就可能失效，而且失效方式是**静默的**：文案悄悄变回英文，
不报错、不崩溃。所以这里逐条钉住用户能看到的那些。

只断言「不该出现英文」是不够的，还得断言「该出现中文」——
否则补丁没生效时两条都过。
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from mograb_cli.main import app

pytestmark = pytest.mark.unit

runner = CliRunner()


def _help(*args: str) -> str:
    result = runner.invoke(app, [*args, "--help"])
    assert result.exit_code == 0, result.output
    return result.output


class TestHelpText:
    def test_用法前缀是中文(self) -> None:
        assert "用法: mog" in _help()
        assert "Usage:" not in _help()

    def test_面板标题是中文(self) -> None:
        output = _help()

        assert "─ 选项 ─" in output
        assert "─ 命令 ─" in output

    def test_补全选项说明是中文(self) -> None:
        output = _help()

        assert "Install completion for the current shell." not in output
        assert "Show completion for the current shell" not in output
        assert "为当前 shell 安装补全" in output
        assert "输出补全脚本" in output

    def test_帮助选项说明是中文(self) -> None:
        output = _help()

        assert "Show this message and exit." not in output
        assert "显示这条帮助并退出" in output

    def test_子命令的参数面板与必填标记(self) -> None:
        output = _help("export")

        assert "─ 参数 ─" in output
        assert "[required]" not in output
        assert "[必填]" in output

    def test_默认值标记是中文(self) -> None:
        output = _help("book")

        assert "[default:" not in output
        assert "[默认:" in output


class TestErrorText:
    def test_缺少参数(self) -> None:
        result = runner.invoke(app, ["source", "enable"])

        assert result.exit_code != 0
        assert "Missing argument" not in result.output
        assert "缺少参数" in result.output

    def test_不存在的命令(self) -> None:
        result = runner.invoke(app, ["no-such-command"])

        assert result.exit_code != 0
        assert "No such command" not in result.output
        assert "没有这个命令" in result.output

    def test_帮助提示是中文(self) -> None:
        result = runner.invoke(app, ["source", "enable"])

        assert "for help." not in result.output
        assert "看帮助" in result.output

    def test_错误面板标题是中文(self) -> None:
        result = runner.invoke(app, ["source", "enable"])

        assert "─ 错误 ─" in result.output

    def test_句末用全角句号(self) -> None:
        """中文句子不该用西文句号 —— 项目对全角标点是一贯要求。"""
        result = runner.invoke(app, ["source", "enable"])

        assert "'source_id'。" in result.output
        assert "'source_id'." not in result.output
