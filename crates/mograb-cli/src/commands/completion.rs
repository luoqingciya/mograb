// SPDX-License-Identifier: GPL-3.0-only
//! `mog completion` —— 生成 Shell 自动补全脚本。

use clap::Args;
use clap_complete::{Shell, generate};
use std::io;

#[derive(Debug, Args)]
pub struct CompletionArgs {
    /// 目标 Shell（bash / zsh / fish / powershell / elvish）
    #[arg(value_enum)]
    pub shell: Shell,
}

pub fn run(args: CompletionArgs, cmd: &mut clap::Command) {
    generate(args.shell, cmd, "mog", &mut io::stdout());
}
