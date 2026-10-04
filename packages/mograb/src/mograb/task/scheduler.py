# SPDX-License-Identifier: GPL-3.0-only
"""下载调度与增量更新（规划书 §18、§20）。

本模块包含两块：

1. :func:`compute_chapter_diff` —— **纯函数**的章节差异计算。
   这是增量更新的核心，必须可离线单元测试（规划书 §47 Unit Test 明确要求
   覆盖 Chapter Identity）。

2. :class:`DownloadScheduler` —— 按 §18 的流程编排一次完整下载：

       Load Book → Load Chapters → Determine Missing → Download
       → Clean → Validate → Persist → (Export)

关键一致性约束（规划书 §39）：

    Download → Validate → **Transaction** → Persist

只有持久化成功后才把 TaskItem 标记为 SUCCESS，避免「下载成功但库里没有」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.chapter import Chapter, normalize_url
from ..logging.setup import get_logger
from ..source.engine import ChapterDraft

_logger = get_logger(__name__)


@dataclass(slots=True)
class ChapterDiff:
    """本地目录与远程目录的差异结果。"""

    new: list[ChapterDraft] = field(default_factory=list)
    changed: list[ChapterDraft] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    """本地存在但远程已消失的章节身份键（仅告警，不删除）。"""
    unchanged: list[ChapterDraft] = field(default_factory=list)

    @property
    def to_download(self) -> list[ChapterDraft]:
        """需要下载的章节 = 新增 + 内容变化。"""
        return [*self.new, *self.changed]

    @property
    def total(self) -> int:
        return len(self.new) + len(self.changed) + len(self.missing) + len(self.unchanged)


def _candidate_keys(
    *, source_chapter_id: str | None, url: str | None, index: int, title: str
) -> set[str]:
    """生成一个章节的全部候选身份键。

    使用**候选集合**而非单一键，是为了让 diff 对「书源某次更新后
    不再返回 source_chapter_id」这类变化保持鲁棒：只要 URL 身份仍能对上，
    就不会把整本书误判为「全新章节」。

    Returns:
        至少包含一个键；优先级信息由键前缀（``sid:`` > ``url:`` > ``idx:``）表达。
    """
    keys: set[str] = set()
    if source_chapter_id:
        keys.add(f"sid:{source_chapter_id}")
    if url:
        keys.add(f"url:{normalize_url(url)}")
    if not keys:
        keys.add(f"idx:{index}:{title}")
    return keys


def compute_chapter_diff(
    local: list[Chapter],
    remote: list[ChapterDraft],
) -> ChapterDiff:
    """计算章节差异。

    判定规则：

    - 远程有、本地无 → ``new``
    - 两边都有，且 ``title`` 或规范化 ``url`` 变化 → ``changed``
    - 两边都有且未变 → ``unchanged``
    - 本地有、远程无 → ``missing``（**不自动删除**，仅提示用户）

    匹配基于**候选身份集合的交集**（见 :func:`_candidate_keys`）。

    Note:
        内容级变更（``content_hash``）需在下载后比对，此处只做目录级比对；
        目录级未变但内容被站点静默修改的情况由 ``mog update --deep`` 覆盖。
    """
    # 建立「候选键 -> 本地章节」索引
    local_index: dict[str, Chapter] = {}
    for chapter in local:
        for key in _candidate_keys(
            source_chapter_id=chapter.source_chapter_id,
            url=chapter.url,
            index=chapter.index,
            title=chapter.title,
        ):
            local_index.setdefault(key, chapter)

    matched: set[str] = set()
    diff = ChapterDiff()

    for draft in remote:
        candidates = _candidate_keys(
            source_chapter_id=draft.source_chapter_id,
            url=draft.url,
            index=draft.index,
            title=draft.title,
        )
        existing: Chapter | None = None
        for key in candidates:
            found = local_index.get(key)
            if found is not None and found.id not in matched:
                existing = found
                break

        if existing is None:
            diff.new.append(draft)
            continue

        matched.add(existing.id)
        if existing.title != draft.title or normalize_url(existing.url) != normalize_url(draft.url):
            diff.changed.append(draft)
        else:
            diff.unchanged.append(draft)

    diff.missing = [c.identity_key for c in local if c.id not in matched]
    return diff


@dataclass(slots=True)
class DownloadPlan:
    """一次下载/更新任务的执行计划。"""

    book_id: str
    total: int
    to_download: list[ChapterDraft]
    skipped: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        """无需下载任何章节（已是最新）。"""
        return not self.to_download


class DownloadScheduler:
    """下载流程编排器。

    Note:
        具体实现依赖 Storage / Content / Export 层的仓储接口；
        骨架阶段保留契约与流程注释，待各层实现后填充。
        流程顺序不可调整（规划书 §18）。
    """

    def __init__(
        self,
        *,
        engine: object,
        book_repo: object,
        chapter_repo: object,
        content_pipeline: object | None = None,
        exporter: object | None = None,
    ) -> None:
        self._engine = engine
        self._books = book_repo
        self._chapters = chapter_repo
        self._pipeline = content_pipeline
        self._exporter = exporter

    async def plan_update(self, book_id: str) -> DownloadPlan:
        """生成增量更新计划（不执行下载）。

        对应 ``mog update <book-id> --dry-run`` 与 §20 的流程。
        """
        raise NotImplementedError("plan_update 待 Storage 层实现后接入；契约见 docs/api/api-v1.md")

    async def run(self, book_id: str, *, task_id: str | None = None) -> DownloadPlan:
        """执行完整下载流程（§18）。

        流程::

            Load Book
              ↓
            Load Chapters（远程目录）
              ↓
            Determine Missing（compute_chapter_diff）
              ↓
            Download（受 SourceLimiter 约束的并发下载）
              ↓
            Clean + Validate（Content Pipeline）
              ↓
            Persist（事务）
              ↓
            Export（可选）
        """
        raise NotImplementedError("run 待 Storage / Content / Export 层实现后接入")


__all__ = ["ChapterDiff", "DownloadPlan", "DownloadScheduler", "compute_chapter_diff"]
