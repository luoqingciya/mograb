# MoGrab Desktop

Electron 桌面客户端（**仅 Windows**）。

## 定位

Desktop = **Electron + MoGrab Local API（Sidecar）**，不是一个独立实现的下载器。

```
Electron (UI)
     │  REST + SSE
     ▼
mograb-api (Sidecar)
     │
     ▼
MoGrab Core
```

## 职责边界

Desktop **只负责**：UI 与状态展示、任务控制、配置、书架、书源管理、日志查看。

**禁止**在 Electron 中实现：解析器、下载器、数据库、书源执行器。

## 目录结构

```
apps/desktop/
├── src/
│   ├── main/            主进程（Node 环境）
│   │   ├── index.ts     窗口与应用生命周期
│   │   ├── backend.ts   后端 sidecar 的启动与健康检查
│   │   └── preload.ts   contextBridge（沙箱下必须是 CommonJS）
│   ├── renderer/        渲染进程（浏览器环境）
│   │   ├── index.html
│   │   ├── styles.css
│   │   ├── main.ts      入口：等后端就绪、搭界面、切页
│   │   ├── api.ts       本地 API 客户端
│   │   ├── dom.ts       极简 DOM 辅助
│   │   └── views/       各页面
│   └── shared/
│       └── types.ts     与 API 契约对应的类型
├── scripts/copy-static.mjs
├── tsconfig.base.json
├── tsconfig.main.json      主进程 → CommonJS
└── tsconfig.renderer.json  渲染层 → ES modules
```

## 构建方式

**TypeScript + tsc，不引打包器。**

渲染层用原生 ES modules（`<script type="module">`），所以不需要 bundler ——
`tsc` 编译完 Electron 直接加载。代价是没有热更新（用 `tsc --watch` 加手动刷新）。

两份 tsconfig 是必须的：主进程跑在 Node 里要 CommonJS，渲染层跑在浏览器里
要 ES modules。开 `sandbox` 时 preload 必须是 CommonJS，这也是 Electron 的限制。

版本号**不在构建时写进 `package.json`** —— 那样会让 `package-lock.json` 里的版本
对不上，`npm ci` 有风险。打包时通过 `--config.extraMetadata.version` 传进来
（见 `.github/workflows/release.yml`）。界面要显示版本就读后端 `/health`。

## 开发

```bash
cd apps/desktop
npm install
npm start          # 编译 + 启动；后端会自动拉起
npm run typecheck  # 只做类型检查
npm run build      # 只编译
```

后端由主进程自动拉起：打包后找 `resources/backend/mograb-api.exe`，
开发时用仓库里的 uv 环境跑 `mograb-api`。如果端口上已经有实例在跑（比如你
手动 `mog server start` 过），会直接复用它，不会重复启动。

## 当前进度

最小闭环已跑通：**搜索 → 点下载 → 看任务进度**。

| 页面 | 状态 |
|------|------|
| 搜索 | 可用 |
| 下载（任务） | 可用，SSE 实时进度 |
| 书架 | 占位 |
| 书源管理 | 占位 |
| 设置 | 占位 |

## 安全基线

- `contextIsolation: true`
- `nodeIntegration: false`
- `sandbox: true`
- CSP：`script-src 'self'`，`connect-src` 只放行本地 API
- 外部链接交给系统浏览器，不在应用内开新窗口
- 渲染进程只能通过 preload 暴露的 `window.mograb` 拿后端地址，
  业务请求直接 `fetch` 本地 API

## 许可证

GPL-3.0-only
