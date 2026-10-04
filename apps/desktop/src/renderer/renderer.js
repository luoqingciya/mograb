// SPDX-License-Identifier: GPL-3.0-only
//
// 渲染进程：页面切换与本地 API 连通性检查（骨架）。

'use strict';

document.querySelectorAll('.nav-item').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('.page').forEach((p) => p.classList.remove('active'));
    btn.classList.add('active');
    const page = document.getElementById(`page-${btn.dataset.page}`);
    if (page) page.classList.add('active');
  });
});

// 连通性检查：确认本地 API Server 已就绪
if (window.mograb) {
  fetch(`${window.mograb.baseUrl.replace('/api/v1', '')}/health`)
    .then((r) => r.json())
    .then((d) => console.info('[mograb] 本地 API 就绪:', d))
    .catch((e) => console.warn('[mograb] 本地 API 不可达:', e.message));
}
