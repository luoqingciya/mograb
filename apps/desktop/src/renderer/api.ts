// SPDX-License-Identifier: GPL-3.0-only
//
// 本地 API 客户端。
//
// 全部走 fetch —— 渲染进程和 API 在同一台机器上，没必要绕 IPC。
// CSP 里的 connect-src 已经限定只能连 127.0.0.1:48721。
//
// 鉴权：每个业务请求都带 Authorization: Bearer <token>，令牌由主进程读好后
// 经 preload 递过来。SSE 也因此不用 EventSource —— 它设不了请求头，
// 而把令牌塞进查询串会让它出现在访问日志里。

import type {
  ApiErrorBody,
  BookOut,
  SearchResponse,
  SourceOut,
  TaskEvent,
  TaskOut,
  TaskType,
} from '../shared/types.js';
import { subscribe } from './sse.js';

let baseUrl = '';
let token = '';

/** 由 main.ts 在拿到后端信息后调用。 */
export function configure(url: string, apiToken: string): void {
  baseUrl = url.replace(/\/$/, '');
  token = apiToken;
}

export function getBaseUrl(): string {
  return baseUrl;
}

export function isConfigured(): boolean {
  return baseUrl !== '';
}

/**
 * 断言已经配置过。
 *
 * 没配置就发请求的话，相对路径会被解析成 `file:///D:/...`，
 * 报出来的是 CSP 违规 —— 完全看不出真正的原因。这里拦一道，
 * 错误信息直接说清楚。
 */
function assertConfigured(): void {
  if (!isConfigured()) {
    throw new ApiError('NOT_CONFIGURED', '还没拿到后端地址就发请求了');
  }
}

/** 请求头。所有出站请求都从这里取，避免漏掉某个调用点。 */
function headers(extra?: Record<string, string>): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
    ...extra,
  };
}

/** 服务端返回的结构化错误（规划书 §37）。 */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  assertConfigured();

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: headers(init?.headers as Record<string, string> | undefined),
    });
  } catch (cause) {
    throw new ApiError('NETWORK_UNREACHABLE', '连不上本地服务', { cause: String(cause) });
  }

  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | null = null;
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    // 不是 JSON（比如代理返回的 HTML 错误页），下面兜底
  }
  if (body !== null && typeof body.code === 'string') {
    return new ApiError(body.code, body.message, body.details ?? {});
  }
  return new ApiError(`HTTP_${response.status}`, `请求失败（HTTP ${response.status}）`);
}

// ---------------------------------------------------------------------------
// 书源
// ---------------------------------------------------------------------------
export function listSources(): Promise<SourceOut[]> {
  return request<SourceOut[]>('/sources');
}

// ---------------------------------------------------------------------------
// 搜索
// ---------------------------------------------------------------------------
export function search(keyword: string, sources: string[] = [], limit = 20): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: keyword, limit: String(limit) });
  for (const id of sources) {
    params.append('source', id);
  }
  return request<SearchResponse>(`/search?${params.toString()}`);
}

// ---------------------------------------------------------------------------
// 书籍
// ---------------------------------------------------------------------------
export function listBooks(limit = 50): Promise<BookOut[]> {
  return request<BookOut[]>(`/books?limit=${limit}`);
}

// ---------------------------------------------------------------------------
// 任务
// ---------------------------------------------------------------------------
export interface CreateTaskInput {
  type: TaskType;
  bookId?: string;
  sourceId?: string;
  url?: string;
  params?: Record<string, unknown>;
}

export function createTask(input: CreateTaskInput): Promise<TaskOut> {
  return request<TaskOut>('/tasks', {
    method: 'POST',
    body: JSON.stringify({
      type: input.type,
      book_id: input.bookId ?? null,
      source_id: input.sourceId ?? null,
      url: input.url ?? null,
      params: input.params ?? {},
    }),
  });
}

export function listTasks(limit = 50): Promise<TaskOut[]> {
  return request<TaskOut[]>(`/tasks?limit=${limit}`);
}

export function getTask(taskId: string): Promise<TaskOut> {
  return request<TaskOut>(`/tasks/${taskId}`);
}

// ---------------------------------------------------------------------------
// SSE
// ---------------------------------------------------------------------------

/**
 * 订阅全局任务事件流。
 *
 * 返回一个取消订阅的函数。
 *
 * 传输层在 sse.ts（fetch + 手写解析 + 自动重连），这里只负责挑出 task 事件
 * 并反序列化。不用 EventSource 的原因见 sse.ts 开头。
 */
export function subscribeTaskEvents(onEvent: (event: TaskEvent) => void): () => void {
  assertConfigured();

  return subscribe({
    url: `${baseUrl}/tasks/events`,
    init: { headers: headers() },
    onMessage: (message) => {
      if (message.event !== 'task') {
        return;
      }
      try {
        onEvent(JSON.parse(message.data) as TaskEvent);
      } catch (error) {
        console.warn('[sse] 事件解析失败', error);
      }
    },
    onError: (error) => {
      console.warn('[sse] 事件流中断，准备重连', error);
    },
  });
}
