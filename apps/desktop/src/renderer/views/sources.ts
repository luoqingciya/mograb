// SPDX-License-Identifier: GPL-3.0-only
//
// 书源管理视图：列表、安装（YAML/文件路径）、启用/禁用、体检、详情与卸载。

import type { SourceDetail, SourceOut } from '../../shared/types.js';
import { SOURCE_HEALTH_LABEL } from '../../shared/types.js';
import {
  ApiError,
  disableSource,
  doctorSource,
  enableSource,
  getSource,
  installSource,
  listSources,
  removeSource,
  rescanSources,
} from '../api.js';
import { el, replace } from '../dom.js';
import type { View } from './view.js';

export interface SourcesViewDeps {
  onNotify(message: string, kind?: 'info' | 'error'): void;
}

export function createSourcesView(deps: SourcesViewDeps): View {
  const status = el('div', { class: 'status' });
  const listEl = el('div', { class: 'results' });
  const installFeedback = el('div', { class: 'status' });
  const detailsMap = new Map<string, SourceDetail>();
  let sources: SourceOut[] = [];
  let confirmDeleteId: string | null = null;
  let disposed = false;

  const modeSelect = el(
    'select',
    { class: 'input select-sm' },
    el('option', { value: 'yaml' }, '粘贴 YAML'),
    el('option', { value: 'file' }, '本地文件路径'),
  );
  const forceCheck = el('input', { type: 'checkbox' });
  const yamlTextarea = el('textarea', {
    class: 'input textarea',
    rows: 7,
    placeholder: '粘贴完整 source.yaml 内容…',
  });
  const pathInput = el('input', {
    class: 'input',
    type: 'text',
    placeholder: '填写本机 source.yaml / source.json 路径…',
  });
  const installInputWrap = el('div', {}, yamlTextarea);
  const installSubmit = el('button', { class: 'btn primary', type: 'submit' }, '校验并安装');

  modeSelect.addEventListener('change', () => {
    if (modeSelect.value === 'file') {
      replace(installInputWrap, pathInput);
    } else {
      replace(installInputWrap, yamlTextarea);
    }
  });

  const installForm = el(
    'form',
    { class: 'stack' },
    el(
      'div',
      { class: 'toolbar' },
      modeSelect,
      el('label', { class: 'check-label' }, forceCheck, '忽略非致命校验/覆盖已存在'),
      installSubmit,
    ),
    installInputWrap,
    installFeedback,
  );

  installForm.addEventListener('submit', (event) => {
    event.preventDefault();
    void handleInstall();
  });

  const installDrawer = el(
    'details',
    { class: 'drawer' },
    el('summary', { class: 'drawer-summary' }, '+ 安装 / 更新书源'),
    installForm,
  );

  function formatError(error: unknown): string {
    if (error instanceof ApiError) {
      const errs = Array.isArray(error.details['errors'])
        ? (error.details['errors'] as string[]).join('；')
        : '';
      return errs ? `${error.message}：${errs}` : `${error.message}（${error.code}）`;
    }
    return String(error);
  }

  async function refresh(): Promise<void> {
    try {
      sources = await listSources();
      if (disposed) return;
      render();
    } catch (error) {
      if (disposed) return;
      replace(status, el('span', { class: 'error' }, formatError(error)));
    }
  }

  async function handleInstall(): Promise<void> {
    const mode = modeSelect.value === 'file' ? 'file' : 'yaml';
    const content = mode === 'yaml' ? yamlTextarea.value : undefined;
    const path = mode === 'file' ? pathInput.value.trim() : undefined;
    if ((mode === 'yaml' && !content?.trim()) || (mode === 'file' && !path)) {
      replace(installFeedback, el('span', { class: 'warn' }, '请填写书源内容或路径'));
      return;
    }

    installSubmit.disabled = true;
    replace(installFeedback, el('span', { class: 'muted' }, '正在校验并安装…'));
    try {
      const res = await installSource({
        mode,
        content: content ?? null,
        path: path ?? null,
        force: forceCheck.checked,
      });
      if (disposed) return;
      const warnMsg = res.warnings.length > 0 ? `（警告 ${res.warnings.length} 条）` : '';
      replace(
        installFeedback,
        el('span', { class: 'ok' }, `已安装 ${res.id} v${res.version}${warnMsg}`),
      );
      deps.onNotify(`书源已安装：${res.id} v${res.version}`);
      if (mode === 'yaml') yamlTextarea.value = '';
      else pathInput.value = '';
      await refresh();
    } catch (error) {
      if (disposed) return;
      replace(installFeedback, el('span', { class: 'error' }, formatError(error)));
    } finally {
      installSubmit.disabled = false;
    }
  }

  async function handleRescan(): Promise<void> {
    try {
      sources = await rescanSources();
      if (disposed) return;
      detailsMap.clear();
      render();
      deps.onNotify(`已重新扫描本地书源，共 ${sources.length} 个`);
    } catch (error) {
      deps.onNotify(`扫描失败：${formatError(error)}`, 'error');
    }
  }

  async function handleToggle(src: SourceOut): Promise<void> {
    try {
      const updated = src.enabled
        ? await disableSource(src.id)
        : await enableSource(src.id);
      if (disposed) return;
      sources = sources.map((s) => (s.id === updated.id ? updated : s));
      render();
      deps.onNotify(`已${updated.enabled ? '启用' : '禁用'}书源：${updated.name}`);
    } catch (error) {
      deps.onNotify(`操作失败：${formatError(error)}`, 'error');
    }
  }

  async function handleDoctor(src: SourceOut): Promise<void> {
    try {
      deps.onNotify(`正在体检书源：${src.name}…`);
      const updated = await doctorSource(src.id, true);
      if (disposed) return;
      sources = sources.map((s) => (s.id === updated.id ? updated : s));
      render();
      deps.onNotify(
        `体检完成：${updated.name} -> ${SOURCE_HEALTH_LABEL[updated.health] ?? updated.health}`,
      );
    } catch (error) {
      deps.onNotify(`体检失败：${formatError(error)}`, 'error');
    }
  }

  async function handleToggleDetail(srcId: string): Promise<void> {
    if (detailsMap.has(srcId)) {
      detailsMap.delete(srcId);
      render();
      return;
    }
    try {
      const detail = await getSource(srcId);
      if (disposed) return;
      detailsMap.set(srcId, detail);
      render();
    } catch (error) {
      deps.onNotify(`读取详情失败：${formatError(error)}`, 'error');
    }
  }

  async function handleRemove(srcId: string): Promise<void> {
    if (confirmDeleteId !== srcId) {
      confirmDeleteId = srcId;
      render();
      return;
    }
    try {
      await removeSource(srcId);
      if (disposed) return;
      confirmDeleteId = null;
      detailsMap.delete(srcId);
      sources = sources.filter((s) => s.id !== srcId);
      render();
      deps.onNotify(`已卸载书源：${srcId}`);
    } catch (error) {
      deps.onNotify(`卸载失败：${formatError(error)}`, 'error');
    }
  }

  function render(): void {
    const enabledCount = sources.filter((s) => s.enabled).length;
    replace(
      status,
      el('span', { class: 'muted' }, `共 ${sources.length} 个书源，已启用 ${enabledCount} 个`),
    );

    if (sources.length === 0) {
      replace(
        listEl,
        el('p', { class: 'hint' }, '还没有安装任何书源。点击上方「+ 安装 / 更新书源」添加。'),
      );
      return;
    }

    replace(
      listEl,
      ...sources.map((src) => {
        const healthLabel = SOURCE_HEALTH_LABEL[src.health] ?? src.health;
        const healthClass =
          src.health === 'healthy'
            ? 'ok'
            : src.health === 'broken' || src.health === 'unsupported'
              ? 'bad'
              : src.health === 'degraded'
                ? 'warn'
                : '';

        const detail = detailsMap.get(src.id);
        const isConfirming = confirmDeleteId === src.id;

        const actions = el(
          'div',
          { class: 'card-actions' },
          el(
            'button',
            {
              class: `btn btn-sm${src.enabled ? '' : ' primary'}`,
              type: 'button',
              onclick: () => void handleToggle(src),
            },
            src.enabled ? '禁用' : '启用',
          ),
          el(
            'button',
            {
              class: 'btn btn-sm',
              type: 'button',
              onclick: () => void handleDoctor(src),
            },
            '体检',
          ),
          el(
            'button',
            {
              class: 'btn btn-sm',
              type: 'button',
              onclick: () => void handleToggleDetail(src.id),
            },
            detail ? '收起' : '详情',
          ),
          el(
            'button',
            {
              class: 'btn btn-sm danger',
              type: 'button',
              onclick: () => void handleRemove(src.id),
            },
            isConfirming ? '确认卸载?' : '卸载',
          ),
        );

        const detailBox = detail
          ? el(
              'div',
              { class: 'detail-box' },
              el(
                'div',
                { class: 'card-meta' },
                `网络白名单：${(detail.permissions.network ?? []).join(', ') || '未声明'}`,
              ),
              el('div', { class: 'card-sub mono' }, `文件：${detail.path}`),
            )
          : null;

        return el(
          'article',
          { class: 'card card-col' },
          el(
            'div',
            { class: 'card-row' },
            el(
              'div',
              { class: 'card-main' },
              el(
                'div',
                { class: 'card-title-row' },
                el('span', { class: 'card-title' }, `${src.name} (${src.id})`),
                el('span', { class: 'badge' }, `v${src.version}`),
                el('span', { class: `badge ${healthClass}` }, healthLabel),
                el('span', { class: 'badge' }, src.enabled ? '已启用' : '已禁用'),
              ),
              el(
                'div',
                { class: 'card-meta' },
                `能力：${src.capabilities.join(', ') || '-'}${src.homepage ? ` · ${src.homepage}` : ''}`,
              ),
              src.description ? el('div', { class: 'card-desc' }, src.description) : null,
            ),
            actions,
          ),
          detailBox,
        );
      }),
    );
  }

  const rescanBtn = el(
    'button',
    {
      class: 'btn',
      type: 'button',
      onclick: () => void handleRescan(),
    },
    '重新扫描 sources/',
  );

  const element = el(
    'section',
    { class: 'view' },
    el(
      'div',
      { class: 'detail-header' },
      el('div', {}, el('h1', {}, '书源管理'), el('p', { class: 'hint' }, '安装、校验、启用/禁用、在线体检或卸载书源配置。')),
      rescanBtn,
    ),
    installDrawer,
    status,
    listEl,
  );

  void refresh();

  return {
    element,
    dispose: () => {
      disposed = true;
    },
  };
}
