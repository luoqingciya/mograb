# MoGrab Desktop

Electron 桌面客户端（**仅 Windows**）。

## 定位

Desktop = **Electron + MoGrab Local API（Sidecar）**，不是一个独立实现的下载器。

```
Electron (UI)
     │  REST + SSE
     ▼
mograb-api.exe (Sidecar)
     │
     ▼
MoGrab Core
```

## 职责边界

Desktop **只负责**：

- UI 与状态展示
- 任务控制
- 配置
- 书架
- 书源管理
- 日志查看

**禁止**在 Electron 中实现：解析器、下载器、数据库、书源执行器。

## 安全基线

- `contextIsolation: true`
- `nodeIntegration: false`
- `sandbox: true`
- CSP 限制 `connect-src` 为本地 API
- 渲染进程仅通过 preload 暴露的 `window.mograb` 访问后端

## 开发

```bash
cd apps/desktop
npm install
npm start        # 需先启动后端： uv run mograb-api
```

## 许可证

GPL-3.0-only
