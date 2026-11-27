// SPDX-License-Identifier: GPL-3.0-only
//
// 搜索视图：支持跨源筛选、按书源直链下载。

import type { SearchItem, SourceOut } from '../../shared/types.js';
import { ApiError, listSources, search } from '../api.js';
import { el, replace } from '../dom.js';
import type { View } from './view.js';

export interface SearchViewDeps {
  onDownload(item: SearchItem): void;
  onDirectDownload(sourceId: string, url: string): void;
}

export function createSearchView(deps: SearchViewDeps): View {
  const input = el('input', {
    class: 'input',
    type: 'search',
    placeholder: '书名或作者',
    autofocus: true,
  });
  const submit = el('button', { class: 'btn primary', type: 'submit' }, '搜索');
  const filterRow = el('div', { class: 'chip-row' });
  const status = el('div', { class: 'status' });
  const results = el('div', { class: 'results' });

  const urlSourceSelect = el('select', { class: 'input select-sm' });
  const urlInput = el('input', {
    class: 'input',
    type: 'url',
    placeholder: '粘贴书籍详情页 URL，如 https://example.com/book/1001',
  });
  const urlSubmit = el('button', { class: 'btn', type: 'submit' }, '直链下载');
  const urlForm = el('form', { class: 'inline-form' }, urlSourceSelect, urlInput, urlSubmit);
  const urlPanel = el(
    'details',
    { class: 'drawer' },
    el('summary', { class: 'drawer-summary' }, '按 URL 直接下载'),
    urlForm,
  );

  let searchableSources: SourceOut[] = [];
  const selectedSources = new Set<string>();

  const form = el('form', { class: 'search-bar' }, input, submit);

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    void runSearch();
  });

  urlForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const sid = urlSourceSelect.value.trim();
    const rawUrl = urlInput.value.trim();
    if (!sid || !rawUrl) {
      return;
    }
    deps.onDirectDownload(sid, rawUrl);
  });

  async function loadAvailableSources(): Promise<void> {
    try {
      const all = await listSources();
      const enabled = all.filter((s) => s.enabled);
      searchableSources = enabled.filter((s) => s.capabilities.includes('search'));
      renderSourceChips();

      replace(
        urlSourceSelect,
        ...(enabled.length > 0
          ? enabled.map((s) => el('option', { value: s.id }, `${s.name} (${s.id})`))
          : [el('option', { value: '' }, '暂无可用书源')]),
      );
      urlSubmit.disabled = enabled.length === 0;
    } catch {
      // checkSources 已统一在全局通知错误
    }
  }

  function renderSourceChips(): void {
    if (searchableSources.length === 0) {
      replace(filterRow);
      return;
    }

    const allChip = el(
      'button',
      {
        class: `chip${selectedSources.size === 0 ? ' active' : ''}`,
        type: 'button',
        onclick: () => {
          selectedSources.clear();
          renderSourceChips();
        },
      },
      `全部启用源 (${searchableSources.length})`,
    );

    const chips = searchableSources.map((src) => {
      const active = selectedSources.has(src.id);
      return el(
        'button',
        {
          class: `chip${active ? ' active' : ''}`,
          type: 'button',
          onclick: () => {
            if (selectedSources.has(src.id)) {
              selectedSources.delete(src.id);
            } else {
              selectedSources.add(src.id);
            }
            renderSourceChips();
          },
        },
        src.name,
      );
    });

    replace(filterRow, allChip, ...chips);
  }

  async function runSearch(): Promise<void> {
    const keyword = input.value.trim();
    if (!keyword) {
      return;
    }

    submit.disabled = true;
    replace(status, el('span', { class: 'muted' }, '搜索中…'));
    replace(results);

    try {
      const filterIds = [...selectedSources];
      const response = await search(keyword, filterIds, 20);
      renderResults(response.items, response.errors);
    } catch (error) {
      renderError(error);
    } finally {
      submit.disabled = false;
    }
  }

  function renderResults(
    items: SearchItem[],
    errors: { source_id: string; message: string }[],
  ): void {
    if (items.length === 0 && errors.length === 0) {
      replace(status, el('span', { class: 'muted' }, '没搜到结果'));
      return;
    }

    replace(
      status,
      el('span', { class: 'muted' }, `共 ${items.length} 条`),
      ...errors.map((err) =>
        el('span', { class: 'warn' }, `${err.source_id} 失败：${err.message}`),
      ),
    );

    replace(results, ...items.map((item) => renderItem(item)));
  }

  function renderItem(item: SearchItem): HTMLElement {
    const download = el(
      'button',
      {
        class: 'btn primary',
        type: 'button',
        onclick: () => deps.onDownload(item),
      },
      '下载',
    );

    const intro = item.intro?.trim();

    return el(
      'article',
      { class: 'card' },
      el(
        'div',
        { class: 'card-main' },
        el('div', { class: 'card-title' }, item.title),
        el('div', { class: 'card-meta' }, `${item.author ?? '佚名'} · ${item.source_id}`),
        intro ? el('div', { class: 'card-desc' }, intro) : null,
      ),
      download,
    );
  }

  function renderError(error: unknown): void {
    const message =
      error instanceof ApiError ? `${error.message}（${error.code}）` : String(error);
    replace(status, el('span', { class: 'error' }, message));
  }

  const element = el(
    'section',
    { class: 'view' },
    el('h1', {}, '搜索'),
    el('p', { class: 'hint' }, '并发搜索启用的书源；也可展开下方输入书籍详情页直链下载。'),
    form,
    filterRow,
    urlPanel,
    status,
    results,
  );

  void loadAvailableSources();

  return { element, dispose: () => {} };
}
