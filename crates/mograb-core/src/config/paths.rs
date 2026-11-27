// SPDX-License-Identifier: GPL-3.0-only
//! 运行目录与便携数据目录解析。

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

pub const APP_NAME: &str = "MoGrab";
pub const ENV_HOME: &str = "MOGRAB_HOME";

pub const DATA_DIRNAME: &str = "data";
pub const CONFIG_FILENAME: &str = "config.toml";
pub const TOKEN_FILENAME: &str = "token";
pub const DATABASE_FILENAME: &str = "mograb.db";
pub const COVERS_DIRNAME: &str = "covers";
pub const LOGS_DIRNAME: &str = "logs";
pub const EXPORTS_DIRNAME: &str = "exports";
pub const SOURCES_DIRNAME: &str = "sources";

const SUBDIRS: &[&str] = &[
    COVERS_DIRNAME,
    LOGS_DIRNAME,
    EXPORTS_DIRNAME,
    SOURCES_DIRNAME,
];

/// 判断是否以「打包发布后的可执行文件」身份运行。
/// cargo run / cargo test 产物在 `target/` 目录下，此时遵循 cwd；
/// 独立分发的二进制（或 release 产物不在 target 下）跟随可执行文件所在目录。
pub fn is_frozen() -> bool {
    let Ok(exe) = env::current_exe() else {
        return false;
    };
    let in_target = exe.components().any(|c| c.as_os_str() == "target");
    !in_target && !cfg!(test)
}

pub fn runtime_dir() -> PathBuf {
    if is_frozen()
        && let Ok(exe) = env::current_exe()
        && let Some(parent) = exe.parent()
    {
        return parent.to_path_buf();
    }
    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

pub fn data_dir() -> PathBuf {
    if let Ok(override_dir) = env::var(ENV_HOME)
        && !override_dir.trim().is_empty()
    {
        return expand_tilde(&override_dir);
    }
    runtime_dir().join(DATA_DIRNAME)
}

pub fn expand_tilde(raw: &str) -> PathBuf {
    if let Some(rest) = raw.strip_prefix("~/").or_else(|| raw.strip_prefix("~\\"))
        && let Some(home) = home_dir()
    {
        return home.join(rest);
    }
    if raw == "~"
        && let Some(home) = home_dir()
    {
        return home;
    }
    PathBuf::from(raw)
}

fn home_dir() -> Option<PathBuf> {
    env::var_os("HOME")
        .or_else(|| env::var_os("USERPROFILE"))
        .map(PathBuf::from)
}

#[derive(Debug, Clone)]
pub struct Paths {
    pub root: PathBuf,
    pub config_file: PathBuf,
    pub token_file: PathBuf,
    pub database: PathBuf,
    pub covers_dir: PathBuf,
    pub logs_dir: PathBuf,
    pub exports_dir: PathBuf,
    pub sources_dir: PathBuf,
}

impl Paths {
    pub fn from_root(root: impl AsRef<Path>) -> Self {
        let base = root.as_ref().to_path_buf();
        Self {
            config_file: base.join(CONFIG_FILENAME),
            token_file: base.join(TOKEN_FILENAME),
            database: base.join(DATABASE_FILENAME),
            covers_dir: base.join(COVERS_DIRNAME),
            logs_dir: base.join(LOGS_DIRNAME),
            exports_dir: base.join(EXPORTS_DIRNAME),
            sources_dir: base.join(SOURCES_DIRNAME),
            root: base,
        }
    }

    pub fn ensure(&self) -> std::io::Result<()> {
        fs::create_dir_all(&self.root)?;
        for name in SUBDIRS {
            fs::create_dir_all(self.root.join(name))?;
        }
        Ok(())
    }
}

pub fn get_paths(root: Option<&Path>) -> Paths {
    match root {
        Some(r) => Paths::from_root(r),
        None => Paths::from_root(data_dir()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_paths_ensure_creates_expected_subdirs() {
        let dir = tempfile::tempdir().unwrap();
        let paths = get_paths(Some(dir.path()));
        paths.ensure().unwrap();
        assert!(paths.covers_dir.is_dir());
        assert!(paths.logs_dir.is_dir());
        assert!(paths.exports_dir.is_dir());
        assert!(paths.sources_dir.is_dir());
        assert!(!dir.path().join("cache").exists());
    }
}
