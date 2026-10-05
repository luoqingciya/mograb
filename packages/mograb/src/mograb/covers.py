# SPDX-License-Identifier: GPL-3.0-only
"""封面下载与本地存储。

**封面是可选资产，拿不到不该让下载任务失败。** 站点没给封面、CDN 临时挂了、
书源没把 CDN 域名写进 ``permissions.network`` —— 都是正常会发生的事。
所以这里的约定是「尽力而为，失败返回 None，并把原因写进日志」。

存放位置是 ``<数据目录>/covers/<book_id>.<ext>``，
:attr:`~mograb.domain.book.Book.cover_path` 记的是**相对数据目录**的路径
（``covers/xxx.jpg``）—— 数据目录整个拷走之后还能对上。
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from .config import Paths
from .domain.book import Book
from .errors import MoGrabError
from .logging.setup import get_logger
from .network import HttpClient

_logger = get_logger(__name__)

MAX_COVER_BYTES = 8 * 1024 * 1024
"""封面大小上限。

站点的封面通常几十 KB。设这个上限是为了不让它变成一个「往任意 URL 下载
大文件」的口子。
"""

_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Content-Type → 后缀。站点经常用 ``image/jpeg`` 配一个没有后缀的 URL。
_CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class CoverStore:
    """把书源声明的封面下载到本地。"""

    def __init__(self, *, http: HttpClient, paths: Paths) -> None:
        self._http = http
        self._paths = paths

    async def ensure(
        self, book: Book, *, allowed_domains: Collection[str] | None = None
    ) -> str | None:
        """确保这本书的封面在本地。

        Args:
            book: 目标书籍。读 ``cover_url`` / ``cover_path``。
            allowed_domains: 书源声明的 ``permissions.network``。
                **封面请求同样受它约束** —— 白名单的意义就是「书源声明了
                什么就只能访问什么」，给封面开后门等于把这道门拆了。

        Returns:
            相对数据目录的路径（``covers/<id>.jpg``）；没拿到就 ``None``。
        """
        if book.cover_path:
            return book.cover_path
        if not book.cover_url:
            return None

        try:
            result = await self._http.fetch(
                "GET",
                book.cover_url,
                source_id=book.source_id,
                allowed_domains=allowed_domains,
            )
        except MoGrabError as exc:
            # 最常见的一种：封面在 CDN 上，而书源只声明了主站域名。
            # 这条日志要说清楚「怎么修」，否则用户只会看到「没有封面」。
            _logger.warning(
                "cover.fetch_failed",
                book_id=book.id,
                url=book.cover_url,
                error=exc.message,
                hint=("如果封面在别的域名（CDN）上，把它加进书源的 permissions.network 就能下载"),
            )
            return None

        if len(result.content) > MAX_COVER_BYTES:
            _logger.warning(
                "cover.too_large",
                book_id=book.id,
                url=book.cover_url,
                size=len(result.content),
                limit=MAX_COVER_BYTES,
            )
            return None

        suffix = _guess_suffix(book.cover_url, result.headers.get("content-type", ""))
        if suffix is None:
            _logger.warning(
                "cover.unknown_format",
                book_id=book.id,
                url=book.cover_url,
                content_type=result.headers.get("content-type"),
            )
            return None

        # 换过后缀的旧文件要清掉 —— 站点把 jpg 换成 png 之后，
        # 不删的话会同时留着两份，而 `cover_path` 只指向新的那个。
        _remove_stale(self._paths.covers_dir, book.id, keep=suffix)

        target = self._paths.covers_dir / f"{book.id}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.content)

        relative = f"{target.parent.name}/{target.name}"
        _logger.info("cover.saved", book_id=book.id, path=relative, size=len(result.content))
        return relative


def _guess_suffix(url: str, content_type: str) -> str | None:
    """定出封面文件的后缀。

    先看 ``Content-Type`` —— 站点经常用一个没有后缀的图片 URL
    （``/img?id=123``），从 URL 上猜不出来。
    """
    mapped = _CONTENT_TYPE_SUFFIX.get(content_type.split(";")[0].strip().lower())
    if mapped:
        return mapped

    suffix = Path(url.split("?")[0]).suffix.lower()
    return suffix if suffix in _SUFFIXES else None


def _remove_stale(covers_dir: Path, book_id: str, *, keep: str) -> None:
    for candidate in covers_dir.glob(f"{book_id}.*"):
        if candidate.suffix.lower() != keep:
            candidate.unlink(missing_ok=True)


__all__ = ["MAX_COVER_BYTES", "CoverStore"]
