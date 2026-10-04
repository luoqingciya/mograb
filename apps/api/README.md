# mograb-api —— MoGrab 本地 API Server

FastAPI 实现的本地 REST API，是 CLI 与 Desktop 的共同后端。

## 运行

```bash
uv run mograb-api                 # 直接启动
uv run python -m mograb_api       # 等价
uv run mog server start           # 由 CLI 拉起
```

默认监听 `127.0.0.1:48721`（仅本机）。

## 认证

**除 `/health`、`/docs`、`/redoc`、`/openapi.json` 外，所有端点都要求
`Authorization: Bearer <token>`。**

令牌首次启动时自动生成在数据目录下的 `token` 文件，之后复用。
**不在 `config.toml` 里** —— 那个文件会被备份、被贴进 issue、在机器之间拷贝。
手工调接口时用 `mog server token` 打印：

```bash
TOKEN=$(uv run mog server token)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:48721/api/v1/sources
```

**只认请求头，不接受 `?token=` 查询参数** —— 后者会让令牌进访问日志。
桌面端的 SSE 因此用 fetch 读流而不是 `EventSource`（它设不了请求头）。

回环地址不构成信任边界：浏览器里的任意页面都能向 `127.0.0.1` 发请求，
简单请求（表单编码、`text/plain`）连预检都不触发，CORS 只约束能不能**读响应**。
详见 [ADR-0004](../../docs/architecture/decisions/ADR-0004-local-api-auth.md)。

## 端点

```
GET    /health                      健康检查（无需令牌）
GET    /docs                        Swagger UI（无需令牌）

/api/v1/sources                     列表 / 安装 / 卸载 / 启停 / 重扫 / 体检
/api/v1/search                      跨书源搜索
/api/v1/books                       书架 / 详情 / 章节 / 增量更新
/api/v1/tasks                       创建 / 列表 / 详情 / 暂停 / 继续 / 取消 / 重试
/api/v1/tasks/{id}/events           SSE 单任务事件流
/api/v1/tasks/events                SSE 全局事件流
/api/v1/exports                     导出作业
```

23 条路径 / 27 个端点。完整契约见 [API v1](../../docs/api/api-v1.md)。

## 错误模型

```json
{ "code": "SOURCE_PARSE_FAILED", "message": "...", "details": {} }
```

## 许可证

GPL-3.0-only
