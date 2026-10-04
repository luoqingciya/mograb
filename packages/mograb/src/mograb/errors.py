# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab 统一错误体系。

设计约束（对应规划书 §37）：

- 禁止在业务代码中裸抛 ``Exception``；所有可预期失败必须落到本模块的层次中。
- 每个错误携带稳定的 ``code``（大写下划线），API 层直接映射为响应体 ``code`` 字段。
- ``retryable`` 显式声明该错误是否适合自动重试，由 Task Engine 读取，
  避免在重试策略中散落 ``isinstance`` 判断。

层次结构::

    MoGrabError
    ├── ConfigError
    ├── SourceError
    │   ├── SourceSchemaError
    │   ├── SourceExecutionError
    │   └── SourceUnsupportedError
    ├── NetworkError
    ├── ParseError
    ├── ContentValidationError
    ├── TaskError
    ├── StorageError
    └── ExportError
"""

from __future__ import annotations

from typing import Any


class MoGrabError(Exception):
    """所有 MoGrab 错误的基类。

    Attributes:
        code: 稳定的机器可读错误码，例如 ``SOURCE_PARSE_FAILED``。
        message: 面向开发者/用户的简短描述。
        details: 结构化补充信息，会原样进入 API 响应与结构化日志。
        retryable: 该错误是否适合自动重试。
    """

    code: str = "MOGRAB_ERROR"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        """转换为 API 响应体结构（规划书 §37）。"""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }

    def __str__(self) -> str:  # pragma: no cover - 便于日志阅读
        if self.details:
            return f"[{self.code}] {self.message} | {self.details}"
        return f"[{self.code}] {self.message}"


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
class ConfigError(MoGrabError):
    """配置缺失、格式非法或取值越界。"""

    code = "CONFIG_ERROR"


# ---------------------------------------------------------------------------
# 书源
# ---------------------------------------------------------------------------
class SourceError(MoGrabError):
    """书源相关错误基类。"""

    code = "SOURCE_ERROR"


class SourceSchemaError(SourceError):
    """书源未通过 Schema / 语义校验。**立即失败，不重试。**"""

    code = "SOURCE_SCHEMA_ERROR"


class SourceExecutionError(SourceError):
    """书源规则执行失败（选择器无匹配、变量未解析等）。

    这类错误通常意味着站点结构变化，**不应无限自动重试**。
    """

    code = "SOURCE_EXECUTION_ERROR"


class SourceUnsupportedError(SourceError):
    """书源声明了当前引擎不支持的能力或 Schema 版本。"""

    code = "SOURCE_UNSUPPORTED_ERROR"


class SourceNotFoundError(SourceError):
    """指定的书源未安装或未启用。"""

    code = "SOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 网络
# ---------------------------------------------------------------------------
class NetworkError(MoGrabError):
    """网络层失败：超时、连接错误、5xx、429。

    默认 ``retryable = True``，由具体子类或调用点覆盖。
    """

    code = "NETWORK_ERROR"
    retryable = True


class TimeoutError_(NetworkError):
    """请求超时。"""

    code = "NETWORK_TIMEOUT"


class RateLimitedError(NetworkError):
    """收到 429 或触发本地限流。应遵循 ``Retry-After``。"""

    code = "NETWORK_RATE_LIMITED"

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retry_after = retry_after


class HttpStatusError(NetworkError):
    """非 2xx 响应。5xx 可重试，4xx 一般不可重试（由调用点判定）。"""

    code = "NETWORK_HTTP_STATUS"

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.status_code = status_code
        self.retryable = status_code >= 500 or status_code == 429


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
class ParseError(MoGrabError):
    """HTML / JSON / 选择器解析失败。**不自动无限重试。**"""

    code = "PARSE_ERROR"


# ---------------------------------------------------------------------------
# 内容校验
# ---------------------------------------------------------------------------
class ContentValidationError(MoGrabError):
    """下载成功但内容未通过校验（空正文、长度异常、疑似广告页）。

    ``retryable`` 默认 False：内容问题通常需要人工或规则修正，
    重试不会改变结果。可由策略层显式开启有限重试。
    """

    code = "CONTENT_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------
class TaskError(MoGrabError):
    """任务状态机非法转移或任务执行失败。"""

    code = "TASK_ERROR"


class TaskNotFoundError(TaskError):
    """指定任务不存在。"""

    code = "TASK_NOT_FOUND"


class TaskParameterError(TaskError):
    """建任务的参数不成立 —— 缺必填项，或者给法互相矛盾。

    和 :class:`InvalidTaskTransitionError` 分开是因为语义不同：
    那是「和资源当前状态冲突」（409），这是「请求本身就没说清楚」（400）。
    """

    code = "TASK_PARAMETER_ERROR"


class InvalidTaskTransitionError(TaskError):
    """尝试了状态机不允许的状态转移。"""

    code = "TASK_INVALID_TRANSITION"


class TaskCancelledError(TaskError):
    """任务被用户取消，用于中断执行流。"""

    code = "TASK_CANCELLED"


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
class StorageError(MoGrabError):
    """持久化失败。"""

    code = "STORAGE_ERROR"


class EntityNotFoundError(StorageError):
    """按 ID 查询实体失败。"""

    code = "STORAGE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------
class ExportError(MoGrabError):
    """导出失败（路径非法、模板错误、EPUB 结构生成失败）。"""

    code = "EXPORT_ERROR"


class UnsafePathError(ExportError):
    """路径包含穿越、非法字符或超出允许的根目录。"""

    code = "EXPORT_UNSAFE_PATH"


__all__ = [
    "ConfigError",
    "ContentValidationError",
    "EntityNotFoundError",
    "ExportError",
    "HttpStatusError",
    "InvalidTaskTransitionError",
    "MoGrabError",
    "NetworkError",
    "ParseError",
    "RateLimitedError",
    "SourceError",
    "SourceExecutionError",
    "SourceNotFoundError",
    "SourceSchemaError",
    "SourceUnsupportedError",
    "StorageError",
    "TaskCancelledError",
    "TaskError",
    "TaskNotFoundError",
    "TimeoutError_",
    "UnsafePathError",
]
