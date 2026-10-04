# SPDX-License-Identifier: GPL-3.0-only
"""内部 ID 生成。

领域模型里写的「MoGrab 内部 ID（ULID）」就是这里产出的东西。

为什么不用 ``uuid4``：ULID 前 48 位是毫秒时间戳，所以**按 ID 排序就等于按创建时间
排序**。排查问题时看一串 ID 能直接看出先后，不用再去 join 时间字段。
后面 80 位是随机数，同一毫秒内也不会撞。

编码用 Crockford Base32，26 个字符。去掉了容易看混的 I / L / O / U，
所以 ID 复制粘贴、口头念都不容易出错。
"""

from __future__ import annotations

import secrets
import time

# Crockford Base32：去掉了 I、L、O、U
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_ULID_LENGTH = 26
_TIMESTAMP_BITS = 48
_RANDOM_BITS = 80


def new_ulid(*, timestamp_ms: int | None = None) -> str:
    """生成一个 ULID。

    Args:
        timestamp_ms: 覆盖时间戳（毫秒）。测试里用来构造有序 ID。
    """
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ts < (1 << _TIMESTAMP_BITS):
        raise ValueError(f"时间戳超出 48 位范围: {ts}")

    value = (ts << _RANDOM_BITS) | secrets.randbits(_RANDOM_BITS)

    # 128 位按 5 位一组从高位往低位取，正好 26 组（前 2 位补零）
    return "".join(
        _ALPHABET[(value >> shift) & 0x1F] for shift in range(_ULID_LENGTH * 5 - 5, -1, -5)
    )


def new_id(prefix: str, *, timestamp_ms: int | None = None) -> str:
    """带前缀的 ID，形如 ``book_01J8X2QK...``。

    前缀是为了看日志和翻数据库时一眼能认出是什么对象。
    """
    return f"{prefix}_{new_ulid(timestamp_ms=timestamp_ms)}"


__all__ = ["new_id", "new_ulid"]
