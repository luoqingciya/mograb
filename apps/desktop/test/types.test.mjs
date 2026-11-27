// SPDX-License-Identifier: GPL-3.0-only
//
// 共享类型与格式化辅助函数的单元测试。

import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  BOOK_STATUS_LABEL,
  EXPORT_STATUS_LABEL,
  SOURCE_HEALTH_LABEL,
  TASK_STATUS_LABEL,
  formatBytes,
  formatWordCount,
  isTerminal,
} from '../dist/shared/types.js';

test('isTerminal 识别终态任务状态', () => {
  assert.equal(isTerminal('success'), true);
  assert.equal(isTerminal('failed'), true);
  assert.equal(isTerminal('cancelled'), true);
  assert.equal(isTerminal('pending'), false);
  assert.equal(isTerminal('running'), false);
  assert.equal(isTerminal('paused'), false);
  assert.equal(isTerminal('retrying'), false);
});

test('formatBytes 格式化容量单位', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(-5), '0 B');
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(1536), '1.5 KB');
  assert.equal(formatBytes(5 * 1024 * 1024), '5.0 MB');
});

test('formatWordCount 格式化中文字数', () => {
  assert.equal(formatWordCount(0), '0 字');
  assert.equal(formatWordCount(3456), '3456 字');
  assert.equal(formatWordCount(4512000), '451.2 万字');
});

test('中文状态标签映射完整', () => {
  assert.equal(TASK_STATUS_LABEL.running, '进行中');
  assert.equal(SOURCE_HEALTH_LABEL.healthy, '正常');
  assert.equal(BOOK_STATUS_LABEL.completed, '已完结');
  assert.equal(EXPORT_STATUS_LABEL.success, '已完成');
});
