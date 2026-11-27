// SPDX-License-Identifier: GPL-3.0-only
//
// 书架与内置阅读器视图：书籍列表、详情、增量更新检查、导出作业、章节阅读。

import type {
  BookOut,
  ChapterDetailOut,
  ChapterSummaryOut,
  ExportFormat,
} from '../../shared/types.js';
import {
  BOOK_STATUS_LABEL,
  formatWordCount,
} from '../../shared/types.js';
import {
  ApiError,
  createExport,
  createTask,
  getBook,
  getChapter,
  listBooks,
  listChapters,
  updateBook,
} from '../api.js';
import { el, replace } from '../dom.js';
import type { View } from './view.js';

export interface ShelfInitialTarget {
  bookId: string;
  chapterId?: string;
}

export interface ShelfViewDeps {
  initial?: ShelfInitialTarget;
  onNotify(message: string, kind?: 'info' | 'error'): void;
  onGoToTasks(): void;
}

export function createShelfView(deps: ShelfViewDeps): View {
  const root = el('section', { class: 'view' });
  let disposed = false;
  let allBooks: BookOut[] = [];
  let selectedBook: BookOut | null = null;
  let chapters: ChapterSummaryOut[] = [];
  let activeChapter: ChapterDetailOut | null = null;
  let readerFontSize = 16;
  let filterKeyword = '';
  let chapterFilter = '';

  function formatError(err: unknown): string {
    return err instanceof ApiError ? `${err.message}（${err.code}）` : String(err);
  }

  async function loadShelf(): Promise<void> {
    replace(
      root,
      el('h1', {}, '书架'),
      el('p', { class: 'hint' }, '正在加载本地藏书…'),
    );
    try {
      allBooks = await listBooks(200);
      if (disposed) return;
      renderShelf();
    } catch (error) {
      if (disposed) return;
      replace(
        root,
        el('h1', {}, '书架'),
        el('p', { class: 'error' }, `加载书架失败：${formatError(error)}`),
      );
    }
  }

  async function openBook(bookId: string, chapterId?: string): Promise<void> {
    replace(
      root,
      el('h1', {}, '书籍详情'),
      el('p', { class: 'hint' }, '正在加载目录…'),
    );
    try {
      const [book, toc] = await Promise.all([getBook(bookId), listChapters(bookId)]);
      if (disposed) return;
      selectedBook = book;
      chapters = toc;
      activeChapter = null;
      chapterFilter = '';

      if (chapterId) {
        await loadChapter(bookId, chapterId);
      } else {
        renderBookDetail();
      }
    } catch (error) {
      if (disposed) return;
      deps.onNotify(`打开书籍失败：${formatError(error)}`, 'error');
      await loadShelf();
    }
  }

  async function loadChapter(bookId: string, chapterId: string): Promise<void> {
    try {
      const detail = await getChapter(bookId, chapterId);
      if (disposed) return;
      activeChapter = detail;
      renderReader();
    } catch (error) {
      if (disposed) return;
      deps.onNotify(`读取章节失败：${formatError(error)}`, 'error');
    }
  }

  function renderShelf(): void {
    const searchInput = el('input', {
      class: 'input',
      type: 'search',
      placeholder: '按书名或作者筛选…',
      value: filterKeyword,
    });
    const refreshBtn = el(
      'button',
      {
        class: 'btn',
        type: 'button',
        onclick: () => void loadShelf(),
      },
      '刷新',
    );
    const listContainer = el('div', { class: 'results' });
    const countSpan = el('span', { class: 'muted' });

    function paintList(): void {
      const kw = filterKeyword.trim().toLowerCase();
      const filtered = kw
        ? allBooks.filter(
            (b) =>
              b.title.toLowerCase().includes(kw) ||
              (b.author ?? '').toLowerCase().includes(kw),
          )
        : allBooks;

      replace(countSpan, `共 ${filtered.length} 本${kw ? `（总计 ${allBooks.length} 本）` : ''}`);

      if (filtered.length === 0) {
        replace(
          listContainer,
          el(
            'p',
            { class: 'hint' },
            allBooks.length === 0 ? '书架还是空的，先去「搜索」页下载一本书吧。' : '没有匹配的书籍。',
          ),
        );
        return;
      }

      replace(
        listContainer,
        ...filtered.map((book) => {
          const badge = BOOK_STATUS_LABEL[book.status] ?? book.status;
          const openBtn = el(
            'button',
            {
              class: 'btn primary',
              type: 'button',
              onclick: () => void openBook(book.id),
            },
            '阅读 / 管理',
          );
          const metaParts = [
            book.author ?? '佚名',
            book.source_id,
            `${book.chapter_count} 章`,
            formatWordCount(book.word_count),
          ];
          return el(
            'article',
            { class: 'card' },
            el(
              'div',
              { class: 'card-main' },
              el(
                'div',
                { class: 'card-title-row' },
                el('span', { class: 'card-title' }, book.title),
                el('span', { class: 'badge' }, badge),
              ),
              el('div', { class: 'card-meta' }, metaParts.join(' · ')),
              book.latest_chapter
                ? el('div', { class: 'card-sub' }, `最新：${book.latest_chapter}`)
                : null,
            ),
            openBtn,
          );
        }),
      );
    }

    searchInput.addEventListener('input', () => {
      filterKeyword = searchInput.value;
      paintList();
    });

    paintList();

    replace(
      root,
      el('h1', {}, '书架'),
      el('p', { class: 'hint' }, '管理本地已入库书籍、增量检查更新、导出电子书及阅读章节。'),
      el('div', { class: 'toolbar' }, searchInput, refreshBtn),
      el('div', { class: 'status' }, countSpan),
      listContainer,
    );
  }

  function renderBookDetail(): void {
    const book = selectedBook;
    if (!book) return;

    const backBtn = el(
      'button',
      {
        class: 'btn',
        type: 'button',
        onclick: () => {
          selectedBook = null;
          void loadShelf();
        },
      },
      '← 返回书架',
    );

    const diffLine = el('div', { class: 'status' });

    const checkUpdateBtn = el(
      'button',
      {
        class: 'btn',
        type: 'button',
        onclick: () => void handleCheckUpdate(),
      },
      '检查更新',
    );

    const formatSelect = el(
      'select',
      { class: 'input select-sm' },
      el('option', { value: 'epub' }, 'EPUB'),
      el('option', { value: 'txt' }, 'TXT'),
      el('option', { value: 'markdown' }, 'Markdown'),
    );
    const exportBtn = el(
      'button',
      {
        class: 'btn primary',
        type: 'button',
        onclick: () => void handleExport(),
      },
      '导出',
    );

    async function handleCheckUpdate(): Promise<void> {
      if (!book) return;
      checkUpdateBtn.disabled = true;
      replace(diffLine, el('span', { class: 'muted' }, '正在抓取远端目录比对…'));
      try {
        const res = await updateBook(book.id, true);
        if (disposed) return;
        if (res.to_download === 0) {
          replace(
            diffLine,
            el('span', { class: 'ok' }, `已是最新（共 ${res.total} 章，未新增或变更章节）`),
          );
        } else {
          const runBtn = el(
            'button',
            {
              class: 'btn primary btn-sm',
              type: 'button',
              onclick: () => void handleStartUpdate(),
            },
            `立即下载 ${res.to_download} 章`,
          );
          replace(
            diffLine,
            el(
              'span',
              { class: 'warn' },
              `发现 ${res.to_download} 章需更新（远端 ${res.total} 章，跳过 ${res.skipped} 章）`,
            ),
            runBtn,
          );
        }
      } catch (error) {
        if (disposed) return;
        replace(diffLine, el('span', { class: 'error' }, `检查更新失败：${formatError(error)}`));
      } finally {
        checkUpdateBtn.disabled = false;
      }
    }

    async function handleStartUpdate(): Promise<void> {
      if (!book) return;
      try {
        await createTask({ type: 'update_book', bookId: book.id });
        deps.onNotify(`已加入更新队列：《${book.title}》`);
        deps.onGoToTasks();
      } catch (error) {
        deps.onNotify(`创建更新任务失败：${formatError(error)}`, 'error');
      }
    }

    async function handleExport(): Promise<void> {
      if (!book) return;
      exportBtn.disabled = true;
      try {
        const fmt = (formatSelect.value || 'epub') as ExportFormat;
        await createExport({ book_id: book.id, format: fmt });
        deps.onNotify(`已提交导出作业：《${book.title}》(${fmt.toUpperCase()})`);
        deps.onGoToTasks();
      } catch (error) {
        deps.onNotify(`创建导出失败：${formatError(error)}`, 'error');
      } finally {
        exportBtn.disabled = false;
      }
    }

    const filterInput = el('input', {
      class: 'input',
      type: 'search',
      placeholder: '过滤章节标题或序号…',
      value: chapterFilter,
    });
    const tocList = el('div', { class: 'toc-list' });

    function paintToc(): void {
      if (!book) return;
      const bookId = book.id;
      const kw = chapterFilter.trim().toLowerCase();
      const filtered = kw
        ? chapters.filter(
            (ch) =>
              ch.title.toLowerCase().includes(kw) || String(ch.index).includes(kw),
          )
        : chapters;

      if (filtered.length === 0) {
        replace(tocList, el('p', { class: 'hint' }, '暂无匹配章节。'));
        return;
      }

      replace(
        tocList,
        ...filtered.map((ch) =>
          el(
            'button',
            {
              class: `toc-item${ch.has_content ? '' : ' empty'}`,
              type: 'button',
              disabled: !ch.has_content,
              onclick: () => void loadChapter(bookId, ch.id),
            },
            el('span', { class: 'toc-title' }, `#${ch.index} ${ch.title}`),
            el(
              'span',
              { class: 'toc-meta' },
              ch.has_content ? formatWordCount(ch.word_count) : '未下载',
            ),
          ),
        ),
      );
    }

    filterInput.addEventListener('input', () => {
      chapterFilter = filterInput.value;
      paintToc();
    });
    paintToc();

    const meta = [
      `作者：${book.author ?? '佚名'}`,
      `书源：${book.source_id}`,
      `状态：${BOOK_STATUS_LABEL[book.status] ?? book.status}`,
      `${book.chapter_count} 章`,
      formatWordCount(book.word_count),
    ].join(' · ');

    replace(
      root,
      el(
        'div',
        { class: 'detail-header' },
        backBtn,
        el('div', { class: 'detail-actions' }, checkUpdateBtn, formatSelect, exportBtn),
      ),
      el('h1', {}, book.title),
      el('p', { class: 'hint' }, meta),
      book.intro ? el('p', { class: 'book-intro' }, book.intro) : null,
      diffLine,
      el('div', { class: 'toolbar' }, filterInput),
      tocList,
    );
  }

  function renderReader(): void {
    const book = selectedBook;
    const ch = activeChapter;
    if (!book || !ch) return;

    const currentIdx = chapters.findIndex((c) => c.id === ch.id);
    const prev = currentIdx > 0 ? chapters[currentIdx - 1] : undefined;
    const next =
      currentIdx >= 0 && currentIdx + 1 < chapters.length
        ? chapters[currentIdx + 1]
        : undefined;

    const bodyEl = el('article', {
      class: 'reader-body',
      style: `font-size: ${readerFontSize}px`,
    });

    const raw = ch.content?.trim() ?? '';
    if (!raw) {
      replace(bodyEl, el('p', { class: 'hint' }, '本章暂无本地正文。'));
    } else {
      const paragraphs = raw.split(/\n+/).filter((p) => p.trim() !== '');
      replace(
        bodyEl,
        ...paragraphs.map((p) => el('p', { class: 'reader-para' }, p)),
      );
    }

    const navBar = () =>
      el(
        'div',
        { class: 'reader-nav' },
        el(
          'button',
          {
            class: 'btn',
            type: 'button',
            disabled: prev === undefined || !prev.has_content,
            onclick: () => {
              if (prev) void loadChapter(book.id, prev.id);
            },
          },
          '← 上一章',
        ),
        el(
          'button',
          {
            class: 'btn',
            type: 'button',
            onclick: () => {
              activeChapter = null;
              renderBookDetail();
            },
          },
          '目录',
        ),
        el(
          'button',
          {
            class: 'btn primary',
            type: 'button',
            disabled: next === undefined || !next.has_content,
            onclick: () => {
              if (next) void loadChapter(book.id, next.id);
            },
          },
          '下一章 →',
        ),
      );

    const fontControls = el(
      'div',
      { class: 'detail-actions' },
      el(
        'button',
        {
          class: 'btn btn-sm',
          type: 'button',
          onclick: () => {
            readerFontSize = Math.max(13, readerFontSize - 1);
            bodyEl.style.fontSize = `${readerFontSize}px`;
          },
        },
        'A-',
      ),
      el(
        'button',
        {
          class: 'btn btn-sm',
          type: 'button',
          onclick: () => {
            readerFontSize = Math.min(24, readerFontSize + 1);
            bodyEl.style.fontSize = `${readerFontSize}px`;
          },
        },
        'A+',
      ),
    );

    replace(
      root,
      el('div', { class: 'detail-header' }, navBar(), fontControls),
      el('h1', { class: 'reader-title' }, `#${ch.index} ${ch.title}`),
      el('p', { class: 'hint' }, `${book.title} · ${formatWordCount(ch.word_count)}`),
      bodyEl,
      navBar(),
    );
    root.scrollTop = 0;
  }

  if (deps.initial) {
    void openBook(deps.initial.bookId, deps.initial.chapterId);
  } else {
    void loadShelf();
  }

  return {
    element: root,
    dispose: () => {
      disposed = true;
    },
  };
}
