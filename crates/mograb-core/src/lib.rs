// SPDX-License-Identifier: GPL-3.0-only
//! MoGrab 核心库入口。

pub mod app;
pub mod config;
pub mod content;
pub mod covers;
pub mod domain;
pub mod errors;
pub mod export;
pub mod logging;
pub mod network;
pub mod source;
pub mod storage;
pub mod task;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    use super::VERSION;

    #[test]
    fn test_version_matches_root_version_file() {
        let root_version = include_str!("../../../VERSION").trim();
        assert_eq!(root_version, VERSION);
    }
}
