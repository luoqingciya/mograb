// SPDX-License-Identifier: GPL-3.0-only
//
// 渲染进程看到的全局声明。
// preload 通过 contextBridge 挂上来的东西在这里补类型。

interface BackendInfo {
  /** API 根地址，如 http://127.0.0.1:48721/api/v1。 */
  baseUrl: string;
  /** API 访问令牌。每个业务请求都要带 Authorization: Bearer。 */
  token: string;
}

interface MoGrabBridge {
  /** 等后端就绪，返回 API 根地址与访问令牌。 */
  waitForBackend(): Promise<BackendInfo>;
}

interface Window {
  readonly mograb: MoGrabBridge;
}
