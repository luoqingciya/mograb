// SPDX-License-Identifier: GPL-3.0-only
//
// 渲染进程入口：等 Tauri 后端就绪后加载完整功能页签。

import type { SearchItem } from '../shared/types.js';
import {
  THEME_MODE_LABEL,
  THEME_STORAGE_KEY,
  type ThemeMode,
  nextThemeMode,
  normalizeThemeMode,
  resolveTheme,
} from '../shared/theme.js';
import { ApiError, configure, createTask, listSources } from './api.js';
import { el, replace, requireElement } from './dom.js';
import { createFindView } from './views/find.js';
import { createSearchView } from './views/search.js';
import { createSettingsView } from './views/settings.js';
import { type ShelfInitialTarget, createShelfView } from './views/shelf.js';
import { createSourcesView } from './views/sources.js';
import { createTasksView } from './views/tasks.js';
import type { View } from './views/view.js';

interface Page {
  id: string;
  label: string;
  create(arg?: unknown): View;
}

const PAGES: Page[] = [
  {
    id: 'search',
    label: '搜索',
    create: () =>
      createSearchView({
        onDownload: (item) => void handleDownload(item),
        onDirectDownload: (sourceId, url) => void handleDirectDownload(sourceId, url),
      }),
  },
  {
    id: 'shelf',
    label: '书架',
    create: (arg) =>
      createShelfView({
        initial: arg as ShelfInitialTarget | undefined,
        onNotify: notify,
        onGoToTasks: () => switchTo('tasks'),
      }),
  },
  {
    id: 'find',
    label: '全文检索',
    create: () =>
      createFindView({
        onOpenChapter: (bookId, chapterId) =>
          switchTo('shelf', { bookId, chapterId } satisfies ShelfInitialTarget),
      }),
  },
  {
    id: 'tasks',
    label: '任务',
    create: () => createTasksView({ onNotify: notify }),
  },
  {
    id: 'sources',
    label: '书源',
    create: () => createSourcesView({ onNotify: notify }),
  },
  {
    id: 'settings',
    label: '设置',
    create: () => createSettingsView({ onNotify: notify }),
  },
];

let current: View | null = null;
let noticeTimer: number | undefined;
let currentThemeMode: ThemeMode = 'dark';
const colorSchemeMedia =
  typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: light)')
    : null;

function readSavedThemeMode(): ThemeMode {
  try {
    return normalizeThemeMode(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return 'dark';
  }
}

function writeSavedThemeMode(mode: ThemeMode): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    // 忽略无存储权限环境
  }
}

function updateThemeButton(): void {
  const button = document.querySelector<HTMLButtonElement>('#theme-toggle');
  if (button) {
    button.textContent = `主题：${THEME_MODE_LABEL[currentThemeMode]}`;
  }
}

function applyTheme(): void {
  const prefersLight = colorSchemeMedia?.matches ?? false;
  document.documentElement.dataset['theme'] = resolveTheme(currentThemeMode, prefersLight);
  updateThemeButton();
}

function initTheme(): void {
  currentThemeMode = readSavedThemeMode();
  applyTheme();
  colorSchemeMedia?.addEventListener('change', () => {
    if (currentThemeMode === 'system') {
      applyTheme();
    }
  });
}

function cycleThemeMode(): void {
  currentThemeMode = nextThemeMode(currentThemeMode);
  writeSavedThemeMode(currentThemeMode);
  applyTheme();
}

function switchTo(pageId: string, arg?: unknown): void {
  const page = PAGES.find((candidate) => candidate.id === pageId);
  if (page === undefined) {
    return;
  }

  current?.dispose();
  current = page.create(arg);

  const content = requireElement<HTMLElement>('#content');
  replace(content, current.element);

  for (const button of document.querySelectorAll<HTMLButtonElement>('.nav-item')) {
    button.classList.toggle('active', button.dataset['page'] === pageId);
  }
}

function showStartingPlaceholder(): void {
  const content = requireElement<HTMLElement>('#content');
  replace(
    content,
    el(
      'section',
      { class: 'view' },
      el('h1', {}, '正在启动'),
      el('p', { class: 'hint' }, '正在等本地服务就绪……'),
    ),
  );
}

function notify(message: string, kind: 'info' | 'error' = 'info'): void {
  const bar = requireElement<HTMLElement>('#notice');
  if (noticeTimer !== undefined) {
    window.clearTimeout(noticeTimer);
    noticeTimer = undefined;
  }
  replace(bar, el('span', {}, message));
  const visible = message !== '';
  bar.classList.toggle('visible', visible);
  bar.classList.toggle('notice-error', visible && kind === 'error');
  bar.classList.toggle('notice-info', visible && kind !== 'error');
  if (visible) {
    noticeTimer = window.setTimeout(() => {
      replace(bar);
      bar.classList.remove('visible', 'notice-info', 'notice-error');
      noticeTimer = undefined;
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

async function handleDirectDownload(sourceId: string, url: string): Promise<void> {
  notify(`正在创建直链下载任务：${url}`);
  try {
    await createTask({
      type: 'download_book',
      sourceId,
      url,
    });
    notify('已加入下载队列');
    switchTo('tasks');
  } catch (error) {
    const message =
      error instanceof ApiError ? `${error.message}（${error.code}）` : String(error);
    notify(`创建任务失败：${message}`, 'error');
  }
}

function buildSidebar(): void {
  const sidebar = requireElement<HTMLElement>('#sidebar');
  const themeBtn = el(
    'button',
    {
      id: 'theme-toggle',
      class: 'btn btn-sm theme-toggle',
      type: 'button',
      title: '切换深色 / 浅色 / 跟随系统主题',
      onclick: cycleThemeMode,
    },
    `主题：${THEME_MODE_LABEL[currentThemeMode]}`,
  );
  replace(
    sidebar,
    el('div', { class: 'brand' }, 'MoGrab'),
    ...PAGES.map((page) =>
      el(
        'button',
        {
          class: 'nav-item',
          type: 'button',
          'data-page': page.id,
          onclick: () => switchTo(page.id),
        },
        page.label,
      ),
    ),
    el('div', { class: 'sidebar-footer' }, themeBtn),
  );
}

async function checkSources(): Promise<void> {
  try {
    const sources = await listSources();
    const usable = sources.filter((source) => source.enabled);
    if (usable.length === 0) {
      notify('还没有可用的书源，请在「书源」页粘贴 YAML 或选择本地文件安装。', 'error');
    }
  } catch (error) {
    console.warn('[main] 读取书源失败', error);
  }
}

async function waitForBackend(): Promise<BackendInfo> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (invoke === undefined) {
    throw new Error('未检测到 Tauri 运行时，请通过桌面客户端启动');
  }
  return await invoke<BackendInfo>('backend_wait');
}

async function bootstrap(): Promise<void> {
  initTheme();
  buildSidebar();
  showStartingPlaceholder();

  try {
    const { baseUrl, token } = await waitForBackend();
    configure(baseUrl, token);
    console.info('[main] 后端就绪:', baseUrl);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    replace(requireElement<HTMLElement>('#content'), el('section', { class: 'view' }));
    notify(`本地服务没起来：${message}`, 'error');
    console.error('[main] 后端不可用', error);
    return;
  }

  switchTo('search');
  await checkSources();
}

void bootstrap();
