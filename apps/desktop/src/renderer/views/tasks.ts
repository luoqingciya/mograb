// SPDX-License-Identifier: GPL-3.0-only
//
// 任务视图。
//
// 数据来源有两条：进页面时拉一次 /tasks，之后靠 SSE 推更新。
// 之所以两条都要 —— SSE 只推「变更」，拉一次才能看到历史任务。

import type { TaskOut, TaskStatus } from '../../shared/types.js';
import { TASK_STATUS_LABEL, isTerminal } from '../../shared/types.js';
import { ApiError, listTasks, subscribeTaskEvents } from '../api.js';
import { el, replace } from '../dom.js';
import type { View } from './view.js';

const TYPE_LABEL: Record<string, string> = {
  download_book: '下载',
  update_book: '更新',
  export_book: '导出',
  refresh_source: '刷新书源',
};

export function createTasksView(): View {
  const list = el('div', { class: 'task-list' });
  const status = el('div', { class: 'status' });
  const tasks = new Map<string, TaskOut>();

  const unsubscribe = subscribeTaskEvents((event) => {
    // 事件只带进度，不带完整任务，所以本地合并而不是整体替换
    const existing = tasks.get(event.task_id);
    if (existing === undefined) {
      void refresh();
      return;
    }
    tasks.set(event.task_id, {
      ...existing,
      status: event.status,
      total: event.total,
      completed: event.completed,
      failed: event.failed,
      error_code: event.error_code,
      error_message: event.error_message,
    });
    render();
  });

  async function refresh(): Promise<void> {
    try {
      const loaded = await listTasks();
      tasks.clear();
      for (const task of loaded) {
        tasks.set(task.id, task);
      }
      render();
    } catch (error) {
      const message =
        error instanceof ApiError ? `${error.message}（${error.code}）` : String(error);
      replace(status, el('span', { class: 'error' }, message));
    }
  }

  function render(): void {
    const sorted = [...tasks.values()].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    );

    const active = sorted.filter((task) => !isTerminal(task.status)).length;
    replace(
      status,
      el('span', { class: 'muted' }, active > 0 ? `${active} 个进行中` : '暂无进行中的任务'),
    );

    if (sorted.length === 0) {
      replace(list, el('p', { class: 'hint' }, '还没有任务。去「搜索」页找一本下下看。'));
      return;
    }
    replace(list, ...sorted.map((task) => renderTask(task)));
  }

  function renderTask(task: TaskOut): HTMLElement {
    const total = task.total;
    const done = task.completed + task.failed;
    const ratio = total > 0 ? Math.min(1, done / total) : 0;

    const bar = el(
      'div',
      { class: 'progress' },
      el('div', {
        class: `progress-fill ${barClass(task.status)}`,
        style: `width: ${(ratio * 100).toFixed(1)}%`,
      }),
    );

    const counts =
      total > 0
        ? `${task.completed}/${total}${task.failed > 0 ? `，失败 ${task.failed}` : ''}`
        : '等待开始';

    return el(
      'article',
      { class: 'card task' },
      el(
        'div',
        { class: 'card-main' },
        el(
          'div',
          { class: 'card-title' },
          `${TYPE_LABEL[task.type] ?? task.type} · ${TASK_STATUS_LABEL[task.status]}`,
        ),
        el('div', { class: 'card-meta' }, counts),
        bar,
        task.error_message !== null
          ? el('div', { class: 'error' }, `[${task.error_code}] ${task.error_message}`)
          : null,
      ),
    );
  }

  function barClass(state: TaskStatus): string {
    if (state === 'success') return 'ok';
    if (state === 'failed') return 'bad';
    if (state === 'cancelled') return 'idle';
    return '';
  }

  const element = el(
    'section',
    { class: 'view' },
    el('h1', {}, '下载任务'),
    el('p', { class: 'hint' }, '进度通过 SSE 实时推过来。'),
    status,
    list,
  );

  void refresh();

  return {
    element,
    dispose: unsubscribe,
  };
}
