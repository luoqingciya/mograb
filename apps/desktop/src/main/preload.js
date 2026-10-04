// SPDX-License-Identifier: GPL-3.0-only
//
// 预加载脚本：在隔离上下文中向渲染进程暴露最小 API。
// 只暴露「调用本地 API」的能力，不暴露 Node 能力（安全基线）。

'use strict';

const { contextBridge } = require('electron');

const API_BASE = 'http://127.0.0.1:48721/api/v1';

contextBridge.exposeInMainWorld('mograb', {
  baseUrl: API_BASE,
  /** 发起 GET 请求。 */
  async get(path) {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
  /** 发起 POST 请求。 */
  async post(path, body) {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
  /** 订阅任务事件流（SSE）。 */
  subscribeTaskEvents(onEvent) {
    const source = new EventSource(`${API_BASE}/tasks/events`);
    source.onmessage = (e) => onEvent(JSON.parse(e.data));
    return () => source.close();
  },
});
