# SPDX-License-Identifier: GPL-3.0-only
"""配置系统（规划书 §35）。

配置文件为 TOML，默认位于 :func:`mograb.config.paths.get_paths().config_file`。

**配置优先级**（高 → 低）::

    CLI 参数
      > Task 参数
        > Source 配置
          > Global 配置（本文件）
            > Default（代码内默认值）

因此本模块只负责「Global 配置」与「Default」两层；
上层覆盖由调用方通过 ``model_copy(update=...)`` 实现。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..errors import ConfigError
from .paths import Paths, get_paths


class ServerSettings(BaseModel):
    """API Server 配置（§34、§35）。"""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    """默认仅监听 localhost（§40）。"""

    port: int = Field(default=48721, ge=1024, le=65535)
    health_timeout_ms: int = Field(default=5000, ge=100)


class DownloadSettings(BaseModel):
    """下载配置（§35、§38）。"""

    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=4, ge=1, le=64, description="全局并发上限（跨所有书源）")
    per_source_concurrency: int = Field(
        default=2, ge=1, le=32, description="单书源默认并发（可被书源 network 覆盖）"
    )
    retry: int = Field(default=3, ge=0, le=10)
    request_interval_ms: int = Field(default=500, ge=0, le=60_000)
    timeout_ms: int = Field(default=15_000, ge=100, le=120_000)


class CacheSettings(BaseModel):
    """缓存配置（§16、§35）。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_size: str = "5GB"
    """容量上限；超限后按 LRU 淘汰。"""

    ttl_seconds: int = Field(default=1800, ge=0)
    content_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=0)


class OutputSettings(BaseModel):
    """输出配置（§28、§35）。

    路径相对于「运行目录」（见 :mod:`mograb.config.paths`）。
    """

    model_config = ConfigDict(extra="forbid")

    directory: str = "exports"
    format: str = "epub"
    template: str = "{{author}} - {{title}}"
    chapter_template: str = "{{index}}. {{title}}"


class LoggingSettings(BaseModel):
    """日志配置（§36）。"""

    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    json_output: bool = Field(default=False, description="是否输出 JSON 行（适合机器解析）")
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5


class AppSettings(BaseSettings):
    """全局配置聚合。

    支持环境变量覆盖，前缀 ``MOGRAB_``，嵌套分隔符 ``__``，例如::

        MOGRAB_SERVER__PORT=9000
        MOGRAB_DOWNLOAD__CONCURRENCY=8
    """

    model_config = SettingsConfigDict(
        env_prefix="MOGRAB_",
        env_nested_delimiter="__",
        extra="forbid",
        case_sensitive=False,
    )

    server: ServerSettings = Field(default_factory=ServerSettings)
    download: DownloadSettings = Field(default_factory=DownloadSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


def load_settings(config_path: Path | None = None) -> AppSettings:
    """加载配置。

    读取顺序：TOML 文件 → 环境变量覆盖（由 pydantic-settings 处理）。

    Raises:
        ConfigError: 配置文件存在但格式非法。
    """
    paths: Paths = get_paths()
    path = config_path or paths.config_file

    file_data: dict[str, Any] = {}
    if path.is_file():
        try:
            file_data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(
                f"配置文件解析失败: {path}",
                details={"path": str(path), "reason": str(exc)},
            ) from exc

    return AppSettings(**file_data)


def write_default_config(path: Path, *, overwrite: bool = False) -> Path:
    """写出带注释的默认配置文件（``mog config init``）。"""
    if path.exists() and not overwrite:
        raise ConfigError(f"配置文件已存在: {path}", details={"path": str(path)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return path


DEFAULT_CONFIG_TOML = """\
# MoGrab 配置文件
# 优先级：CLI 参数 > Task 参数 > Source 配置 > 本文件 > 代码默认值

[server]
host = "127.0.0.1"
port = 48721

[download]
concurrency = 4
per_source_concurrency = 2
retry = 3
request_interval_ms = 500
timeout_ms = 15000

[cache]
enabled = true
max_size = "5GB"
ttl_seconds = 1800

[output]
directory = "exports"
format = "epub"
template = "{{author}} - {{title}}"
chapter_template = "{{index}}. {{title}}"

[logging]
level = "INFO"
json_output = false
"""


__all__ = [
    "DEFAULT_CONFIG_TOML",
    "AppSettings",
    "CacheSettings",
    "DownloadSettings",
    "LoggingSettings",
    "OutputSettings",
    "ServerSettings",
    "load_settings",
    "write_default_config",
]
