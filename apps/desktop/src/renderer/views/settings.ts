// SPDX-License-Identifier: GPL-3.0-only
//
// 设置与运维视图：运行时信息、下载/缓存/导出配置编辑与 HTTP 缓存清理。

import type { AppInfoOut, SettingsPatchInput } from '../../shared/types.js';
import { formatBytes } from '../../shared/types.js';
import { ApiError, clearHttpCache, getAppInfo, saveSettings } from '../api.js';
import { el, replace } from '../dom.js';
import type { View } from './view.js';

export interface SettingsViewDeps {
  onNotify(message: string, kind?: 'info' | 'error'): void;
}

export function createSettingsView(deps: SettingsViewDeps): View {
  const root = el('section', { class: 'view' });
  let disposed = false;

  function formatError(err: unknown): string {
    return err instanceof ApiError ? `${err.message}（${err.code}）` : String(err);
  }

  async function load(): Promise<void> {
    replace(root, el('h1', {}, '设置'), el('p', { class: 'hint' }, '正在加载运行时配置…'));
    try {
      const info = await getAppInfo();
      if (disposed) return;
      render(info);
    } catch (error) {
      if (disposed) return;
      replace(
        root,
        el('h1', {}, '设置'),
        el('p', { class: 'error' }, `加载设置失败：${formatError(error)}`),
      );
    }
  }

  function render(info: AppInfoOut): void {
    const s = info.settings;

    const concurrencyInput = el('input', {
      class: 'input',
      type: 'number',
      min: 1,
      max: 64,
      value: String(s.download.concurrency),
    });
    const perSourceInput = el('input', {
      class: 'input',
      type: 'number',
      min: 1,
      max: 32,
      value: String(s.download.per_source_concurrency),
    });
    const intervalInput = el('input', {
      class: 'input',
      type: 'number',
      min: 0,
      max: 60000,
      value: String(s.download.request_interval_ms),
    });
    const timeoutInput = el('input', {
      class: 'input',
      type: 'number',
      min: 100,
      max: 120000,
      value: String(s.download.timeout_ms),
    });
    const retryInput = el('input', {
      class: 'input',
      type: 'number',
      min: 0,
      max: 10,
      value: String(s.download.retry),
    });
    const proxyInput = el('input', {
      class: 'input',
      type: 'text',
      placeholder: '留空使用环境变量 HTTPS_PROXY / HTTP_PROXY',
      value: s.download.proxy ?? '',
    });

    const cacheEnabled = el('input', {
      type: 'checkbox',
      checked: s.cache.enabled,
    });
    const cacheMaxSizeInput = el('input', {
      class: 'input',
      type: 'text',
      value: s.cache.max_size,
    });

    const formatSelect = el(
      'select',
      { class: 'input' },
      el('option', { value: 'epub', selected: s.output.format === 'epub' }, 'EPUB'),
      el('option', { value: 'txt', selected: s.output.format === 'txt' }, 'TXT'),
      el('option', { value: 'markdown', selected: s.output.format === 'markdown' }, 'Markdown'),
    );
    const templateInput = el('input', {
      class: 'input',
      type: 'text',
      value: s.output.template,
    });

    const logLevelSelect = el(
      'select',
      { class: 'input' },
      el('option', { value: 'DEBUG', selected: s.logging.level === 'DEBUG' }, 'DEBUG'),
      el('option', { value: 'INFO', selected: s.logging.level === 'INFO' }, 'INFO'),
      el('option', { value: 'WARNING', selected: s.logging.level === 'WARNING' }, 'WARNING'),
      el('option', { value: 'ERROR', selected: s.logging.level === 'ERROR' }, 'ERROR'),
    );

    const saveStatus = el('div', { class: 'status' });
    const saveBtn = el('button', { class: 'btn primary', type: 'submit' }, '保存配置');

    const form = el(
      'form',
      { class: 'settings-grid' },
      field('全局并发 (1-64)', concurrencyInput),
      field('单书源并发 (1-32)', perSourceInput),
      field('请求间隔 (ms)', intervalInput),
      field('单请求超时 (ms)', timeoutInput),
      field('失败重试次数 (0-10)', retryInput),
      field('HTTP 代理地址', proxyInput),
      field('默认导出格式', formatSelect),
      field('导出文件名模板', templateInput),
      field('缓存容量上限', cacheMaxSizeInput),
      field('日志级别', logLevelSelect),
      el(
        'div',
        { class: 'field-full' },
        el('label', { class: 'check-label' }, cacheEnabled, '启用 SQLite HTTP 缓存'),
      ),
      el('div', { class: 'field-full toolbar' }, saveBtn, saveStatus),
    );

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      void handleSave();
    });

    async function handleSave(): Promise<void> {
      const patch: SettingsPatchInput = {
        concurrency: Number(concurrencyInput.value),
        perSourceConcurrency: Number(perSourceInput.value),
        requestIntervalMs: Number(intervalInput.value),
        timeoutMs: Number(timeoutInput.value),
        retry: Number(retryInput.value),
        proxy: proxyInput.value,
        cacheEnabled: cacheEnabled.checked,
        cacheMaxSize: cacheMaxSizeInput.value,
        outputFormat: formatSelect.value,
        outputTemplate: templateInput.value,
        loggingLevel: logLevelSelect.value,
      };
      saveBtn.disabled = true;
      replace(saveStatus, el('span', { class: 'muted' }, '正在保存…'));
      try {
        await saveSettings(patch);
        if (disposed) return;
        replace(
          saveStatus,
          el('span', { class: 'ok' }, '已写入 config.toml（部分网络/日志参数重启后生效）'),
        );
        deps.onNotify('设置已保存');
      } catch (error) {
        if (disposed) return;
        replace(saveStatus, el('span', { class: 'error' }, formatError(error)));
      } finally {
        saveBtn.disabled = false;
      }
    }

    const cacheStatsLine = el(
      'div',
      { class: 'card-meta' },
      info.cacheStats
        ? `当前缓存：${info.cacheStats.entries} 条，占用 ${formatBytes(info.cacheStats.sizeBytes)} / ${formatBytes(info.cacheStats.maxSizeBytes)}`
        : '当前连接外部独立服务，请用命令行 `mog cache stats` 管理缓存。',
    );

    const purgeBtn = el(
      'button',
      {
        class: 'btn',
        type: 'button',
        disabled: !info.inProcess,
        onclick: () => void handleClearCache(true),
      },
      '清理过期缓存',
    );
    const clearAllBtn = el(
      'button',
      {
        class: 'btn danger',
        type: 'button',
        disabled: !info.inProcess,
        onclick: () => void handleClearCache(false),
      },
      '清空全部缓存',
    );

    async function handleClearCache(expiredOnly: boolean): Promise<void> {
      purgeBtn.disabled = true;
      clearAllBtn.disabled = true;
      try {
        const res = await clearHttpCache(expiredOnly);
        if (disposed) return;
        cacheStatsLine.textContent = `当前缓存：${res.stats.entries} 条，占用 ${formatBytes(res.stats.sizeBytes)} / ${formatBytes(res.stats.maxSizeBytes)}`;
        deps.onNotify(
          `${expiredOnly ? '已清理过期缓存' : '已清空缓存'}（移除 ${res.removed} 条）`,
        );
      } catch (error) {
        if (disposed) return;
        deps.onNotify(`缓存清理失败：${formatError(error)}`, 'error');
      } finally {
        purgeBtn.disabled = !info.inProcess;
        clearAllBtn.disabled = !info.inProcess;
      }
    }

    const pathsCard = el(
      'div',
      { class: 'panel-box' },
      el('div', { class: 'card-title' }, `MoGrab Desktop v${info.version}`),
      pathRow('运行模式', info.inProcess ? '进程内嵌入 Axum API' : '复用外部本地服务 (127.0.0.1:48721)'),
      pathRow('数据目录', info.dataDir),
      pathRow('配置文件', info.configFile),
      pathRow('数据库', info.database),
      pathRow('导出目录', info.exportsDir),
      pathRow('书源目录', info.sourcesDir),
      pathRow('日志目录', info.logsDir),
    );

    const cacheCard = el(
      'div',
      { class: 'panel-box' },
      el('div', { class: 'card-title' }, 'HTTP 缓存管理'),
      cacheStatsLine,
      el('div', { class: 'toolbar' }, purgeBtn, clearAllBtn),
    );

    replace(
      root,
      el('h1', {}, '设置与运行环境'),
      el('p', { class: 'hint' }, '修改配置将写入 data/config.toml；敏感网络参数保留在本地。'),
      pathsCard,
      el('h2', { class: 'section-title' }, '核心配置'),
      form,
      cacheCard,
    );
  }

  function field(label: string, control: HTMLElement): HTMLElement {
    return el('label', { class: 'field' }, el('span', { class: 'field-label' }, label), control);
  }

  function pathRow(label: string, value: string): HTMLElement {
    return el(
      'div',
      { class: 'path-row' },
      el('span', { class: 'path-label' }, label),
      el('span', { class: 'path-value mono' }, value),
    );
  }

  void load();

  return {
    element: root,
    dispose: () => {
      disposed = true;
    },
  };
}
