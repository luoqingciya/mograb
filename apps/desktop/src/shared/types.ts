// SPDX-License-Identifier: GPL-3.0-only
//
// 与 API 契约及 Tauri IPC 对齐的类型定义与纯函数辅助。

export interface SourceOut {
  id: string;
  name: string;
  version: string;
  spec_version: number;
  homepage: string | null;
  repository: string | null;
  description: string | null;
  capabilities: string[];
  enabled: boolean;
  health: string;
  installed_version: string;
  previous_version: string | null;
}

export interface SourceDetail extends SourceOut {
  permissions: {
    network?: string[];
    cookies?: boolean;
    filesystem?: boolean;
    script?: boolean;
  };
  path: string;
}

export interface SourceInstallRequest {
  mode: 'yaml' | 'file';
  content?: string | null;
  path?: string | null;
  force?: boolean;
}

export interface SourceInstallResult {
  id: string;
  version: string;
  replaced: boolean;
  path: string;
  warnings: string[];
}

export interface RemoveSourceResult {
  removed: boolean;
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

export interface LocalHit {
  book_id: string;
  book_title: string;
  chapter_id: string;
  chapter_title: string;
  chapter_index: number;
  snippet: string;
}

export interface LocalSearchResponse {
  keyword: string;
  total: number;
  items: LocalHit[];
}

export interface BookOut {
  id: string;
  source_id: string;
  source_book_id: string;
  url: string;
  title: string;
  author: string | null;
  intro: string | null;
  language: string | null;
  cover_url: string | null;
  status: string;
  latest_chapter: string | null;
  chapter_count: number;
  word_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChapterSummaryOut {
  id: string;
  title: string;
  index: number;
  word_count: number;
  has_content: boolean;
}

export interface ChapterDetailOut extends ChapterSummaryOut {
  url: string;
  content: string | null;
  content_hash: string | null;
}

export interface UpdateResult {
  book_id: string;
  total: number;
  to_download: number;
  skipped: number;
  missing: string[];
  latest_chapter: string | null;
  dry_run: boolean;
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

export type ExportFormat = 'epub' | 'txt' | 'markdown';

export interface ExportCreate {
  book_id: string;
  format: ExportFormat;
  output?: string | null;
}

export interface ExportOut {
  id: string;
  book_id: string;
  format: string;
  status: string;
  path: string | null;
  size_bytes: number;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface CacheStatsOut {
  entries: number;
  sizeBytes: number;
  maxSizeBytes: number;
}

export interface AppSettingsOut {
  server: {
    host: string;
    port: number;
    health_timeout_ms: number;
    auth: boolean;
  };
  download: {
    concurrency: number;
    per_source_concurrency: number;
    retry: number;
    request_interval_ms: number;
    timeout_ms: number;
    proxy: string | null;
  };
  cache: {
    enabled: boolean;
    max_size: string;
    ttl_seconds: number;
    content_ttl_seconds: number;
  };
  output: {
    directory: string;
    format: string;
    template: string;
    chapter_template: string;
    metadata: Record<string, string>;
  };
  logging: {
    level: string;
    json_output: boolean;
    max_bytes: number;
    backup_count: number;
  };
}

export interface AppInfoOut {
  version: string;
  dataDir: string;
  configFile: string;
  database: string;
  coversDir: string;
  exportsDir: string;
  logsDir: string;
  sourcesDir: string;
  inProcess: boolean;
  settings: AppSettingsOut;
  cacheStats: CacheStatsOut | null;
}

export interface SettingsPatchInput {
  concurrency?: number;
  perSourceConcurrency?: number;
  requestIntervalMs?: number;
  timeoutMs?: number;
  retry?: number;
  proxy?: string;
  cacheEnabled?: boolean;
  cacheMaxSize?: string;
  outputFormat?: string;
  outputTemplate?: string;
  loggingLevel?: string;
}

export interface ClearCacheResult {
  removed: number;
  stats: CacheStatsOut;
}

/** 服务端的统一错误体。 */
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

export const SOURCE_HEALTH_LABEL: Record<string, string> = {
  healthy: '正常',
  degraded: '降级',
  broken: '异常',
  unsupported: '不兼容',
  unknown: '未检测',
};

export const BOOK_STATUS_LABEL: Record<string, string> = {
  ongoing: '连载中',
  completed: '已完结',
  hiatus: '停更',
  unknown: '未知',
};

export const EXPORT_STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '导出中',
  success: '已完成',
  failed: '失败',
};

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return '0 B';
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let idx = 0;
  let val = bytes;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx += 1;
  }
  return idx === 0 ? `${Math.round(val)} B` : `${val.toFixed(1)} ${units[idx]}`;
}

export function formatWordCount(words: number): string {
  if (!Number.isFinite(words) || words <= 0) {
    return '0 字';
  }
  if (words >= 10_000) {
    return `${(words / 10_000).toFixed(1)} 万字`;
  }
  return `${Math.round(words)} 字`;
}
