# MoGrab Desktop

Tauri v2 桌面客户端（Windows & Linux）。

## 定位

Desktop = **Tauri v2 + 进程内嵌入的 `mograb-api`**（不再依赖 Electron 与独立 sidecar 子进程），UI 层只负责展示与交互，核心业务逻辑完全走本地 API 与 `mograb-core`。

```
Tauri WebView (TypeScript ES Modules)
     │  Tauri IPC (`backend_wait`) + REST/SSE (`127.0.0.1:48721`)
     ▼
mograb-api (Axum, in-process)
     │
     ▼
mograb-core
```

## 职责边界

Desktop **只负责**：UI 与状态展示、任务控制、配置、书架、书源管理、日志查看。

**禁止**在前端层实现：解析器、下载器、数据库、书源执行器。

## 目录结构

```
apps/desktop/
├── src/
│   ├── renderer/             前端代码（浏览器原生 ES Modules）
│   │   ├── index.html
│   │   ├── styles.css
│   │   ├── env.d.ts          window.__TAURI__.core.invoke 类型声明
│   │   ├── main.ts           入口：invoke('backend_wait') 等后端就绪、搭界面
│   │   ├── api.ts            本地 API 客户端
│   │   ├── sse.ts            SSE 读取端（fetch + 手写解析 + 重连）
│   │   ├── dom.ts            极简 DOM 辅助
│   │   └── views/            各页面
│   └── shared/
│       └── types.ts          与 API 契约对应的类型
├── src-tauri/                Tauri v2 Rust 宿主 crate
│   ├── Cargo.toml
│   ├── Cargo.lock
│   ├── build.rs
│   ├── tauri.conf.json
│   ├── capabilities/default.json
│   ├── icons/
│   └── src/
│       ├── main.rs
│       └── lib.rs            进程内启动/复用 mograb-api、导航守卫与优雅退出
├── test/sse.test.mjs         SSE 解析器的测试（node:test）
├── scripts/copy-static.mjs
├── package.json
├── tsconfig.base.json
└── tsconfig.renderer.json    渲染层 → ES modules
```

## 构建方式

**TypeScript + tsc（零 bundler）+ Tauri v2 (`tauri.conf.json`)。**

- 前端使用原生 ES modules（`<script type="module">`），`npm run build` 把 HTML/CSS 与编译产物统一产出到 `dist/`（`frontendDist: "../dist"`）。
- `apps/desktop/src-tauri` 直接链接工作区内的 `mograb-core` 与 `mograb-api` crate，打包时产出的单二进制客户端自带后端服务，无需额外 sidecar。
- Linux 下打包安装运行于只读系统目录时，数据默认落入 `$XDG_DATA_HOME/mograb`（即 `~/.local/share/mograb`）；Windows 与本地开发模式跟随便携/仓库 `data/`，也可通过 `MOGRAB_HOME` 显式指定。

## 开发与打包

```bash
cd apps/desktop
npm install
npm run typecheck  # 类型检查
npm run build      # 构建 dist/
npm test           # SSE 解析器的单元测试
npm run dev        # 启动 Tauri 开发窗口（Linux 需先安装 webkit2gtk-4.1 等系统依赖）
npm run pack       # Windows: 生成 NSIS 安装包
npm run pack:linux # Linux: 生成 .deb 与 .rpm 安装包
```

## 鉴权与安全基线

- API 的每个业务端点均要求 `Authorization: Bearer <token>`。后端在进程内初始化后，通过 `backend_wait` IPC 命令将 `{ baseUrl, token }` 安全递交给前端；SSE 仍通过带请求头的 `fetch` 流式读取。
- `tauri.conf.json` 启用严格 CSP（仅允许 `'self'`、Tauri IPC 与 `http://127.0.0.1:48721`），并在 Rust 宿主层通过 `on_navigation` 拦截一切外部 URL 跳转。

## 已实现页面

| 页面 | 功能范围 |
|------|----------|
| 搜索 (`views/search.ts`) | 跨启用书源筛选搜索、按书籍详情页 URL 直链下载 |
| 书架 (`views/shelf.ts`) | 本地藏书列表与过滤、章节目录、内置正文阅读器（字号调节/翻章）、增量检查更新、EPUB/TXT/Markdown 导出 |
| 全文检索 (`views/find.ts`) | 本地章节正文关键词检索（按书筛选与高亮）、一键跳转至对应章节阅读 |
| 任务 (`views/tasks.ts`) | 状态过滤、SSE 实时进度条、暂停/继续/取消/重试控制、近期导出记录 |
| 书源 (`views/sources.ts`) | 粘贴 YAML / 本机文件路径安装、启用/禁用、在线体检、网络权限/路径详情查看、重新扫描与卸载 |
| 设置 (`views/settings.ts`) | 运行模式与路径查看、`config.toml` 核心参数修改保存、SQLite HTTP 缓存统计与清理 |
