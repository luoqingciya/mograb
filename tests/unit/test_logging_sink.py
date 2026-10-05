# SPDX-License-Identifier: GPL-3.0-only
"""日志输出落点的测试。

盯的是 ``configure_logging(console_sink=...)`` —— 让日志和 Rich 进度条
共用同一个 console。

**为什么需要这个机制。** 默认日志直接写 stderr，而进度条在 stdout 上不停
重画当前行，两个写入者不协调。用户实测长下载时看到的就是这样：

    ⠴ 下载章节 ━━━━ 339/2036 0:06:062026-10-05T13:42:38 [warning] http.retry …

日志被糊在进度条中间。走同一个 Console 之后 Rich 会把日志排在进度条上方。

断言统一用 ``json_output=True`` —— 那个渲染器不输出 ANSI 颜色，
比去剥转义序列干净，也不会在源码里留下控制字符。
"""

from __future__ import annotations

import json
import logging

import pytest

# 注意别把模块别名叫成 `setup_module` —— 那是 pytest 的保留钩子名，
# pytest 会把它当钩子去调用，报一堆看不懂的 AttributeError。
import mograb.logging.setup as logging_setup
from mograb.logging import get_logger
from mograb.logging.setup import configure_logging

pytestmark = pytest.mark.unit


@pytest.fixture
def fresh_logging(monkeypatch: pytest.MonkeyPatch):
    """把日志系统恢复成「没配过」的状态，并保证用完还原。

    ``configure_logging`` 靠模块级 ``_configured`` 做幂等，测试要重配
    就得先把它按回去。
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    monkeypatch.setattr(logging_setup, "_configured", False)
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        logging_setup._configured = True


def _sink_lines() -> tuple[list[str], object]:
    """造一个收集日志行的通道，返回 (列表, 回调)。"""
    lines: list[str] = []
    return lines, lines.append


class TestConsoleSink:
    def test_日志走注入的通道(self, fresh_logging) -> None:
        lines, sink = _sink_lines()
        configure_logging(level="INFO", json_output=True, console_sink=sink)

        get_logger("test").warning("下载失败", attempt=1)

        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "下载失败"
        assert record["attempt"] == 1

    def test_不注入时仍写_stderr(self, fresh_logging, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(level="INFO", json_output=True)

        get_logger("test").warning("走默认通道")

        assert "走默认通道" in capsys.readouterr().err

    def test_注入后不写_stderr(self, fresh_logging, capsys: pytest.CaptureFixture[str]) -> None:
        """两条通道只能二选一 —— 否则日志会打两遍。"""
        lines, sink = _sink_lines()
        configure_logging(level="INFO", json_output=True, console_sink=sink)

        get_logger("test").warning("只该出现一次")

        assert len(lines) == 1
        assert capsys.readouterr().err == ""

    def test_低于级别的日志不输出(self, fresh_logging) -> None:
        lines, sink = _sink_lines()
        configure_logging(level="WARNING", json_output=True, console_sink=sink)

        logger = get_logger("test")
        logger.info("看不见")
        logger.warning("看得见")

        assert len(lines) == 1
        assert json.loads(lines[0])["event"] == "看得见"

    def test_通道抛异常不影响主流程(self, fresh_logging) -> None:
        """日志失败绝不能把业务带崩。"""

        def boom(_: str) -> None:
            raise RuntimeError("通道坏了")

        configure_logging(level="INFO", json_output=True, console_sink=boom)

        get_logger("test").warning("照常返回")


class TestHandlerInstallation:
    def test_根_logger_已有_handler_时也能装上(self, fresh_logging) -> None:
        """**这条盯的是一个静默失效。**

        ``logging.basicConfig()`` 在根 logger 已有 handler 时**什么都不做** ——
        不带 ``force=True`` 的话整个日志配置会被跳过，一个 handler 都装不上，
        而且不报错。写这批测试时撞到过：pytest 先挂了自己的 handler，
        于是注入的通道完全没生效。
        """
        logging.getLogger().addHandler(logging.NullHandler())  # 模拟「别人先占了」

        lines, sink = _sink_lines()
        configure_logging(level="INFO", json_output=True, console_sink=sink)

        get_logger("test").warning("必须能出来")

        assert len(lines) == 1

    def test_重复调用是幂等的(self, fresh_logging) -> None:
        """第二次调用不该再装一遍 handler —— 否则日志会翻倍。"""
        lines, sink = _sink_lines()
        configure_logging(level="INFO", json_output=True, console_sink=sink)
        configure_logging(level="INFO", json_output=True, console_sink=sink)

        get_logger("test").warning("只一次")

        assert len(lines) == 1
