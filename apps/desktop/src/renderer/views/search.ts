// SPDX-License-Identifier: GPL-3.0-only
//
// 搜索视图。
//
// 对应 API 的 GET /search —— 默认跨源并发搜，单源失败不影响整体，
// 失败信息单独列出来。

import type { SearchItem } from '../../shared/types.js';
import { ApiError, search } from '../api.js';
import { el, replace } from '../dom.js';
import type { View } from './view.js';

export interface SearchViewDeps {
  /** 用户点了某条结果的「下载」。 */
  onDownload(item: SearchItem): void;
}

export function createSearchView(deps: SearchViewDeps): View {
  const input = el('input', {
    class: 'input',
    type: 'search',
    placeholder: '书名或作者',
    autofocus: true,
  });
  const submit = el('button', { class: 'btn primary', type: 'submit' }, '搜索');
  const status = el('div', { class: 'status' });
  const results = el('div', { class: 'results' });

  const form = el('form', { class: 'search-bar' }, input, submit);

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    void runSearch();
  });

  async function runSearch(): Promise<void> {
    const keyword = input.value.trim();
    if (!keyword) {
      return;
    }

    submit.disabled = true;
    replace(status, el('span', { class: 'muted' }, '搜索中…'));
    replace(results);

    try {
      const response = await search(keyword);
      renderResults(response.items, response.errors);
    } catch (error) {
      renderError(error);
    } finally {
      submit.disabled = false;
    }
  }

  function renderResults(items: SearchItem[], errors: { source_id: string; message: string }[]): void {
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

    replace(
      results,
      ...items.map((item) => renderItem(item)),
    );
  }

  function renderItem(item: SearchItem): HTMLElement {
    const download = el(
      'button',
      {
        class: 'btn',
        type: 'button',
        onclick: () => deps.onDownload(item),
      },
      '下载',
    );

    return el(
      'article',
      { class: 'card' },
      el(
        'div',
        { class: 'card-main' },
        el('div', { class: 'card-title' }, item.title),
        el('div', { class: 'card-meta' }, `${item.author ?? '佚名'} · ${item.source_id}`),
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
    el('p', { class: 'hint' }, '在所有启用的书源上搜。搜到之后点「下载」就开始抓。'),
    form,
    status,
    results,
  );

  return { element, dispose: () => {} };
}
