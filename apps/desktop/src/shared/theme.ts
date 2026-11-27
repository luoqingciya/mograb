// SPDX-License-Identifier: GPL-3.0-only
//
// 主题模式管理（深色 / 浅色 / 跟随系统）纯函数工具。

export type ThemeMode = 'dark' | 'light' | 'system';

export type ResolvedTheme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'mograb.theme';

export const THEME_MODE_LABEL: Record<ThemeMode, string> = {
  dark: '深色',
  light: '浅色',
  system: '跟随系统',
};

export function normalizeThemeMode(raw: string | null | undefined): ThemeMode {
  if (raw === 'dark' || raw === 'light' || raw === 'system') {
    return raw;
  }
  return 'dark';
}

export function resolveTheme(mode: ThemeMode, systemPrefersLight: boolean): ResolvedTheme {
  if (mode === 'system') {
    return systemPrefersLight ? 'light' : 'dark';
  }
  return mode;
}

export function nextThemeMode(mode: ThemeMode): ThemeMode {
  if (mode === 'dark') return 'light';
  if (mode === 'light') return 'system';
  return 'dark';
}
