// SPDX-License-Identifier: GPL-3.0-only
//! 本地 API 访问令牌生成与并发安全读写。

use super::paths::{Paths, get_paths};
use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use rand::Rng;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::thread;
use std::time::{Duration, Instant};

pub const TOKEN_BYTES: usize = 32;
const SETTLE_TIMEOUT: Duration = Duration::from_secs(1);
const SETTLE_INTERVAL: Duration = Duration::from_millis(10);

pub fn generate_token() -> String {
    let mut bytes = [0u8; TOKEN_BYTES];
    rand::rng().fill_bytes(&mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}

pub fn read_token(paths: Option<&Paths>) -> Option<String> {
    let owned;
    let resolved = match paths {
        Some(p) => p,
        None => {
            owned = get_paths(None);
            &owned
        }
    };
    let path = &resolved.token_file;
    if !path.is_file() {
        return None;
    }
    let text = fs::read_to_string(path).ok()?;
    let trimmed = text.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

pub fn ensure_token(paths: Option<&Paths>) -> std::io::Result<String> {
    let owned;
    let resolved = match paths {
        Some(p) => p,
        None => {
            owned = get_paths(None);
            &owned
        }
    };
    if let Some(existing) = read_token(Some(resolved)) {
        return Ok(existing);
    }

    let token = generate_token();
    if create_exclusive(&resolved.token_file, &token)? {
        return Ok(token);
    }

    if let Some(settled) = read_until_settled(resolved) {
        return Ok(settled);
    }

    // 存在但持续为空，清理后重试一次
    let _ = fs::remove_file(&resolved.token_file);
    if create_exclusive(&resolved.token_file, &token)? {
        return Ok(token);
    }
    Ok(read_until_settled(resolved).unwrap_or(token))
}

fn create_exclusive(path: &Path, token: &str) -> std::io::Result<bool> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut opts = OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }

    let mut file = match opts.open(path) {
        Ok(f) => f,
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => return Ok(false),
        Err(e) => return Err(e),
    };
    writeln!(file, "{token}")?;
    file.flush()?;
    Ok(true)
}

fn read_until_settled(paths: &Paths) -> Option<String> {
    let deadline = Instant::now() + SETTLE_TIMEOUT;
    loop {
        if let Some(t) = read_token(Some(paths)) {
            return Some(t);
        }
        if Instant::now() >= deadline {
            return None;
        }
        thread::sleep(SETTLE_INTERVAL);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ensure_token_idempotent_and_length() {
        let dir = tempfile::tempdir().unwrap();
        let paths = get_paths(Some(dir.path()));
        let t1 = ensure_token(Some(&paths)).unwrap();
        let t2 = ensure_token(Some(&paths)).unwrap();
        assert_eq!(t1, t2);
        assert_eq!(t1.len(), 43);
        assert_eq!(read_token(Some(&paths)).as_deref(), Some(t1.as_str()));
    }
}
