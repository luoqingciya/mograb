// SPDX-License-Identifier: GPL-3.0-only
//! `mog` —— MoGrab 命令行入口。

mod api_client;
mod commands;
mod common;

use crate::common::{CliExit, EXIT_OK};
use clap::{CommandFactory, Parser, Subcommand};

const VERSION_STR: &str = concat!("mog (MoGrab) ", env!("CARGO_PKG_VERSION"));

#[derive(Debug, Parser)]
#[command(
    name = "mog",
    about = "MoGrab — 模块化、桌面优先的网络小说抓取与电子书阅读工具",
    version = env!("CARGO_PKG_VERSION"),
    disable_version_flag = true,
    arg_required_else_help = true
)]
struct Cli {
    /// 显示版本信息并退出
    #[arg(short = 'V', long = "version", global = true)]
    version: bool,

    /// 输出详细调试日志
    #[arg(short = 'v', long = "verbose", global = true)]
    verbose: bool,

    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// 初始化数据目录、默认配置、数据库与认证令牌
    Init(commands::init::InitArgs),
    /// 配置与路径管理
    Config(commands::config::ConfigArgs),
    /// 书源管理与验证
    Source(commands::source::SourceArgs),
    /// 并发搜索多个已启用书源
    Search(commands::search::SearchArgs),
    /// 书架列表、书籍详情与章节查看
    Book(commands::book::BookArgs),
    /// 下载整本（或按目录/URL）并可选导出
    Download(commands::download::DownloadArgs),
    /// 增量检查并更新已入库书籍
    Update(commands::update::UpdateArgs),
    /// 导出本地已下载书籍（txt / markdown / epub）
    Export(commands::export::ExportArgs),
    /// 全文检索本地已下载章节正文
    Find(commands::find::FindArgs),
    /// 任务队列查看与控制
    Task(commands::task::TaskArgs),
    /// HTTP 缓存统计与清理
    Cache(commands::cache::CacheArgs),
    /// 本地 REST API 服务与令牌管理
    Server(commands::server::ServerArgs),
    /// 查看应用、任务或书源日志
    Logs(commands::logs::LogsArgs),
    /// 生成 Shell 自动补全脚本
    Completion(commands::completion::CompletionArgs),
}

async fn dispatch() -> Result<(), CliExit> {
    let cli = Cli::parse();
    if cli.version {
        println!("{VERSION_STR}");
        return Ok(());
    }
    let Some(cmd) = cli.command else {
        let mut root = Cli::command();
        let _ = root.print_help();
        return Ok(());
    };
    let verbose = cli.verbose;
    match cmd {
        Commands::Init(a) => commands::init::run(a, verbose).await,
        Commands::Config(a) => commands::config::run(a),
        Commands::Source(a) => commands::source::run(a, verbose).await,
        Commands::Search(a) => commands::search::run(a, verbose).await,
        Commands::Book(a) => commands::book::run(a, verbose).await,
        Commands::Download(a) => commands::download::run(a, verbose).await,
        Commands::Update(a) => commands::update::run(a, verbose).await,
        Commands::Export(a) => commands::export::run(a, verbose).await,
        Commands::Find(a) => commands::find::run(a, verbose).await,
        Commands::Task(a) => commands::task::run(a, verbose).await,
        Commands::Cache(a) => commands::cache::run(a, verbose).await,
        Commands::Server(a) => commands::server::run(a).await,
        Commands::Logs(a) => commands::logs::run(a).await,
        Commands::Completion(a) => {
            let mut root = Cli::command();
            commands::completion::run(a, &mut root);
            Ok(())
        }
    }
}

#[tokio::main]
async fn main() {
    let code = match dispatch().await {
        Ok(()) => EXIT_OK,
        Err(CliExit(c)) => c,
    };
    std::process::exit(code);
}
