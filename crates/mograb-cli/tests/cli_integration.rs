// SPDX-License-Identifier: GPL-3.0-only
//! `mog` CLI 端到端集成测试。

use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use tempfile::TempDir;

fn mog_bin() -> &'static str {
    env!("CARGO_BIN_EXE_mog")
}

fn example_source_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/example-source")
}

fn run_mog(home: &Path, args: &[&str]) -> Output {
    Command::new(mog_bin())
        .args(args)
        .env("MOGRAB_HOME", home)
        .output()
        .expect("spawn mog")
}

fn parse_json_stdout(out: &Output) -> Value {
    let s = String::from_utf8(out.stdout.clone()).expect("UTF-8 stdout");
    serde_json::from_str(&s).unwrap_or_else(|e| panic!("invalid JSON stdout ({e}): {s}"))
}

#[test]
fn test_version_and_help() {
    let dir = TempDir::new().unwrap();

    let v = run_mog(dir.path(), &["--version"]);
    assert_eq!(v.status.code(), Some(0));
    let vs = String::from_utf8(v.stdout).unwrap();
    assert_eq!(
        vs.trim(),
        format!("mog (MoGrab) {}", env!("CARGO_PKG_VERSION"))
    );

    let h = run_mog(dir.path(), &["--help"]);
    assert_eq!(h.status.code(), Some(0));
    let hs = String::from_utf8(h.stdout).unwrap();
    assert!(hs.contains("init"));
    assert!(hs.contains("source"));
    assert!(hs.contains("download"));
    assert!(hs.contains("server"));
}

#[test]
fn test_init_and_config_commands() {
    let dir = TempDir::new().unwrap();

    let init_out = run_mog(dir.path(), &["init", "--json"]);
    assert_eq!(
        init_out.status.code(),
        Some(0),
        "stderr: {}",
        String::from_utf8_lossy(&init_out.stderr)
    );
    let init_json = parse_json_stdout(&init_out);
    assert!(Path::new(init_json["config"].as_str().unwrap()).is_file());
    assert!(Path::new(init_json["database"].as_str().unwrap()).is_file());

    let path_out = run_mog(dir.path(), &["config", "path", "--json"]);
    assert_eq!(path_out.status.code(), Some(0));
    let path_json = parse_json_stdout(&path_out);
    assert_eq!(
        path_json["data"].as_str().unwrap(),
        dir.path().to_str().unwrap()
    );

    let init_cfg = run_mog(dir.path(), &["config", "init", "--force"]);
    assert_eq!(init_cfg.status.code(), Some(0));

    let show_cfg = run_mog(dir.path(), &["config", "show", "--json"]);
    assert_eq!(show_cfg.status.code(), Some(0));
    let cfg_json = parse_json_stdout(&show_cfg);
    assert!(cfg_json["cache"]["max_size_bytes"].as_u64().unwrap() > 0);
}

