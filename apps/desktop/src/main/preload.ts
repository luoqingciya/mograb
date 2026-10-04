// SPDX-License-Identifier: GPL-3.0-only
//
// 预加载脚本：在隔离上下文里向渲染进程暴露最小接口。
//
// 只暴露「后端好了没、地址是多少」。业务请求由渲染进程直接 fetch 本地 API ——
// 没必要每个请求都绕一次 IPC，而且 API 本来就是 REST，前端直接用更自然。
//
// 注意：窗口开了 sandbox，preload 必须是 CommonJS（Electron 的限制），
// 所以这个文件用 tsconfig.main.json 编译。

import { contextBridge, ipcRenderer } from 'electron';

interface BackendInfo {
  baseUrl: string;
}

contextBridge.exposeInMainWorld('mograb', {
  /**
   * 等后端就绪，返回 API 根地址。
   *
   * 后端起不来时这个 Promise 会 reject，调用方据此显示错误。
   */
  async waitForBackend(): Promise<string> {
    const info = (await ipcRenderer.invoke('backend:wait')) as BackendInfo;
    return info.baseUrl;
  },
});
