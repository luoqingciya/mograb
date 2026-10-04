# SPDX-License-Identifier: GPL-3.0-only
"""任务子系统：队列、Worker 池、调度与生命周期管理。

下载不是同步函数，而是任务（规划书 §17）。
"""

from .manager import TaskManager, TaskRepository
from .queue import TaskQueue
from .scheduler import ChapterDiff, DownloadPlan, DownloadScheduler, compute_chapter_diff
from .worker import TaskHandler, WorkerPool

__all__ = [
    "ChapterDiff",
    "DownloadPlan",
    "DownloadScheduler",
    "TaskHandler",
    "TaskManager",
    "TaskQueue",
    "TaskRepository",
    "WorkerPool",
    "compute_chapter_diff",
]
