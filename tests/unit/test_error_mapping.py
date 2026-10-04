# SPDX-License-Identifier: GPL-3.0-only
"""错误码映射的单元测试。

两个映射是**契约的一部分** —— 客户端按 HTTP 状态码分支，脚本按退出码分支。
它们靠 `isinstance` 的顺序匹配，所以「子类必须排在父类前面」这条规则
一旦被打破，表现是错误码静默变错，不会报错。这里钉住。

CLI 和 API 各有一份映射表，分别测。
"""

from __future__ import annotations

import pytest

from mograb.errors import (
    AuthError,
    ContentValidationError,
    EntityNotFoundError,
    ExportError,
    HttpStatusError,
    InvalidTaskTransitionError,
    NetworkError,
    SourceNotFoundError,
    SourceSchemaError,
    SourceUnsupportedError,
    StorageError,
    TaskError,
    TaskNotFoundError,
    TaskParameterError,
    TimeoutError_,
)
from mograb_api.errors import status_for
from mograb_cli.commands._common import ExitCode, exit_code_for

# ---------------------------------------------------------------------------
# API：领域错误 -> HTTP 状态码
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthError("缺少令牌"), 401),
        (EntityNotFoundError("书籍不存在"), 404),
        (SourceNotFoundError("书源不存在"), 404),
        (TaskNotFoundError("任务不存在"), 404),
        (SourceSchemaError("书源不合法"), 422),
        (SourceUnsupportedError("规范版本不支持"), 422),
        (ContentValidationError("正文太短"), 422),
        (ExportError("导出失败"), 422),
        (TaskParameterError("缺 book_id"), 400),
        (NetworkError("连不上"), 502),
        (HttpStatusError("上游 503", status_code=503), 502),
        (StorageError("写库失败"), 500),
        (TaskError("任务失败"), 409),
        (InvalidTaskTransitionError("不能这么转"), 409),
    ],
)
def test_status_for(error: Exception, expected: int) -> None:
    assert status_for(error) == expected


def test_task_parameter_beats_task_error() -> None:
    """`TaskParameterError` 是 `TaskError` 的子类，顺序错了就会变成 409。"""
    error = TaskParameterError("缺参数")

    assert isinstance(error, TaskError)
    assert status_for(error) == 400


# ---------------------------------------------------------------------------
# CLI：领域错误 -> 退出码
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthError("缺少令牌"), ExitCode.ERROR),
        (EntityNotFoundError("书籍不存在"), ExitCode.NOT_FOUND),
        (SourceNotFoundError("书源不存在"), ExitCode.NOT_FOUND),
        (TaskNotFoundError("任务不存在"), ExitCode.NOT_FOUND),
        (SourceSchemaError("书源不合法"), ExitCode.VALIDATION),
        (ContentValidationError("正文太短"), ExitCode.VALIDATION),
        (TaskParameterError("缺 book_id"), ExitCode.USAGE),
        (NetworkError("连不上"), ExitCode.NETWORK),
        (TimeoutError_("超时"), ExitCode.NETWORK),
        (TaskError("任务失败"), ExitCode.ERROR),
        (StorageError("写库失败"), ExitCode.ERROR),
    ],
)
def test_exit_code_for(error: Exception, expected: ExitCode) -> None:
    assert exit_code_for(error) == expected


def test_unknown_error_is_generic_failure() -> None:
    """没在表里的异常落到 1，而不是悄悄当成成功。"""
    assert exit_code_for(RuntimeError("意料之外")) == ExitCode.ERROR
