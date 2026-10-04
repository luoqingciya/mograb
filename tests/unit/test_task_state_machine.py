# SPDX-License-Identifier: GPL-3.0-only
"""任务状态机与调度纯函数测试（规划书 §17、§18、§20）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mograb.domain.enums import (
    TASK_TRANSITIONS,
    TERMINAL_TASK_STATUSES,
    ChapterChangeKind,
    TaskStatus,
    TaskType,
    can_transition,
)
from mograb.domain.task import Task
from mograb.errors import InvalidTaskTransitionError
from mograb.source.engine import ChapterDraft
from mograb.task.scheduler import compute_chapter_diff

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _task(status: TaskStatus = TaskStatus.PENDING) -> Task:
    return Task(id="t1", type=TaskType.DOWNLOAD_BOOK, status=status, created_at=NOW)


class TestTaskStateMachine:
    @pytest.mark.parametrize(
        ("src", "dst"),
        [
            (TaskStatus.PENDING, TaskStatus.RUNNING),
            (TaskStatus.RUNNING, TaskStatus.SUCCESS),
            (TaskStatus.RUNNING, TaskStatus.RETRYING),
            (TaskStatus.RETRYING, TaskStatus.RUNNING),
            (TaskStatus.PAUSED, TaskStatus.PENDING),
            (TaskStatus.RUNNING, TaskStatus.PAUSED),
        ],
    )
    def test_allowed_transitions(self, src: TaskStatus, dst: TaskStatus) -> None:
        assert can_transition(src, dst)
        task = _task(src)
        task.transition_to(dst)
        assert task.status is dst

    @pytest.mark.parametrize(
        ("src", "dst"),
        [
            (TaskStatus.SUCCESS, TaskStatus.RUNNING),
            (TaskStatus.FAILED, TaskStatus.RUNNING),
            (TaskStatus.CANCELLED, TaskStatus.PENDING),
            (TaskStatus.PENDING, TaskStatus.SUCCESS),
        ],
    )
    def test_rejected_transitions(self, src: TaskStatus, dst: TaskStatus) -> None:
        assert not can_transition(src, dst)
        with pytest.raises(InvalidTaskTransitionError):
            _task(src).transition_to(dst)

    def test_terminal_states_have_no_exit(self) -> None:
        for status in TERMINAL_TASK_STATUSES:
            assert TASK_TRANSITIONS[status] == frozenset()

    def test_self_transition_is_noop(self) -> None:
        task = _task(TaskStatus.RUNNING)
        task.transition_to(TaskStatus.RUNNING)
        assert task.status is TaskStatus.RUNNING

    def test_progress_calculation(self) -> None:
        task = _task()
        task.total = 100
        task.completed = 40
        task.failed = 10
        assert task.progress == pytest.approx(0.5)

    def test_progress_with_zero_total(self) -> None:
        assert _task().progress == 0.0


class TestChapterDiff:
    def _draft(self, index: int, title: str, cid: str | None = None) -> ChapterDraft:
        return ChapterDraft(
            title=title,
            url=f"https://example.com/c/{index}",
            index=index,
            source_chapter_id=cid,
        )

    def test_all_new_when_local_empty(self) -> None:
        diff = compute_chapter_diff([], [self._draft(1, "第一章", "c1")])
        assert len(diff.new) == 1
        assert not diff.changed
        assert not diff.unchanged

    def test_unchanged_when_identical(self, sample_chapters) -> None:
        local = sample_chapters[:1]
        draft = ChapterDraft(
            title=local[0].title,
            url=local[0].url,
            index=local[0].index,
            source_chapter_id=local[0].source_chapter_id,
        )
        diff = compute_chapter_diff(local, [draft])
        assert len(diff.unchanged) == 1
        assert not diff.to_download

    def test_detects_new_chapters(self, sample_chapters) -> None:
        """规划书 §20 示例：本地 1-3，远程 1-5 → 应下载 4-5。"""
        local = sample_chapters
        remote = [
            ChapterDraft(
                title=c.title,
                url=c.url,
                index=c.index,
                source_chapter_id=c.source_chapter_id,
            )
            for c in local
        ] + [self._draft(4, "第四章", "c4"), self._draft(5, "第五章", "c5")]

        diff = compute_chapter_diff(local, remote)
        assert len(diff.new) == 2
        assert [d.index for d in diff.to_download] == [4, 5]

    def test_detects_changed_title(self, sample_chapters) -> None:
        local = sample_chapters[:1]
        draft = ChapterDraft(
            title="第一章（修订）",
            url=local[0].url,
            index=0,
            source_chapter_id=local[0].source_chapter_id,
        )
        diff = compute_chapter_diff(local, [draft])
        assert len(diff.changed) == 1

    def test_detects_missing_without_deleting(self, sample_chapters) -> None:
        """本地有、远程无的章节只标记 missing，不进入下载计划。"""
        local = sample_chapters
        remote = [
            ChapterDraft(
                title=local[0].title,
                url=local[0].url,
                index=0,
                source_chapter_id=local[0].source_chapter_id,
            )
        ]
        diff = compute_chapter_diff(local, remote)
        assert len(diff.missing) == 2
        assert not diff.to_download

    def test_identity_by_url_when_no_chapter_id(self, sample_chapters) -> None:
        local = sample_chapters[:1]
        draft = ChapterDraft(title=local[0].title, url=local[0].url, index=0)
        diff = compute_chapter_diff(local, [draft])
        assert len(diff.unchanged) == 1


@pytest.mark.unit
def test_change_kinds_are_distinct() -> None:
    """差异分类枚举互不相同（防止实现误用）。"""
    values = {k.value for k in ChapterChangeKind}
    assert len(values) == len(list(ChapterChangeKind))
