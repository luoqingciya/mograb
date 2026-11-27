// SPDX-License-Identifier: GPL-3.0-only
//
// 本地 API + Tauri IPC 客户端。

import type {
  ApiErrorBody,
  AppInfoOut,
  AppSettingsOut,
  BookOut,
  ChapterDetailOut,
  ChapterSummaryOut,
  ClearCacheResult,
  ExportCreate,
  ExportOut,
  LocalSearchResponse,
  RemoveSourceResult,
  SearchResponse,
  SettingsPatchInput,
  SourceDetail,
  SourceInstallRequest,
  SourceInstallResult,
  SourceOut,
  TaskEvent,
  TaskOut,
  TaskType,
  UpdateResult,
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

function assertConfigured(): void {
  if (!isConfigured()) {
    throw new ApiError('NOT_CONFIGURED', '还没拿到后端地址就发请求了');
  }
}

function headers(extra?: Record<string, string>): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
    ...extra,
  };
}

/** 服务端返回的结构化错误。 */
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
    // 非 JSON 兜底
  }
  if (body !== null && typeof body.code === 'string') {
    return new ApiError(body.code, body.message, body.details ?? {});
  }
  return new ApiError(`HTTP_${response.status}`, `请求失败（HTTP ${response.status}）`);
}

function invokeTauri<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (invoke === undefined) {
    return Promise.reject(new ApiError('NO_TAURI_RUNTIME', '未检测到 Tauri 运行时'));
  }
  return invoke<T>(cmd, args);
}

// ---------------------------------------------------------------------------
// Tauri IPC（设置、路径、缓存）
// ---------------------------------------------------------------------------
export function getAppInfo(): Promise<AppInfoOut> {
  return invokeTauri<AppInfoOut>('get_app_info');
}

export function saveSettings(patch: SettingsPatchInput): Promise<AppSettingsOut> {
  return invokeTauri<AppSettingsOut>('save_settings', { patch });
}

export function clearHttpCache(expiredOnly = false): Promise<ClearCacheResult> {
  return invokeTauri<ClearCacheResult>('clear_http_cache', { expiredOnly });
}

// ---------------------------------------------------------------------------
// 书源
// ---------------------------------------------------------------------------
export function listSources(): Promise<SourceOut[]> {
  return request<SourceOut[]>('/sources');
}

export function getSource(sourceId: string): Promise<SourceDetail> {
  return request<SourceDetail>(`/sources/${encodeURIComponent(sourceId)}`);
}

export function installSource(payload: SourceInstallRequest): Promise<SourceInstallResult> {
  return request<SourceInstallResult>('/sources', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function removeSource(sourceId: string): Promise<RemoveSourceResult> {
  return request<RemoveSourceResult>(`/sources/${encodeURIComponent(sourceId)}`, {
    method: 'DELETE',
  });
}

export function enableSource(sourceId: string): Promise<SourceOut> {
  return request<SourceOut>(`/sources/${encodeURIComponent(sourceId)}/enable`, {
    method: 'POST',
  });
}

export function disableSource(sourceId: string): Promise<SourceOut> {
  return request<SourceOut>(`/sources/${encodeURIComponent(sourceId)}/disable`, {
    method: 'POST',
  });
}

export function rescanSources(): Promise<SourceOut[]> {
  return request<SourceOut[]>('/sources/rescan', { method: 'POST' });
}

export function doctorSource(sourceId: string, live = true): Promise<SourceOut> {
  return request<SourceOut>(
    `/sources/${encodeURIComponent(sourceId)}/doctor?live=${live ? 'true' : 'false'}`,
    { method: 'POST' },
  );
}

// ---------------------------------------------------------------------------
// 搜索（线上 & 本地全文）
// ---------------------------------------------------------------------------
export function search(keyword: string, sources: string[] = [], limit = 20): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: keyword, limit: String(limit) });
  for (const id of sources) {
    params.append('source', id);
  }
  return request<SearchResponse>(`/search?${params.toString()}`);
}

export function searchLocal(
  keyword: string,
  bookId?: string,
  limit = 50,
): Promise<LocalSearchResponse> {
  const params = new URLSearchParams({ q: keyword, limit: String(limit) });
  if (bookId && bookId.trim() !== '') {
    params.set('book_id', bookId.trim());
  }
  return request<LocalSearchResponse>(`/search/local?${params.toString()}`);
}

// ---------------------------------------------------------------------------
// 书籍与章节
// ---------------------------------------------------------------------------
export function listBooks(limit = 50): Promise<BookOut[]> {
  return request<BookOut[]>(`/books?limit=${limit}`);
}

export function getBook(bookId: string): Promise<BookOut> {
  return request<BookOut>(`/books/${encodeURIComponent(bookId)}`);
}

export function listChapters(bookId: string): Promise<ChapterSummaryOut[]> {
  return request<ChapterSummaryOut[]>(`/books/${encodeURIComponent(bookId)}/chapters`);
}

export function getChapter(bookId: string, chapterId: string): Promise<ChapterDetailOut> {
  return request<ChapterDetailOut>(
    `/books/${encodeURIComponent(bookId)}/chapters/${encodeURIComponent(chapterId)}`,
  );
}

export function updateBook(bookId: string, dryRun = true): Promise<UpdateResult> {
  return request<UpdateResult>(
    `/books/${encodeURIComponent(bookId)}/update?dry_run=${dryRun ? 'true' : 'false'}`,
    { method: 'POST' },
  );
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
  return request<TaskOut>(`/tasks/${encodeURIComponent(taskId)}`);
}

export function pauseTask(taskId: string): Promise<TaskOut> {
  return request<TaskOut>(`/tasks/${encodeURIComponent(taskId)}/pause`, { method: 'POST' });
}

export function resumeTask(taskId: string): Promise<TaskOut> {
  return request<TaskOut>(`/tasks/${encodeURIComponent(taskId)}/resume`, { method: 'POST' });
}

export function cancelTask(taskId: string): Promise<TaskOut> {
  return request<TaskOut>(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' });
}

export function retryTask(taskId: string): Promise<TaskOut> {
  return request<TaskOut>(`/tasks/${encodeURIComponent(taskId)}/retry`, { method: 'POST' });
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------
export function createExport(payload: ExportCreate): Promise<ExportOut> {
  return request<ExportOut>('/exports', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listExports(limit = 20): Promise<ExportOut[]> {
  return request<ExportOut[]>(`/exports?limit=${limit}`);
}

export function getExport(exportId: string): Promise<ExportOut> {
  return request<ExportOut>(`/exports/${encodeURIComponent(exportId)}`);
}

// ---------------------------------------------------------------------------
// SSE
// ---------------------------------------------------------------------------
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
