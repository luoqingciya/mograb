// SPDX-License-Identifier: GPL-3.0-only
//
// 渲染进程看到的全局声明。
// Tauri v2 在 `withGlobalTauri: true` 下通过 `window.__TAURI__.core.invoke` 注入 IPC。

interface BackendInfo {
  /** API 根地址，如 http://127.0.0.1:48721/api/v1。 */
  baseUrl: string;
  /** API 访问令牌。每个业务请求都要带 Authorization: Bearer。 */
  token: string;
}

interface TauriCoreApi {
  invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T>;
}

interface Window {
  readonly __TAURI__?: {
    readonly core: TauriCoreApi;
  };
}
