// SPDX-License-Identifier: GPL-3.0-only
//
// 任务与导出历史视图：状态筛选、SSE 实时进度、暂停/继续/取消/重试、近期导出列表。

import type { ExportOut, TaskOut, TaskStatus } from '../../shared/types.js';
import {
  EXPORT_STATUS_LABEL,
  TASK_STATUS_LABEL,
  formatBytes,
  isTerminal,
} from '../../shared/types.js';
import {
  ApiError,
  cancelTask,
  listExports,
  listTasks,
  pauseTask,
  resumeTask,
  retryTask,
  subscribeTaskEvents,
} from '../api.js';
import { el, replace } from '../dom.js';
import type { View } from './view.js';

const TYPE_LABEL: Record<string, string> = {
  download_book: '下载',
  update_book: '更新',
  export_book: '导出',
  refresh_source: '刷新书源',
};

type TaskFilter = 'all' | 'active' | 'success' | 'failed';

export interface TasksViewDeps {
  onNotify(message: string, kind?: 'info' | 'error'): void;
}

export function createTasksView(deps: TasksViewDeps): View {
  const filterRow = el('div', { class: 'chip-row' });
  const list = el('div', { class: 'task-list' });
  const exportList = el('div', { class: 'task-list' });
  const status = el('div', { class: 'status' });
  const tasks = new Map<string, TaskOut>();
  let exports: ExportOut[] = [];
  let currentFilter: TaskFilter = 'all';
  let disposed = false;

  const unsubscribe = subscribeTaskEvents((event) => {
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
    if (event.type === 'export_book' && isTerminal(event.status)) {
      void refreshExports();
    }
    render();
  });

  function formatError(error: unknown): string {
    return error instanceof ApiError ? `${error.message}（${error.code}）` : String(error);
  }

  async function refresh(): Promise<void> {
    try {
      const [loadedTasks, loadedExports] = await Promise.all([
        listTasks(100),
        listExports(20),
      ]);
      if (disposed) return;
      tasks.clear();
      for (const task of loadedTasks) {
        tasks.set(task.id, task);
      }
      exports = loadedExports;
      render();
    } catch (error) {
      if (disposed) return;
      replace(status, el('span', { class: 'error' }, formatError(error)));
    }
  }

  async function refreshExports(): Promise<void> {
    try {
      exports = await listExports(20);
      if (!disposed) {
        renderExports();
      }
    } catch {
      // 忽略后台刷新误差
    }
  }

  async function runAction(
    action: () => Promise<TaskOut>,
    label: string,
  ): Promise<void> {
    try {
      const updated = await action();
      tasks.set(updated.id, updated);
      render();
      deps.onNotify(`${label}成功`);
    } catch (error) {
      deps.onNotify(`${label}失败：${formatError(error)}`, 'error');
    }
  }

  function renderFilterChips(): void {
    const defs: { id: TaskFilter; label: string }[] = [
      { id: 'all', label: '全部' },
      { id: 'active', label: '进行中' },
      { id: 'success', label: '已完成' },
      { id: 'failed', label: '失败 / 取消' },
    ];
    replace(
      filterRow,
      ...defs.map((d) =>
        el(
          'button',
          {
            class: `chip${currentFilter === d.id ? ' active' : ''}`,
            type: 'button',
            onclick: () => {
              currentFilter = d.id;
              render();
            },
          },
          d.label,
        ),
      ),
      el(
        'button',
        {
          class: 'chip',
          type: 'button',
          onclick: () => void refresh(),
        },
        '刷新',
      ),
    );
  }

  function render(): void {
    renderFilterChips();

    const sorted = [...tasks.values()].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    );
    const activeCount = sorted.filter((t) => !isTerminal(t.status)).length;

    const visible = sorted.filter((task) => {
      if (currentFilter === 'active') return !isTerminal(task.status);
      if (currentFilter === 'success') return task.status === 'success';
      if (currentFilter === 'failed') {
        return task.status === 'failed' || task.status === 'cancelled';
      }
      return true;
    });

    replace(
      status,
      el(
        'span',
        { class: 'muted' },
        activeCount > 0 ? `${activeCount} 个进行中` : '暂无进行中的任务',
      ),
      el('span', { class: 'muted' }, `当前显示 ${visible.length} 条`),
    );

    if (visible.length === 0) {
      replace(
        list,
        el('p', { class: 'hint' }, '还没有匹配的任务。去「搜索」或「书架」页触发任务吧。'),
      );
    } else {
      replace(list, ...visible.map((task) => renderTask(task)));
    }

    renderExports();
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

    const targetHint = task.book_id ?? task.source_id ?? '';
    const counts =
      total > 0
        ? `${task.completed}/${total}${task.failed > 0 ? `，失败 ${task.failed}` : ''}`
        : '等待开始';

    const actions: HTMLElement[] = [];
    if (task.status === 'running' || task.status === 'pending' || task.status === 'retrying') {
      actions.push(
        el(
          'button',
          {
            class: 'btn btn-sm',
            type: 'button',
            onclick: () => void runAction(() => pauseTask(task.id), '暂停任务'),
          },
          '暂停',
        ),
        el(
          'button',
          {
            class: 'btn btn-sm danger',
            type: 'button',
            onclick: () => void runAction(() => cancelTask(task.id), '取消任务'),
          },
          '取消',
        ),
      );
    } else if (task.status === 'paused') {
      actions.push(
        el(
          'button',
          {
            class: 'btn btn-sm primary',
            type: 'button',
            onclick: () => void runAction(() => resumeTask(task.id), '继续任务'),
          },
          '继续',
        ),
        el(
          'button',
          {
            class: 'btn btn-sm danger',
            type: 'button',
            onclick: () => void runAction(() => cancelTask(task.id), '取消任务'),
          },
          '取消',
        ),
      );
    } else if (task.status === 'failed' || task.status === 'cancelled') {
      actions.push(
        el(
          'button',
          {
            class: 'btn btn-sm',
            type: 'button',
            onclick: () => void runAction(() => retryTask(task.id), '重试任务'),
          },
          '重试',
        ),
      );
    }

    return el(
      'article',
      { class: 'card task' },
      el(
        'div',
        { class: 'card-main' },
        el(
          'div',
          { class: 'card-title-row' },
          el(
            'span',
            { class: 'card-title' },
            `${TYPE_LABEL[task.type] ?? task.type} · ${TASK_STATUS_LABEL[task.status]}`,
          ),
          targetHint ? el('span', { class: 'badge' }, targetHint) : null,
        ),
        el('div', { class: 'card-meta' }, `${counts} · ${task.id}`),
        bar,
        task.error_message !== null
          ? el('div', { class: 'error' }, `[${task.error_code}] ${task.error_message}`)
          : null,
      ),
      actions.length > 0 ? el('div', { class: 'card-actions' }, ...actions) : null,
    );
  }

  function renderExports(): void {
    if (exports.length === 0) {
      replace(exportList, el('p', { class: 'hint' }, '暂无导出记录。'));
      return;
    }

    replace(
      exportList,
      ...exports.map((rec) => {
        const statusText = EXPORT_STATUS_LABEL[rec.status] ?? rec.status;
        const sizeText = rec.size_bytes > 0 ? formatBytes(rec.size_bytes) : '-';
        return el(
          'article',
          { class: 'card' },
          el(
            'div',
            { class: 'card-main' },
            el(
              'div',
              { class: 'card-title-row' },
              el('span', { class: 'card-title' }, `${rec.format.toUpperCase()} · ${statusText}`),
              el('span', { class: 'badge' }, sizeText),
            ),
            el('div', { class: 'card-meta' }, `书籍：${rec.book_id}`),
            rec.path ? el('div', { class: 'card-sub mono' }, rec.path) : null,
            rec.error_message ? el('div', { class: 'error' }, rec.error_message) : null,
          ),
        );
      }),
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
    el('h1', {}, '下载与导出任务'),
    el('p', { class: 'hint' }, '进度通过 SSE 实时推送，可直接暂停、恢复、取消或重试任务。'),
    filterRow,
    status,
    list,
    el('h2', { class: 'section-title' }, '近期导出记录'),
    exportList,
  );

  void refresh();

  return {
    element,
    dispose: () => {
      disposed = true;
      unsubscribe();
    },
  };
}
