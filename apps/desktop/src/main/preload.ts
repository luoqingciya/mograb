// SPDX-License-Identifier: GPL-3.0-only
//
// 预加载脚本：在隔离上下文里向渲染进程暴露最小接口。
//
// 只暴露「后端好了没、地址是多少、令牌是什么」。业务请求由渲染进程直接
// fetch 本地 API —— 没必要每个请求都绕一次 IPC，而且 API 本来就是 REST。
//
// 令牌必须从这里过去：渲染进程开了 sandbox、拿不到文件系统，
// 而 API 的每个业务端点都要求 Authorization 头。
//
// 注意：窗口开了 sandbox，preload 必须是 CommonJS（Electron 的限制），
// 所以这个文件用 tsconfig.main.json 编译。

import { contextBridge, ipcRenderer } from 'electron';

interface BackendInfo {
  baseUrl: string;
  token: string;
}

contextBridge.exposeInMainWorld('mograb', {
  /**
   * 等后端就绪，返回 API 根地址与访问令牌。
   *
   * 后端起不来时这个 Promise 会 reject，调用方据此显示错误。
   */
  async waitForBackend(): Promise<BackendInfo> {
    return (await ipcRenderer.invoke('backend:wait')) as BackendInfo;
  },
});
