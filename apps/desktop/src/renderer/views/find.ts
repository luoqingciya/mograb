// SPDX-License-Identifier: GPL-3.0-only
//
// 本地全文搜索视图：不联网检索已下载章节正文，并支持一键跳转阅读。

import type { BookOut, LocalHit } from '../../shared/types.js';
import { ApiError, listBooks, searchLocal } from '../api.js';
import { el, replace } from '../dom.js';
import type { View } from './view.js';

export interface FindViewDeps {
  onOpenChapter(bookId: string, chapterId: string): void;
}

function buildHighlightedSnippet(snippet: string, keyword: string): HTMLElement {
  const container = el('div', { class: 'card-desc' });
  const kw = keyword.trim();
  if (!kw) {
    container.textContent = snippet;
    return container;
  }

  const lowerSnippet = snippet.toLowerCase();
  const lowerKw = kw.toLowerCase();
  let cursor = 0;

  while (cursor < snippet.length) {
    const idx = lowerSnippet.indexOf(lowerKw, cursor);
    if (idx === -1) {
      container.append(document.createTextNode(snippet.slice(cursor)));
      break;
    }
    if (idx > cursor) {
      container.append(document.createTextNode(snippet.slice(cursor, idx)));
    }
    const matched = snippet.slice(idx, idx + kw.length);
    container.append(el('mark', { class: 'hl' }, matched));
    cursor = idx + kw.length;
  }
  return container;
}

export function createFindView(deps: FindViewDeps): View {
  const input = el('input', {
    class: 'input',
    type: 'search',
    placeholder: '在已下载的正文里搜索关键词…',
    autofocus: true,
  });
  const bookSelect = el(
    'select',
    { class: 'input select-sm' },
    el('option', { value: '' }, '全部书籍'),
  );
  const submit = el('button', { class: 'btn primary', type: 'submit' }, '检索');
  const status = el('div', { class: 'status' });
  const results = el('div', { class: 'results' });

  const form = el('form', { class: 'search-bar wide' }, input, bookSelect, submit);

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    void runFind();
  });

  async function loadBooksFilter(): Promise<void> {
    try {
      const books: BookOut[] = await listBooks(200);
      replace(
        bookSelect,
        el('option', { value: '' }, `全部书籍 (${books.length})`),
        ...books.map((b) => el('option', { value: b.id }, b.title)),
      );
    } catch {
      // 忽略书籍筛选加载异常
    }
  }

  async function runFind(): Promise<void> {
    const kw = input.value.trim();
    if (!kw) return;

    submit.disabled = true;
    replace(status, el('span', { class: 'muted' }, '检索中…'));
    replace(results);

    try {
      const bookId = bookSelect.value.trim() || undefined;
      const res = await searchLocal(kw, bookId, 50);
      if (res.items.length === 0) {
        replace(status, el('span', { class: 'muted' }, `未找到包含 “${kw}” 的正文`));
        return;
      }
      replace(status, el('span', { class: 'muted' }, `共命中 ${res.total} 处`));
      replace(results, ...res.items.map((hit) => renderHit(hit, kw)));
    } catch (error) {
      const msg = error instanceof ApiError ? `${error.message}（${error.code}）` : String(error);
      replace(status, el('span', { class: 'error' }, msg));
    } finally {
      submit.disabled = false;
    }
  }

  function renderHit(hit: LocalHit, keyword: string): HTMLElement {
    const readBtn = el(
      'button',
      {
        class: 'btn',
        type: 'button',
        onclick: () => deps.onOpenChapter(hit.book_id, hit.chapter_id),
      },
      '阅读本章',
    );

    return el(
      'article',
      { class: 'card' },
      el(
        'div',
        { class: 'card-main' },
        el('div', { class: 'card-title' }, `${hit.book_title} · #${hit.chapter_index} ${hit.chapter_title}`),
        buildHighlightedSnippet(hit.snippet, keyword),
      ),
      readBtn,
    );
  }

  const element = el(
    'section',
    { class: 'view' },
    el('h1', {}, '全文检索'),
    el('p', { class: 'hint' }, '纯本地 SQLite 检索已下载章节正文（字面匹配，不联网）。'),
    form,
    status,
    results,
  );

  void loadBooksFilter();

  return { element, dispose: () => {} };
}
