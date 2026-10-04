// SPDX-License-Identifier: GPL-3.0-only
//
// MoGrab Desktop —— Electron 主进程（骨架）。
//
// 职责边界（规划书 §32、§61）：
//   Desktop 只负责 UI / 状态展示 / 任务控制 / 配置 / 书架 / 书源管理 / 日志查看。
//   禁止在 Electron 中实现：解析器、下载器、数据库、书源执行器。
//
// Desktop = Electron + MoGrab Local API（Sidecar，规划书 §34、§57.3）。

'use strict';

const { app, BrowserWindow } = require('electron');
const path = require('node:path');
const { spawn } = require('node:child_process');

/** @type {import('node:child_process').ChildProcess | null} */
let backend = null;

/**
 * 启动本地 MoGrab API Server（Sidecar）。
 * 规划书 §34：Electron 启动 → 启动 Server → 健康检查 → 加载 UI。
 */
function startBackend() {
  const exe = path.join(process.resourcesPath || '.', 'backend', 'mograb-api.exe');
  backend = spawn(exe, [], { stdio: 'ignore' });
  backend.on('error', (err) => {
    console.error('[mograb] 后端启动失败:', err.message);
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'MoGrab',
    webPreferences: {
      // 安全基线（规划书 §40 未明确，此处补齐）
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
}

app.whenReady().then(() => {
  startBackend();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (backend && !backend.killed) backend.kill();
});
