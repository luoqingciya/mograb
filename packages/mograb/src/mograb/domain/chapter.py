# SPDX-License-Identifier: GPL-3.0-only
"""Chapter 领域模型与「章节身份」规则（规划书 §6.3）。

章节身份（Chapter Identity）
----------------------------

去重不能只依赖章节序号：站点可能插入卷标、重复章节、调整顺序。
因此按以下优先级解析稳定身份：

1. ``source_chapter_id`` —— 来源站提供的稳定 ID（最优）
2. ``normalized_url``   —— 规范化后的章节 URL
3. ``(index, title)``   —— 兜底，稳定性最差

同时保存 ``content_hash`` 用于检测「同一章节内容是否变化」，
这是增量更新（§20）判定 ``CHANGED`` 的依据。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

# 追踪参数黑名单：这些 query 参数不影响内容，规范化时移除
_TRACKING_QUERY_PREFIXES = ("utm_", "spm", "from", "ref", "share", "_t")
_TRACKING_QUERY_KEYS = frozenset({"sid", "t", "timestamp", "rand"})

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    """规范化 URL，用于生成稳定的章节身份。

    处理内容：

    - 协议与主机小写化，去掉默认端口
    - 移除 fragment
    - 移除追踪类 query 参数（utm_* / from / ref / share 等）
    - query 参数按 key 排序，保证顺序无关
    - 去除路径尾部多余斜杠（保留根路径）

    Examples:
        >>> normalize_url("https://A.com/Book/12/?utm_source=x&b=2&a=1#frag")
        'https://a.com/Book/12?a=1&b=2'
    """
    if not url:
        return ""

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # 去掉默认端口
    if (scheme == "http" and netloc.endswith(":80")) or (
        scheme == "https" and netloc.endswith(":443")
    ):
        netloc = netloc.rsplit(":", 1)[0]

    # 过滤追踪参数并排序
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _TRACKING_QUERY_KEYS:
            continue
        if any(lowered.startswith(p) for p in _TRACKING_QUERY_PREFIXES):
            continue
        kept.append((key, value))
    kept.sort()

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, netloc, path, urlencode(kept), ""))


def compute_content_hash(content: str) -> str:
    """计算正文内容哈希（用于变更检测）。

    归一化策略：先折叠空白，避免仅空白差异被误判为内容变化。
    算法固定为 BLAKE2b-128（快且碰撞率足够低）；变更算法需迁移既有数据。
    """
    normalized = _WHITESPACE_RE.sub(" ", content).strip()
    return hashlib.blake2b(normalized.encode("utf-8"), digest_size=16).hexdigest()


class Chapter(BaseModel):
    """一章的元数据与正文。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    # --- 标识 ---
    id: str = Field(description="MoGrab 内部 ID（ULID）")
    book_id: str
    source_chapter_id: str | None = None

    # --- 内容元数据 ---
    title: str
    url: str
    index: int = Field(description="在目录中的顺序（从 0 或 1 起由书源决定）")

    # --- 正文 ---
    content: str | None = None
    content_hash: str | None = None
    word_count: int = 0

    # --- 时间戳 ---
    created_at: datetime
    updated_at: datetime

    @property
    def normalized_url(self) -> str:
        """规范化 URL，作为次级身份。"""
        return normalize_url(self.url)

    @property
    def identity_key(self) -> str:
        """稳定身份键，按 §6.3 优先级解析。"""
        if self.source_chapter_id:
            return f"sid:{self.source_chapter_id}"
        if self.url:
            return f"url:{self.normalized_url}"
        return f"idx:{self.index}:{self.title}"

    def refresh_content(self, content: str) -> bool:
        """写入正文并更新哈希/字数，返回内容是否发生变化。"""
        new_hash = compute_content_hash(content)
        changed = new_hash != self.content_hash
        self.content = content
        self.content_hash = new_hash
        self.word_count = len(content)
        return changed


@dataclass(slots=True)
class ChapterSearchHit:
    """本地全文搜索的一条命中。

    这是**查询结果**而不是实体，所以用 dataclass 而不是 pydantic 模型
    （与 :class:`~mograb.source.engine.BookDraft` 同类）。

    ``snippet`` 是命中位置附近的片段，**不是整章正文** —— 一本几千章的书
    搜一次就把几十兆正文全读进内存是不可接受的。片段由仓储在查询时就地截好。
    """

    book_id: str
    book_title: str
    chapter_id: str
    chapter_title: str
    chapter_index: int
    snippet: str


__all__ = ["Chapter", "ChapterSearchHit", "compute_content_hash", "normalize_url"]
