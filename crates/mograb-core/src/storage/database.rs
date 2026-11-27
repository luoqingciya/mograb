// SPDX-License-Identifier: GPL-3.0-only
//! SQLite 数据库连接池与迁移。

use crate::errors::{MoGrabError, MoGrabResult};
use sqlx::SqlitePool;
use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tracing::info;

#[derive(Clone)]
pub struct Database {
    path: PathBuf,
    pool: SqlitePool,
}

impl Database {
    pub async fn open(path: impl AsRef<Path>) -> MoGrabResult<Self> {
        let path_buf = path.as_ref().to_path_buf();
        if let Some(parent) = path_buf.parent()
            && !parent.as_os_str().is_empty()
        {
            fs::create_dir_all(parent).map_err(|e| MoGrabError::storage(e.to_string()))?;
        }

        let opts = SqliteConnectOptions::new()
            .filename(&path_buf)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .foreign_keys(true)
            .synchronous(SqliteSynchronous::Normal)
            .busy_timeout(Duration::from_secs(5));

        let pool = SqlitePoolOptions::new()
            .max_connections(5)
            .connect_with(opts)
            .await
            .map_err(|e| MoGrabError::storage(format!("连接 SQLite 失败: {e}")))?;

        Ok(Self {
            path: path_buf,
            pool,
        })
    }

    pub async fn init_schema(&self) -> MoGrabResult<()> {
        sqlx::migrate!("./migrations")
            .run(&self.pool)
            .await
            .map_err(|e| MoGrabError::storage(format!("执行数据库迁移失败: {e}")))?;
        info!(path = %self.path.display(), "storage.schema_ready");
        Ok(())
    }

    pub fn pool(&self) -> &SqlitePool {
        &self.pool
    }

    pub async fn dispose(&self) {
        self.pool.close().await;
    }
}
