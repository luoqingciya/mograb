# mograb-api —— MoGrab 本地 API Server

FastAPI 实现的本地 REST API，是 CLI 与 Desktop 的共同后端。

## 运行

```bash
uv run mograb-api                 # 直接启动
uv run python -m mograb_api       # 等价
uv run mog server start           # 由 CLI 拉起
```

默认监听 `127.0.0.1:48721`（仅本机）。

## 端点

```
GET    /health                      健康检查
GET    /docs                        OpenAPI 文档

/api/v1/sources                     书源列表 / 安装 / 卸载 / 启停 / 健康检查
/api/v1/search                      跨书源搜索
/api/v1/books                       书架 / 详情 / 章节 / 增量更新
/api/v1/tasks                       任务创建 / 列表 / 详情 / 暂停 / 继续 / 取消 / 重试
/api/v1/tasks/{id}/events           SSE 单任务事件流
/api/v1/tasks/events                SSE 全局事件流
/api/v1/exports                     导出作业
```

## 错误模型

```json
{ "code": "SOURCE_PARSE_FAILED", "message": "...", "details": {} }
```

## 许可证

GPL-3.0-only
