// SPDX-License-Identifier: GPL-3.0-only
//
// MoGrab Desktop 主进程。
//
// 职责边界（规划书 §32）：只做 UI 宿主、后端生命周期、窗口管理。
// 解析器、下载器、数据库、书源执行器一概不在这里 —— 那些在 mograb-api 里。
//
// 启动流程（§34）：
//
//     创建窗口（显示「正在启动」）
//          ↓
//     拉起 mograb-api（后台进行）
//          ↓
//     渲染进程问「好了没」→ 就绪后开始干活

import { join } from 'node:path';

import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron';

import { type BackendInfo, isBackendReady, startBackend, stopBackend } from './backend';

/** 后端起好之前先挂着，渲染进程 await 它。 */
let backendReady: Promise<BackendInfo> | null = null;

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 900,
    minHeight: 600,
    title: 'MoGrab',
    backgroundColor: '#1b1d23',
    show: false,
    webPreferences: {
      // 安全基线：渲染进程拿不到 Node，只能用 preload 暴露的那几个方法
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: join(__dirname, 'preload.js'),
    },
  });

  window.once('ready-to-show', () => window.show());
  window.loadFile(join(__dirname, '..', 'renderer', 'index.html'));

  // 开发时把渲染进程的 console 转发到终端。
  // 不转发的话，前端请求失败（CORS、401、解析出错）在终端里完全看不见 ——
  // 后端日志照样记 200，看起来一切正常。
  if (!app.isPackaged) {
    window.webContents.on('console-message', (_event, level, message) => {
      console.log(`[renderer:${level}] ${message}`);
    });
  }

  // 外部链接交给系统浏览器，不在应用里开新窗口
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://')) {
      event.preventDefault();
      void shell.openExternal(url);
    }
  });

  return window;
}

function registerIpc(): void {
  // 渲染进程启动时 await 这个。后端失败时它会 reject，前端据此显示错误。
  // 返回里带令牌 —— 渲染进程拿不到文件系统，只能由主进程读好递过去。
  ipcMain.handle('backend:wait', async () => {
    if (backendReady === null) {
      throw new Error('后端尚未启动');
    }
    return await backendReady;
  });

  ipcMain.handle('backend:ping', () => isBackendReady());
}

app.whenReady().then(() => {
  registerIpc();
  const window = createWindow();

  // 先把窗口显示出来（渲染进程会显示「正在启动」），再去拉后端。
  // 反过来做的话，后端起得慢时用户面对的是十几秒白屏。
  backendReady = startBackend();
  backendReady.catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    console.error('[main] 后端启动失败:', message);
    if (!window.isDestroyed()) {
      void dialog.showMessageBox(window, {
        type: 'error',
        title: '后端启动失败',
        message: 'MoGrab 的本地服务没能起来，界面无法工作。',
        detail: message,
      });
    }
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', () => {
  stopBackend();
});