#[test]
fn test_source_lint_test_install_and_manage() {
    let dir = TempDir::new().unwrap();
    let example = example_source_dir();
    let example_str = example.to_str().unwrap();

    // 1. lint valid example-source
    let lint_ok = run_mog(dir.path(), &["source", "lint", example_str, "--json"]);
    assert_eq!(lint_ok.status.code(), Some(0));
    let lint_json = parse_json_stdout(&lint_ok);
    assert_eq!(lint_json["schema"], "PASS");
    assert_eq!(lint_json["result"], "READY");

    // 2. lint invalid source -> exit code 4
    let bad_dir = TempDir::new().unwrap();
    let bad_file = bad_dir.path().join("source.yaml");
    fs::write(&bad_file, "id: INVALID_ID\nname: broken\n").unwrap();
    let lint_bad = run_mog(
        dir.path(),
        &["source", "lint", bad_file.to_str().unwrap(), "--json"],
    );
    assert_eq!(lint_bad.status.code(), Some(4));

    // 3. test example-source offline fixtures
    let test_out = run_mog(dir.path(), &["source", "test", example_str, "--json"]);
    assert_eq!(
        test_out.status.code(),
        Some(0),
        "stdout: {}\nstderr: {}",
        String::from_utf8_lossy(&test_out.stdout),
        String::from_utf8_lossy(&test_out.stderr)
    );
    let test_json = parse_json_stdout(&test_out);
    assert_eq!(test_json["ok"], true);
    assert_eq!(test_json["cases"].as_array().unwrap().len(), 4);

    // 4. install / list / show / disable / enable / remove
    let inst = run_mog(dir.path(), &["source", "install", example_str, "--json"]);
    assert_eq!(inst.status.code(), Some(0));

    let list = run_mog(dir.path(), &["source", "list", "--json"]);
    assert_eq!(list.status.code(), Some(0));
    let list_json = parse_json_stdout(&list);
    assert_eq!(list_json.as_array().unwrap().len(), 1);
    assert_eq!(list_json[0]["id"], "example");

    let show = run_mog(dir.path(), &["source", "show", "example", "--json"]);
    assert_eq!(show.status.code(), Some(0));

    assert_eq!(
        run_mog(dir.path(), &["source", "disable", "example"])
            .status
            .code(),
        Some(0)
    );
    assert_eq!(
        run_mog(dir.path(), &["source", "enable", "example"])
            .status
            .code(),
        Some(0)
    );
    assert_eq!(
        run_mog(dir.path(), &["source", "remove", "example", "-y"])
            .status
            .code(),
        Some(0)
    );

    // 5. show missing source -> exit code 3
    let missing_src = run_mog(dir.path(), &["source", "show", "nope", "--json"]);
    assert_eq!(missing_src.status.code(), Some(3));

    // 6. source init scaffold + lint
    let scaffold_parent = TempDir::new().unwrap();
    let init_src = run_mog(
        dir.path(),
        &[
            "source",
            "init",
            "demo_src",
            "-d",
            scaffold_parent.path().to_str().unwrap(),
        ],
    );
    assert_eq!(init_src.status.code(), Some(0));
    let lint_scaffold = run_mog(
        dir.path(),
        &[
            "source",
            "lint",
            scaffold_parent.path().join("demo_src").to_str().unwrap(),
        ],
    );
    assert_eq!(lint_scaffold.status.code(), Some(0));
}

#[test]
fn test_book_find_cache_server_and_exit_codes() {
    let dir = TempDir::new().unwrap();

    // 空书架
    let books = run_mog(dir.path(), &["book", "--json"]);
    assert_eq!(books.status.code(), Some(0));
    assert_eq!(parse_json_stdout(&books).as_array().unwrap().len(), 0);

    // 查询不存在书籍 -> exit code 3
    let missing_book = run_mog(dir.path(), &["book", "book_missing", "--json"]);
    assert_eq!(missing_book.status.code(), Some(3));

    // --chapters 与 --chapter 冲突 -> exit code 2
    let conflict = run_mog(
        dir.path(),
        &["book", "book_1", "-c", "--chapter", "1", "--json"],
    );
    assert_eq!(conflict.status.code(), Some(2));

    // find 支持中文 UTF-8 JSON 输出
    let find_out = run_mog(dir.path(), &["find", "中文关键词", "--json"]);
    assert_eq!(find_out.status.code(), Some(0));
    let find_json = parse_json_stdout(&find_out);
    assert_eq!(find_json["keyword"], "中文关键词");
    assert_eq!(find_json["count"], 0);

    // cache stats / clear
    let stats = run_mog(dir.path(), &["cache", "stats", "--json"]);
    assert_eq!(stats.status.code(), Some(0));
    let clear = run_mog(dir.path(), &["cache", "clear", "-y"]);
    assert_eq!(clear.status.code(), Some(0));

    // server token / status
    let tok = run_mog(dir.path(), &["server", "token", "--json"]);
    assert_eq!(tok.status.code(), Some(0));
    let tok_json = parse_json_stdout(&tok);
    assert!(!tok_json["token"].as_str().unwrap().is_empty());

    let st = run_mog(dir.path(), &["server", "status", "--json"]);
    assert_eq!(st.status.code(), Some(0));
    let st_json = parse_json_stdout(&st);
    assert_eq!(st_json["running"], false);
}
