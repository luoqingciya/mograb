// SPDX-License-Identifier: GPL-3.0-only
//
// 渲染进程入口。
//
// 先等后端就绪，再搭界面。后端起不来的话，界面再漂亮也没用 ——
// 所以这一步失败就直接显示原因，不装作没事。

import type { SearchItem } from '../shared/types.js';
import { ApiError, createTask, listSources, setBaseUrl } from './api.js';
import { el, replace, requireElement } from './dom.js';
import { createSearchView } from './views/search.js';
import { createTasksView } from './views/tasks.js';
import type { View } from './views/view.js';

interface Page {
  id: string;
  label: string;
  /** 未实现的页面在侧边栏里灰着。 */
  ready: boolean;
  create(): View;
}

function placeholderView(title: string, note: string): View {
  return {
    element: el(
      'section',
      { class: 'view' },
      el('h1', {}, title),
      el('p', { class: 'hint' }, note),
    ),
    dispose: () => {},
  };
}

const PAGES: Page[] = [
  {
    id: 'search',
    label: '搜索',
    ready: true,
    create: () => createSearchView({ onDownload: (item) => void handleDownload(item) }),
  },
  {
    id: 'tasks',
    label: '下载',
    ready: true,
    create: () => createTasksView(),
  },
  {
    id: 'shelf',
    label: '书架',
    ready: false,
    create: () => placeholderView('书架', '还没做。先看「下载」页里的任务。'),
  },
  {
    id: 'sources',
    label: '书源',
    ready: false,
    create: () =>
      placeholderView(
        '书源管理',
        '还没做。目前用命令行装：mog source install <source.yaml>',
      ),
  },
  {
    id: 'settings',
    label: '设置',
    ready: false,
    create: () => placeholderView('设置', '还没做。配置文件在 data/config.toml。'),
  },
];

let current: View | null = null;

function switchTo(pageId: string): void {
  const page = PAGES.find((candidate) => candidate.id === pageId);
  if (page === undefined || !page.ready) {
    return;
  }

  current?.dispose();
  current = page.create();

  const content = requireElement<HTMLElement>('#content');
  replace(content, current.element);

  for (const button of document.querySelectorAll<HTMLButtonElement>('.nav-item')) {
    button.classList.toggle('active', button.dataset['page'] === pageId);
  }
}

function notify(message: string, kind: 'info' | 'error' = 'info'): void {
  const bar = requireElement<HTMLElement>('#notice');
  replace(bar, el('span', { class: kind === 'error' ? 'error' : 'muted' }, message));
  bar.classList.toggle('visible', message !== '');
  if (message !== '') {
    window.setTimeout(() => {
      replace(bar);
      bar.classList.remove('visible');
    }, 6000);
  }
}

async function handleDownload(item: SearchItem): Promise<void> {
  notify(`正在创建下载任务：${item.title}`);
  try {
    await createTask({
      type: 'download_book',
      sourceId: item.source_id,
      url: item.url,
    });
    notify(`已加入下载队列：${item.title}`);
    switchTo('tasks');
  } catch (error) {
    const message =
      error instanceof ApiError ? `${error.message}（${error.code}）` : String(error);
    notify(`创建任务失败：${message}`, 'error');
  }
}

function buildSidebar(): void {
  const sidebar = requireElement<HTMLElement>('#sidebar');
  replace(
    sidebar,
    el('div', { class: 'brand' }, 'MoGrab'),
    ...PAGES.map((page) =>
      el(
        'button',
        {
          class: `nav-item${page.ready ? '' : ' disabled'}`,
          type: 'button',
          'data-page': page.id,
          disabled: !page.ready,
          onclick: () => switchTo(page.id),
        },
        page.label,
      ),
    ),
  );
}

async function checkSources(): Promise<void> {
  try {
    const sources = await listSources();
    const usable = sources.filter((source) => source.enabled);
    if (usable.length === 0) {
      notify('还没有可用的书源。用 mog source install <source.yaml> 装一个。', 'error');
    }
  } catch (error) {
    console.warn('[main] 读取书源失败', error);
  }
}

async function bootstrap(): Promise<void> {
  buildSidebar();
  switchTo('search');

  try {
    const baseUrl = await window.mograb.waitForBackend();
    setBaseUrl(baseUrl);
    console.info('[main] 后端就绪:', baseUrl);
    await checkSources();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    notify(`本地服务没起来：${message}`, 'error');
    console.error('[main] 后端不可用', error);
  }
}

void bootstrap();
