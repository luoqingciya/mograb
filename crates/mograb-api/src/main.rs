// SPDX-License-Identifier: GPL-3.0-only
//! `mograb-api` 二进制入口。

#[tokio::main]
async fn main() {
    if let Err(err) = mograb_api::serve(None, None).await {
        eprintln!("[{}] {}", err.code(), err.message());
        std::process::exit(1);
    }
}
