# SPDX-License-Identifier: GPL-3.0-only
"""CLI 集成测试。

用 Typer 的 CliRunner 跑真实命令。全部离线 —— 数据目录由 conftest 的
autouse fixture 指到临时目录，不会碰到仓库或用户数据。

只覆盖不需要网络的部分：书源管理、配置、缓存、任务查询。
下载和搜索要真实站点，交给 fixture 测试去验证。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mograb.config import get_paths, read_token
from mograb_cli.main import app

pytestmark = pytest.mark.integration

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, list(args))


@pytest.fixture
def example_yaml(example_source_dir: Path) -> str:
    return str(example_source_dir / "source.yaml")


class TestSourceCommands:
    def test_list_when_empty(self) -> None:
        result = run("source", "list")
        assert result.exit_code == 0
        assert "还没有安装任何书源" in result.stdout

    def test_list_json_when_empty(self) -> None:
        result = run("source", "list", "--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == []

    def test_install_then_list(self, example_yaml: str) -> None:
        installed = run("source", "install", example_yaml)
        assert installed.exit_code == 0, installed.stdout
        assert "已安装" in installed.stdout

        listed = run("source", "list")
        assert "example" in listed.stdout

    def test_install_twice_reports_update(self, example_yaml: str) -> None:
        run("source", "install", example_yaml)
        again = run("source", "install", example_yaml)
        assert again.exit_code == 0
        assert "已更新" in again.stdout

    def test_install_rejects_lint_errors(self, tmp_path: Path) -> None:
        """Schema 合法但 lint 有 ERROR 的书源要被挡下来。"""
        broken = tmp_path / "lint-error.yaml"
        broken.write_text(
            "spec_version: 1\n"
            "id: demo\n"
            "name: Demo\n"
            "version: 1.0.0\n"
            "capabilities: [search]\n"
            "search:\n"
            "  request:\n"
            "    method: GET\n"
            "    url: 'https://demo.example.com/s?q={{nope}}'\n"
            "  result:\n"
            "    list: '.item'\n"
            "    fields: {title: '.t', url: 'a@href'}\n",
            encoding="utf-8",
        )

        result = run("source", "install", str(broken))
        assert result.exit_code == 4
        assert "拒绝安装" in result.stdout

    def test_install_force_overrides_lint_errors(self, tmp_path: Path) -> None:
        broken = tmp_path / "lint-error.yaml"
        broken.write_text(
            "spec_version: 1\n"
            "id: demo\n"
            "name: Demo\n"
            "version: 1.0.0\n"
            "capabilities: [search]\n"
            "search:\n"
            "  request:\n"
            "    method: GET\n"
            "    url: 'https://demo.example.com/s?q={{nope}}'\n"
            "  result:\n"
            "    list: '.item'\n"
            "    fields: {title: '.t', url: 'a@href'}\n",
            encoding="utf-8",
        )

        result = run("source", "install", str(broken), "--force")
        assert result.exit_code == 0, result.stdout

    def test_install_rejects_schema_errors(self, tmp_path: Path) -> None:
        """Schema 就不合法的文件，--force 也不该放行 —— 它压根不是一份书源。"""
        broken = tmp_path / "bad.yaml"
        broken.write_text("spec_version: 1\nid: Bad_ID\n", encoding="utf-8")

        assert run("source", "install", str(broken)).exit_code == 4
        assert run("source", "install", str(broken), "--force").exit_code == 4

    def test_show(self, example_yaml: str) -> None:
        run("source", "install", example_yaml)
        result = run("source", "show", "example")
        assert result.exit_code == 0
        assert "Example" in result.stdout
        assert "example.com" in result.stdout

    def test_show_missing(self) -> None:
        result = run("source", "show", "nope")
        assert result.exit_code == 3

    def test_disable_and_enable(self, example_yaml: str) -> None:
        run("source", "install", example_yaml)

        assert run("source", "disable", "example").exit_code == 0
        disabled = run("source", "list", "--json")
        assert json.loads(disabled.stdout)[0]["enabled"] is False

        assert run("source", "enable", "example").exit_code == 0
        enabled = run("source", "list", "--json")
        assert json.loads(enabled.stdout)[0]["enabled"] is True

    def test_remove(self, example_yaml: str) -> None:
        run("source", "install", example_yaml)
        result = run("source", "remove", "example", "--yes")
        assert result.exit_code == 0
        assert json.loads(run("source", "list", "--json").stdout) == []

    def test_remove_missing(self) -> None:
        assert run("source", "remove", "nope", "--yes").exit_code == 3

    def test_rescan_after_hand_drop(self, example_yaml: str, monkeypatch) -> None:
        """模拟「换机器只拷了 sources 目录」：清库再扫描。"""
        run("source", "install", example_yaml)

        import os

        home = Path(os.environ["MOGRAB_HOME"])
        (home / "mograb.db").unlink()

        result = run("source", "rescan")
        assert result.exit_code == 0
        assert "扫描到 1 个书源" in result.stdout

    def test_doctor_offline(self, example_yaml: str) -> None:
        run("source", "install", example_yaml)
        result = run("source", "doctor")
        assert result.exit_code == 0
        assert "正常" in result.stdout

    def test_init_scaffold(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = run("source", "init", "my-source")
        assert result.exit_code == 0

        target = tmp_path / "my-source"
        assert (target / "source.yaml").is_file()
        assert (target / "README.md").is_file()
        assert (target / "fixtures").is_dir()

        # 生成的模板本身要能通过校验
        linted = run("source", "lint", str(target / "source.yaml"))
        assert linted.exit_code == 0, linted.stdout

    def test_init_rejects_bad_id(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert run("source", "init", "Bad-Name").exit_code == 2


class TestSourceLint:
    def test_lint_ok(self, example_yaml: str) -> None:
        result = run("source", "lint", example_yaml)
        assert result.exit_code == 0
        assert "READY" in result.stdout

    def test_lint_broken_returns_4(self, tmp_path: Path) -> None:
        broken = tmp_path / "bad.yaml"
        broken.write_text("spec_version: 1\nid: demo\n", encoding="utf-8")

        result = run("source", "lint", str(broken))
        assert result.exit_code == 4

    def test_lint_json(self, example_yaml: str) -> None:
        result = run("source", "lint", example_yaml, "--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout)["result"] == "READY"

    def test_lint_missing_file(self, tmp_path: Path) -> None:
        assert run("source", "lint", str(tmp_path / "nope.yaml")).exit_code == 4


class TestConfigCommands:
    def test_path(self) -> None:
        result = run("config", "path")
        assert result.exit_code == 0
        assert "data" in result.stdout

    def test_path_json(self) -> None:
        result = run("config", "path", "--json")
        data = json.loads(result.stdout)
        assert "runtime" in data
        assert "database" in data

    def test_show_json(self) -> None:
        result = run("config", "show", "--json")
        data = json.loads(result.stdout)
        assert data["server"]["host"] == "127.0.0.1"
        assert data["cache"]["max_size_bytes"] == 5 * 1024**3

    def test_init_writes_file(self) -> None:
        import os

        result = run("config", "init")
        assert result.exit_code == 0
        assert (Path(os.environ["MOGRAB_HOME"]) / "config.toml").is_file()


class TestCacheCommands:
    def test_stats(self) -> None:
        result = run("cache", "stats")
        assert result.exit_code == 0
        assert "条目数" in result.stdout

    def test_stats_json(self) -> None:
        data = json.loads(run("cache", "stats", "--json").stdout)
        assert data["entries"] == 0

    def test_clear(self) -> None:
        assert run("cache", "clear", "--yes").exit_code == 0

    def test_clear_source(self) -> None:
        assert run("cache", "clear-source", "example").exit_code == 0


class TestTaskCommands:
    def test_list_empty(self) -> None:
        result = run("task", "list")
        assert result.exit_code == 0
        assert "没有任务" in result.stdout

    def test_list_empty_json(self) -> None:
        assert json.loads(run("task", "list", "--json").stdout) == []

    def test_show_missing(self) -> None:
        assert run("task", "show", "nope").exit_code == 3

    def test_bad_status_filter(self) -> None:
        assert run("task", "list", "--status", "nonsense").exit_code != 0

    def test_pause_without_server_explains(self) -> None:
        """没有 server 时要给人话，不是堆栈。"""
        result = run("task", "pause", "whatever")
        assert result.exit_code == 1
        assert "没在运行" in result.stdout

    def test_unauthorized_explains(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """令牌对不上也要给人话 —— 正常不会发生，但真撞上要能自己查。"""
        from mograb_cli.commands import task as task_module
        from mograb_cli.commands._api import ApiUnauthorized

        async def fake_request(*args: object, **kwargs: object) -> object:
            raise ApiUnauthorized("unauthorized")

        monkeypatch.setattr(task_module, "request", fake_request)

        result = run("task", "pause", "whatever")

        assert result.exit_code == 1
        assert "令牌" in result.stdout


class TestServerCommands:
    def test_status_when_down(self) -> None:
        result = run("server", "status")
        assert result.exit_code == 0
        assert "未运行" in result.stdout

    def test_status_json(self) -> None:
        data = json.loads(run("server", "status", "--json").stdout)
        assert data["running"] is False


class TestServerToken:
    """``mog server token`` —— 给手工调接口用的。"""

    def test_prints_token(self) -> None:
        result = run("server", "token")

        assert result.exit_code == 0
        lines = result.stdout.strip().splitlines()
        assert len(lines[0]) == 43

    def test_matches_file(self) -> None:
        """打印出来的必须就是文件里那份 —— 不然手工调接口会 401。"""
        printed = run("server", "token").stdout.strip().splitlines()[0]

        assert read_token(get_paths()) == printed

    def test_json_shape(self) -> None:
        data = json.loads(run("server", "token", "--json").stdout)

        assert set(data) == {"token", "path"}
        assert Path(data["path"]) == get_paths().token_file

    def test_is_stable_across_calls(self) -> None:
        first = run("server", "token").stdout.strip().splitlines()[0]
        second = run("server", "token").stdout.strip().splitlines()[0]

        assert first == second


class TestTopLevel:
    def test_version(self) -> None:
        result = run("--version")
        assert result.exit_code == 0
        assert "MoGrab" in result.stdout

    def test_help_lists_commands(self) -> None:
        result = run("--help")
        assert result.exit_code == 0
        for name in ("source", "search", "download", "task", "cache", "config", "server"):
            assert name in result.stdout


def _seed_chapter() -> None:
    """往库里塞一本书 + 一章正文。

    免得为了测搜索真跑一遍下载 —— ``mog find`` 要验的是查询，不是抓取。
    """
    from datetime import UTC, datetime

    from mograb.app import create_application
    from mograb.domain.book import Book
    from mograb.domain.chapter import Chapter

    async def go() -> None:
        async with create_application() as app:
            now = datetime(2026, 1, 1, tzinfo=UTC)
            await app.books.save(
                Book(
                    id="book_t",
                    source_id="example",
                    source_book_id="1001",
                    url="https://example.com/book/1001",
                    title="三体",
                    created_at=now,
                    updated_at=now,
                )
            )
            await app.chapters.save(
                Chapter(
                    id="chap_t",
                    book_id="book_t",
                    title="第一章 科学边界",
                    url="https://example.com/1",
                    index=0,
                    content="汪淼接到一个差事，要去看看鲜荔枝。",
                    created_at=now,
                    updated_at=now,
                )
            )

    asyncio.run(go())


class TestFindCommand:
    """``mog find`` —— 在已下载的章节正文里搜。**纯本地，不访问网络。**"""

    @pytest.fixture
    def seeded(self, example_yaml: str) -> None:
        assert run("source", "install", example_yaml).exit_code == 0
        _seed_chapter()

    def test_空库时给人话(self) -> None:
        result = run("find", "荔枝")

        assert result.exit_code == 0
        assert "没有匹配" in result.stdout

    def test_命中并显示书名章节(self, seeded: None) -> None:
        result = run("find", "荔枝")

        assert result.exit_code == 0
        assert "命中" in result.stdout
        assert "三体" in result.stdout
        assert "第一章 科学边界" in result.stdout

    def test_未命中(self, seeded: None) -> None:
        result = run("find", "这个词肯定不存在")

        assert result.exit_code == 0
        assert "没有匹配" in result.stdout

    def test_json_输出(self, seeded: None) -> None:
        data = json.loads(run("find", "荔枝", "--json").stdout)

        assert data["keyword"] == "荔枝"
        assert data["count"] == 1
        assert data["hits"][0]["book_title"] == "三体"
        assert "荔枝" in data["hits"][0]["snippet"]

    def test_限定书籍(self, seeded: None) -> None:
        assert json.loads(run("find", "荔枝", "--book", "book_t", "--json").stdout)["count"] == 1
        assert json.loads(run("find", "荔枝", "--book", "nope", "--json").stdout)["count"] == 0

    def test_缺关键词是参数错误(self) -> None:
        assert run("find").exit_code != 0
