// SPDX-License-Identifier: GPL-3.0-only
//
// SSE 解析器的测试。
//
// 直接跑编译产物（dist/renderer/sse.js），测的就是真正发出去的那份代码。
// 用 node:test，不引第三方测试框架 —— 这个模块只用标准 API，没必要为它
// 拉一个依赖进来。
//
//   node --test test/

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { parseEventBlock, SseDecoder } from '../dist/renderer/sse.js';

test('解析基本事件块', () => {
  const message = parseEventBlock('event: task\ndata: {"a":1}');
  assert.deepEqual(message, { event: 'task', data: '{"a":1}' });
});

test('event 缺省是 message', () => {
  assert.deepEqual(parseEventBlock('data: hello'), { event: 'message', data: 'hello' });
});

test('冒号后的一个空格是分隔符，不算内容', () => {
  assert.equal(parseEventBlock('data:  x')?.data, ' x');
});

test('多行 data 用换行拼接', () => {
  assert.equal(parseEventBlock('data: 第一行\ndata: 第二行')?.data, '第一行\n第二行');
});

test('纯注释块（心跳）返回 null', () => {
  assert.equal(parseEventBlock(': heartbeat'), null);
});

test('没有 data 的块返回 null', () => {
  assert.equal(parseEventBlock('event: task'), null);
});

test('CRLF 行尾', () => {
  assert.deepEqual(parseEventBlock('event: task\r\ndata: {}'), { event: 'task', data: '{}' });
});

test('分片落在事件边界上', () => {
  const decoder = new SseDecoder();
  assert.deepEqual(decoder.push('event: task\ndata: {"n":1}\n\n'), [
    { event: 'task', data: '{"n":1}' },
  ]);
});

test('分片切在块中间 —— 半块要留住', () => {
  const decoder = new SseDecoder();
  assert.deepEqual(decoder.push('event: ta'), []);
  assert.deepEqual(decoder.push('sk\ndata: {"n"'), []);
  assert.deepEqual(decoder.push(':1}\n\n'), [{ event: 'task', data: '{"n":1}' }]);
});

test('CRLF 被切在 \\r 和 \\n 之间', () => {
  const decoder = new SseDecoder();
  assert.deepEqual(decoder.push('data: a\r\n\r'), []);
  assert.deepEqual(decoder.push('\ndata: b\r\n\r\n'), [
    { event: 'message', data: 'a' },
    { event: 'message', data: 'b' },
  ]);
});

test('一个分片里多个事件', () => {
  const decoder = new SseDecoder();
  const messages = decoder.push('data: 1\n\ndata: 2\n\ndata: 3\n\n');
  assert.deepEqual(
    messages.map((m) => m.data),
    ['1', '2', '3'],
  );
});

test('心跳块被丢掉，不产生空事件', () => {
  const decoder = new SseDecoder();
  const messages = decoder.push(': ping\n\ndata: real\n\n');
  assert.deepEqual(messages, [{ event: 'message', data: 'real' }]);
});

test('尾部不完整的块不会被提前吐出', () => {
  const decoder = new SseDecoder();
  assert.deepEqual(decoder.push('data: 完整\n\ndata: 未完'), [{ event: 'message', data: '完整' }]);
  assert.deepEqual(decoder.push('成的\n\n'), [{ event: 'message', data: '未完成的' }]);
});

test('服务端真实输出的形状（sse_starlette）', () => {
  // sse_starlette 用 CRLF，并且带 id 字段
  const decoder = new SseDecoder();
  const raw =
    'event: task\r\nid: task_01\r\ndata: {"event":"task","task_id":"task_01"}\r\n\r\n';
  assert.deepEqual(decoder.push(raw), [
    { event: 'task', data: '{"event":"task","task_id":"task_01"}' },
  ]);
});
