// SPDX-License-Identifier: GPL-3.0-only
//! 配置模块入口。

pub mod paths;
pub mod settings;
pub mod token;

pub use paths::{
    APP_NAME, CONFIG_FILENAME, COVERS_DIRNAME, DATA_DIRNAME, DATABASE_FILENAME, ENV_HOME,
    EXPORTS_DIRNAME, LOGS_DIRNAME, Paths, SOURCES_DIRNAME, TOKEN_FILENAME, data_dir, get_paths,
    is_frozen, runtime_dir,
};
pub use settings::{
    AppSettings, CacheSettings, DEFAULT_CONFIG_TOML, DownloadSettings, LoggingSettings,
    OutputSettings, ServerSettings, load_settings, parse_size, write_default_config,
};
pub use token::{TOKEN_BYTES, ensure_token, generate_token, read_token};
