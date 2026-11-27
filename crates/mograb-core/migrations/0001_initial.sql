-- MoGrab Storage v1 initial schema

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    spec_version INTEGER NOT NULL DEFAULT 1,
    homepage TEXT,
    license TEXT,
    capabilities TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    installed_version TEXT NOT NULL DEFAULT '',
    previous_version TEXT,
    health TEXT NOT NULL DEFAULT 'unknown',
    installed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    source_book_id TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    author TEXT,
    intro TEXT,
    language TEXT,
    cover_url TEXT,
    cover_path TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    latest_chapter TEXT,
    word_count INTEGER NOT NULL DEFAULT 0,
    chapter_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT uq_book_identity UNIQUE (source_id, source_book_id)
);

CREATE INDEX IF NOT EXISTS ix_books_source_id ON books(source_id);
CREATE INDEX IF NOT EXISTS ix_books_source_book_id ON books(source_book_id);
CREATE INDEX IF NOT EXISTS ix_books_title ON books(title);
CREATE INDEX IF NOT EXISTS ix_books_author ON books(author);
CREATE INDEX IF NOT EXISTS ix_books_updated_at ON books(updated_at);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    source_chapter_id TEXT,
    identity_key TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL DEFAULT '',
    "index" INTEGER NOT NULL DEFAULT 0,
    content TEXT,
    content_hash TEXT,
    word_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT uq_chapter_identity UNIQUE (book_id, identity_key)
);

CREATE INDEX IF NOT EXISTS ix_chapters_book_id ON chapters(book_id);
CREATE INDEX IF NOT EXISTS ix_chapters_identity_key ON chapters(identity_key);
CREATE INDEX IF NOT EXISTS ix_chapters_content_hash ON chapters(content_hash);
CREATE INDEX IF NOT EXISTS ix_chapter_book_index ON chapters(book_id, "index");

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    source_id TEXT,
    book_id TEXT REFERENCES books(id),
    total INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    resume_cursor INTEGER,
    params TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_tasks_type ON tasks(type);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS ix_tasks_book_id ON tasks(book_id);

CREATE TABLE IF NOT EXISTS task_items (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    chapter_id TEXT,
    chapter_index INTEGER,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_task_items_task_id ON task_items(task_id);
CREATE INDEX IF NOT EXISTS ix_task_items_status ON task_items(status);

CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id),
    format TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    path TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_exports_book_id ON exports(book_id);

CREATE TABLE IF NOT EXISTS http_cache (
    key TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    encoding TEXT,
    content BLOB NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_http_cache_source_id ON http_cache(source_id);
CREATE INDEX IF NOT EXISTS ix_http_cache_expires ON http_cache(expires_at);
CREATE INDEX IF NOT EXISTS ix_http_cache_accessed ON http_cache(accessed_at);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
