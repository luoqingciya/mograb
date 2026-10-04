// SPDX-License-Identifier: GPL-3.0-only
//
// 与 API 契约对应的类型。
//
// 这些形状是从 Python 那边的 Pydantic 模型手工对齐过来的 —— 两边没有代码生成，
// 所以改 API 响应结构时记得同步这里。契约本身在 docs/api/api-v1.md。

export interface SourceOut {
  id: string;
  name: string;
  version: string;
  spec_version: number;
  homepage: string | null;
  description: string | null;
  capabilities: string[];
  enabled: boolean;
  health: string;
  installed_version: string;
  previous_version: string | null;
}

export interface SearchItem {
  source_id: string;
  title: string;
  url: string;
  author: string | null;
  cover_url: string | null;
  intro: string | null;
}

export interface SearchError {
  source_id: string;
  code: string;
  message: string;
}

export interface SearchResponse {
  keyword: string;
  total: number;
  items: SearchItem[];
  errors: SearchError[];
}

export interface BookOut {
  id: string;
  source_id: string;
  source_book_id: string;
  url: string;
  title: string;
  author: string | null;
  intro: string | null;
  status: string;
  latest_chapter: string | null;
  chapter_count: number;
  word_count: number;
  created_at: string;
  updated_at: string;
}

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'retrying'
  | 'success'
  | 'failed'
  | 'cancelled';

export type TaskType = 'download_book' | 'update_book' | 'export_book' | 'refresh_source';

export interface TaskOut {
  id: string;
  type: TaskType;
  status: TaskStatus;
  priority: number;
  book_id: string | null;
  source_id: string | null;
  total: number;
  completed: number;
  failed: number;
  progress: number;
  error_code: string | null;
  error_message: string | null;
  params: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** 服务端的统一错误体（规划书 §37）。 */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

/** SSE 推过来的任务事件。 */
export interface TaskEvent {
  event: 'task';
  task_id: string;
  type: TaskType;
  status: TaskStatus;
  book_id: string | null;
  total: number;
  completed: number;
  failed: number;
  error_code: string | null;
  error_message: string | null;
}

/** 终态任务不会再变，前端据此停止展示进度。 */
export function isTerminal(status: TaskStatus): boolean {
  return status === 'success' || status === 'failed' || status === 'cancelled';
}

/** 任务状态的中文标签。 */
export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  pending: '排队中',
  running: '进行中',
  paused: '已暂停',
  retrying: '重试中',
  success: '已完成',
  failed: '失败',
  cancelled: '已取消',
};
