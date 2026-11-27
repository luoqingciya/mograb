// SPDX-License-Identifier: GPL-3.0-only
//
// 主题切换逻辑与 WCAG 2.1 对比度自动化校验，避免低对比度回退。

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  THEME_MODE_LABEL,
  nextThemeMode,
  normalizeThemeMode,
  resolveTheme,
} from '../dist/shared/theme.js';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CSS = readFileSync(resolve(ROOT, 'src/renderer/styles.css'), 'utf8');

function extractVars(selectorPattern) {
  const match = CSS.match(selectorPattern);
  assert.ok(match, `未找到样式块: ${selectorPattern}`);
  const vars = {};
  for (const [, name, value] of match[1].matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    vars[name] = value.toLowerCase();
  }
  return vars;
}

function luminance(hex) {
  const clean = hex.replace('#', '');
  const channels = [0, 2, 4].map((i) => {
    const srgb = parseInt(clean.slice(i, i + 2), 16) / 255;
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(fg, bg) {
  const l1 = luminance(fg);
  const l2 = luminance(bg);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

function assertContrast(themeName, label, fg, bg, minRatio) {
  assert.ok(fg, `${themeName} 缺少前景色 (${label})`);
  assert.ok(bg, `${themeName} 缺少背景色 (${label})`);
  const ratio = contrastRatio(fg, bg);
  assert.ok(
    ratio >= minRatio,
    `${themeName} 对比度不足 [${label}]: ${fg} on ${bg} = ${ratio.toFixed(2)}:1 (要求 >= ${minRatio}:1)`,
  );
}

function verifyThemePalette(themeName, vars) {
  // 主标题与正文 >= 7.0 (AAA)
  assertContrast(themeName, 'text-strong on bg', vars['--text-strong'], vars['--bg'], 7.0);
  assertContrast(themeName, 'text-strong on panel', vars['--text-strong'], vars['--panel'], 7.0);
  assertContrast(themeName, 'text on bg', vars['--text'], vars['--bg'], 7.0);
  assertContrast(themeName, 'text on panel', vars['--text'], vars['--panel'], 7.0);
  assertContrast(themeName, 'text on panel-hi', vars['--text'], vars['--panel-hi'], 7.0);
  assertContrast(themeName, 'text on input-bg', vars['--text'], vars['--input-bg'], 7.0);
  assertContrast(themeName, 'reader-text on reader-bg', vars['--reader-text'], vars['--reader-bg'], 7.0);

  // 次级、弱化、占位符、激活态、语义状态 >= 4.5 (AA)
  assertContrast(themeName, 'text-secondary on panel', vars['--text-secondary'], vars['--panel'], 4.5);
  assertContrast(themeName, 'muted on bg', vars['--muted'], vars['--bg'], 4.5);
  assertContrast(themeName, 'muted on panel', vars['--muted'], vars['--panel'], 4.5);
  assertContrast(themeName, 'muted on panel-hi', vars['--muted'], vars['--panel-hi'], 4.5);
  assertContrast(themeName, 'placeholder on input-bg', vars['--placeholder'], vars['--input-bg'], 4.5);
  assertContrast(themeName, 'accent-text on bg', vars['--accent-text'], vars['--bg'], 4.5);
  assertContrast(themeName, 'accent-text on panel', vars['--accent-text'], vars['--panel'], 4.5);
  assertContrast(themeName, 'accent-text on accent-soft', vars['--accent-text'], vars['--accent-soft'], 4.5);
  assertContrast(themeName, 'btn-primary-text on accent-bg', vars['--btn-primary-text'], vars['--accent-bg'], 4.5);
  assertContrast(themeName, 'btn-primary-text on accent-bg-hover', vars['--btn-primary-text'], vars['--accent-bg-hover'], 4.5);
  assertContrast(themeName, 'ok on ok-soft', vars['--ok'], vars['--ok-soft'], 4.5);
  assertContrast(themeName, 'warn on warn-soft', vars['--warn'], vars['--warn-soft'], 4.5);
  assertContrast(themeName, 'bad on bg', vars['--bad'], vars['--bg'], 4.5);
  assertContrast(themeName, 'bad on panel', vars['--bad'], vars['--panel'], 4.5);
  assertContrast(themeName, 'bad on bad-soft', vars['--bad'], vars['--bad-soft'], 4.5);
  assertContrast(themeName, 'text on notice-info-bg', vars['--text'], vars['--notice-info-bg'], 4.5);
  assertContrast(themeName, 'disabled-text on disabled-bg', vars['--disabled-text'], vars['--disabled-bg'], 4.5);
  assertContrast(themeName, 'hl-text on hl-bg', vars['--hl-text'], vars['--hl-bg'], 4.5);

  // 交互控件边框 >= 3.0 (WCAG 1.4.11)
  assertContrast(themeName, 'border-strong vs panel', vars['--border-strong'], vars['--panel'], 3.0);
  assertContrast(themeName, 'border-strong vs input-bg', vars['--border-strong'], vars['--input-bg'], 3.0);
}

test('styles.css 声明 color-scheme、下拉 option 与 placeholder 样式', () => {
  assert.match(CSS, /:root\s*\{[^}]*color-scheme:\s*dark\s*;/s);
  assert.match(CSS, /:root\[data-theme='light'\]\s*\{[^}]*color-scheme:\s*light\s*;/s);
  assert.match(CSS, /select\.input option\s*\{/);
  assert.match(CSS, /\.input::placeholder\s*\{/);
  assert.match(CSS, /:focus-visible\s*\{/);
});

test('Dark 主题色板满足 WCAG AA/AAA 对比度要求', () => {
  const darkVars = extractVars(/:root\s*\{([^}]*)\}/s);
  verifyThemePalette('Dark', darkVars);
});

test('Light 主题色板满足 WCAG AA/AAA 对比度要求', () => {
  const lightVars = extractVars(/:root\[data-theme='light'\]\s*\{([^}]*)\}/s);
  verifyThemePalette('Light', lightVars);
});

test('theme.ts 主题模式归一化、解析与切换循环正确', () => {
  assert.equal(normalizeThemeMode('dark'), 'dark');
  assert.equal(normalizeThemeMode('light'), 'light');
  assert.equal(normalizeThemeMode('system'), 'system');
  assert.equal(normalizeThemeMode('unknown'), 'dark');
  assert.equal(normalizeThemeMode(null), 'dark');

  assert.equal(resolveTheme('dark', true), 'dark');
  assert.equal(resolveTheme('light', false), 'light');
  assert.equal(resolveTheme('system', true), 'light');
  assert.equal(resolveTheme('system', false), 'dark');

  assert.equal(nextThemeMode('dark'), 'light');
  assert.equal(nextThemeMode('light'), 'system');
  assert.equal(nextThemeMode('system'), 'dark');

  assert.equal(THEME_MODE_LABEL.dark, '深色');
  assert.equal(THEME_MODE_LABEL.light, '浅色');
  assert.equal(THEME_MODE_LABEL.system, '跟随系统');
});
