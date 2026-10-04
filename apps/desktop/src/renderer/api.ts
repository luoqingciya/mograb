// SPDX-License-Identifier: GPL-3.0-only
//
// 本地 API 客户端。
//
// 全部走 fetch —— 渲染进程和 API 在同一台机器上，没必要绕 IPC。
// CSP 里的 connect-src 已经限定只能连 127.0.0.1:48721。

import type {
  ApiErrorBody,
  BookOut,
  SearchResponse,
  SourceOut,
  TaskEvent,
  TaskOut,
  TaskType,
} from '../shared/types.js';

let baseUrl = '';

/** 由 main.ts 在拿到后端地址后调用。 */
export function setBaseUrl(url: string): void {
  baseUrl = url.replace(/\/$/, '');
}

export function getBaseUrl(): string {
  return baseUrl;
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
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
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
 * 返回一个取消订阅的函数。连不上时浏览器会自动重连，这里不额外处理。
 */
export function subscribeTaskEvents(onEvent: (event: TaskEvent) => void): () => void {
  const source = new EventSource(`${baseUrl}/tasks/events`);
  source.addEventListener('task', (raw) => {
    try {
      onEvent(JSON.parse((raw as MessageEvent<string>).data) as TaskEvent);
    } catch (error) {
      console.warn('[sse] 事件解析失败', error);
    }
  });
  return () => source.close();
}
