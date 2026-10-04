# SPDX-License-Identifier: GPL-3.0-only
"""``mog source`` —— 书源管理（规划书 §11、§12、§13、§51、§54）。"""

from __future__ import annotations

from pathlib import Path

import typer

from mograb.domain.enums import HealthStatus
from mograb.errors import SourceNotFoundError, SourceSchemaError
from mograb.source import lint, load_cases, load_source_file, run_cases
from mograb.source.fixture import FixtureError

from ._common import command, console, emit, open_app

app = typer.Typer(no_args_is_help=True, help="书源管理")

_HEALTH_MARK = {
    HealthStatus.HEALTHY: "[green]正常[/green]",
    HealthStatus.DEGRADED: "[yellow]部分异常[/yellow]",
    HealthStatus.BROKEN: "[red]已失效[/red]",
    HealthStatus.UNSUPPORTED: "[red]不兼容[/red]",
    HealthStatus.UNKNOWN: "[dim]未检测[/dim]",
}


def _locate_source_file(target: Path) -> Path:
    """用户给目录时自动找里面的 source.yaml。

    **先查存在性再交给 loader** —— loader 对不存在的文件抛的是
    ``SourceSchemaError``，于是 CLI 会打印「Schema 校验失败」，
    而真正的原因是路径写错了。这个提示误导过一次。
    """
    if not target.exists():
        raise typer.BadParameter(f"路径不存在: {target}")

    if target.is_dir():
        candidate = target / "source.yaml"
        if not candidate.is_file():
            raise typer.BadParameter(f"目录里没有 source.yaml: {target}")
        return candidate
    return target


def _not_found(source_id: str) -> SourceNotFoundError:
    return SourceNotFoundError(f"书源未安装: {source_id}", details={"source_id": source_id})


def _resolve_source_file(target: str) -> Path:
    """把参数解析成 source.yaml 的路径。

    **只接受路径，不接受书源 ID。** 快照（``fixtures/``）是开发期产物，
    安装时不会复制到数据目录 —— 否则每个已安装书源都拖着一份会随版本变旧的
    测试数据。所以测试必须在**开发目录**里跑：

        cd my-source && mog source test .

    规划书 §51 里写的是 ``mog source test example``（传 ID），评估报告 P3-02
    也提过参数风格不统一。这里的裁决是「统一成路径」—— 传 ID 时给出明确指引，
    而不是让它去找一份根本不存在的快照。
    """
    as_path = Path(target)
    if not as_path.exists():
        raise typer.BadParameter(
            f"路径不存在: {target}\n"
            "mog source test 只接受书源**目录**或 source.yaml 的路径 ——\n"
            "快照是开发期产物，安装时不会复制到数据目录，所以不能按 ID 测已安装的书源。\n\n"
            "  cd <书源开发目录> && mog source test ."
        )
    return _locate_source_file(as_path)


# ---------------------------------------------------------------------------
# 查看
# ---------------------------------------------------------------------------
@app.command("list")
@command
async def list_sources(
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """列出已安装的书源。"""
    async with open_app() as application:
        entries = await application.sources.list_all()

    emit(
        [
            {
                "id": entry.id,
                "name": entry.spec.name,
                "version": entry.spec.version,
                "capabilities": [c.value for c in entry.spec.capabilities],
                "enabled": entry.enabled,
                "health": entry.health.value,
            }
            for entry in entries
        ],
        json_output=json_output,
    )
    if json_output:
        return

    if not entries:
        console.print("[yellow]还没有安装任何书源[/yellow]")
        console.print("[dim]用 `mog source install <source.yaml>` 装一个[/dim]")
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("名称")
    table.add_column("版本")
    table.add_column("能力")
    table.add_column("状态")

    for entry in entries:
        if not entry.enabled:
            status = "[dim]已禁用[/dim]"
        else:
            status = _HEALTH_MARK.get(entry.health, "?")
        table.add_row(
            entry.id,
            entry.spec.name,
            entry.spec.version,
            ",".join(c.value for c in entry.spec.capabilities),
            status,
        )
    console.print(table)


@app.command("show")
@command
async def show_source(
    source_id: str = typer.Argument(..., help="书源 ID"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """查看书源详情。"""
    async with open_app() as application:
        entry = await application.sources.get(source_id)
        path = application.sources.source_path(source_id)

    if entry is None:
        raise _not_found(source_id)

    emit(
        {
            "id": entry.id,
            "name": entry.spec.name,
            "version": entry.spec.version,
            "homepage": entry.spec.homepage,
            "repository": entry.spec.repository,
            "capabilities": [c.value for c in entry.spec.capabilities],
            "permissions": entry.spec.permissions.model_dump(),
            "enabled": entry.enabled,
            "health": entry.health.value,
            "installed_version": entry.installed_version,
            "previous_version": entry.previous_version,
            "path": str(path),
        },
        json_output=json_output,
    )
    if json_output:
        return

    spec = entry.spec
    console.print(f"[bold]{spec.name}[/bold]  ({spec.id} @ {spec.version})")
    if spec.homepage:
        console.print(f"  主页      {spec.homepage}")
    if spec.repository:
        console.print(f"  项目地址  {spec.repository}")
    if spec.description:
        console.print(f"  说明      {spec.description}")
    console.print(f"  能力      {', '.join(c.value for c in spec.capabilities)}")
    console.print(f"  允许域名  {', '.join(spec.permissions.network) or '（未声明）'}")
    console.print(f"  状态      {_HEALTH_MARK.get(entry.health, '?')}")
    if entry.previous_version:
        # 只作诊断用，**不要**写成「可回滚到 X」——
        # 回滚没有实现，旧版本定义文件也不保留，那样写是给用户错误的安全感。
        console.print(f"  版本变更  {entry.previous_version} → {spec.version}")
    console.print(f"  文件      {path}")
    if spec.repository:
        console.print(f"\n[dim]需要新版就去 {spec.repository} 取，重新 install 即可覆盖[/dim]")


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
@app.command("lint")
def lint_source(
    path: Path = typer.Argument(..., help="书源 YAML 文件或所在目录"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """校验书源（Schema + 语义），不访问网络。

    输出遵循 §11：错误包含位置、字段路径、原因与解决建议。
    """
    try:
        spec = load_source_file(_locate_source_file(path))
        report = lint(spec)
    except SourceSchemaError as exc:
        if json_output:
            emit(exc.to_dict(), json_output=True)
        else:
            console.print("[red]Schema 校验失败[/red]")
            for item in exc.details.get("errors", []):
                location = item.get("path") or "<根>"
                console.print(f"  [red]{location}[/red] {item.get('message')}")
        raise typer.Exit(code=4) from exc

    if json_output:
        emit(report.to_dict(), json_output=True)
    else:
        ready = report.is_ready
        console.print(f"Source: [bold]{report.source_id}[/bold]")
        console.print(f"Schema: {'[green]PASS[/green]' if ready else '[red]FAIL[/red]'}")
        console.print(f"Semantic: {'[green]PASS[/green]' if ready else '[red]FAIL[/red]'}")
        if report.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for diag in report.warnings:
                console.print(f"- {diag.format()}")
        if report.errors:
            console.print("\n[red]Errors:[/red]")
            for diag in report.errors:
                console.print(f"- {diag.format()}")
        console.print(f"\nResult: {'[green]READY[/green]' if ready else '[red]BROKEN[/red]'}")

    if not report.is_ready:
        raise typer.Exit(code=4)


# ---------------------------------------------------------------------------
# 离线测试
# ---------------------------------------------------------------------------
@app.command("test")
@command
async def test_source(
    target: str = typer.Argument(..., help="书源目录或 source.yaml 的路径"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """用离线快照跑一遍书源规则（**不访问网络**）。

    站点改版后规则会失效，但失效点未必是「选择器写错了」——
    更常见的是页面结构变了导致提取到空值。lint 查不出这类问题，
    因为它只看规则本身能不能编译。

    用例写在书源目录的 ``fixtures/cases.yaml``，声明每个能力用哪个快照。
    只接受路径：快照是开发期产物，不随安装复制。
    """
    source_file = _resolve_source_file(target)
    source_dir = source_file.parent
    try:
        spec = load_source_file(source_file)
    except SourceSchemaError as exc:
        console.print("[red]Schema 校验失败[/red]")
        for item in exc.details.get("errors", []):
            console.print(f"  [red]{item.get('path') or '<根>'}[/red] {item.get('message')}")
        raise typer.Exit(code=4) from exc

    report = lint(spec)
    if not report.is_ready:
        console.print("[red]书源未通过校验，先修 lint 错误[/red]")
        for diag in report.errors:
            console.print(f"- {diag.format()}")
        raise typer.Exit(code=4)

    try:
        cases = load_cases(source_dir)
    except FixtureError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=4) from exc

    results = await run_cases(spec, cases, source_dir)

    if json_output:
        emit(
            {
                "source_id": spec.id,
                "total": len(results),
                "passed": sum(1 for r in results if r.ok),
                "failed": sum(1 for r in results if not r.ok),
                "cases": [
                    {
                        "capability": r.capability,
                        "files": r.case.files,
                        "url": r.case.url,
                        "ok": r.ok,
                        "detail": r.summary,
                    }
                    for r in results
                ],
            },
            json_output=True,
        )
    else:
        console.print(f"Source: [bold]{spec.id}[/bold] @ {spec.version}\n")
        for result in results:
            mark = "[green]PASS[/green]" if result.ok else "[red]FAIL[/red]"
            console.print(f"  {mark}  {result.capability:<9} {result.summary}")

        passed = sum(1 for r in results if r.ok)
        console.print(f"\n{passed}/{len(results)} 通过")

    if any(not r.ok for r in results):
        raise typer.Exit(code=4)


# ---------------------------------------------------------------------------
# 安装 / 卸载
# ---------------------------------------------------------------------------
@app.command("install")
@command
async def install_source(
    target: Path = typer.Argument(..., help="书源 YAML 文件或所在目录"),
    force: bool = typer.Option(False, "--force", help="即使有 ERROR 也装"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """安装书源。

    装之前先 lint 一遍。有 ERROR 就拒绝 —— 装一个跑不起来的书源，
    问题要等到真下载时才暴露，那时候更难定位。
    """
    spec = load_source_file(_locate_source_file(target))
    report = lint(spec)

    if not report.is_ready and not force:
        if json_output:
            emit(report.to_dict(), json_output=True)
        else:
            console.print("[red]书源未通过校验，已拒绝安装[/red]")
            for diag in report.errors:
                console.print(f"- {diag.format()}")
            console.print("\n[dim]确实要装的话加 --force[/dim]")
        raise typer.Exit(code=4)

    async with open_app() as application:
        existing = await application.sources.get(spec.id)
        await application.sources.save(spec)
        path = application.sources.source_path(spec.id)

    emit(
        {
            "id": spec.id,
            "version": spec.version,
            "replaced": existing is not None,
            "path": str(path),
            "warnings": [d.message for d in report.warnings],
        },
        json_output=json_output,
    )
    if json_output:
        return

    action = "已更新" if existing else "已安装"
    console.print(f"{action} [bold]{spec.id}[/bold] @ {spec.version}  →  {path}")
    for diag in report.warnings:
        console.print(f"[yellow]警告[/yellow] {diag.message}")


@app.command("remove")
@command
async def remove_source(
    source_id: str = typer.Argument(..., help="书源 ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """卸载书源（连同本地定义文件一起删）。"""
    if not yes:
        typer.confirm(f"确定卸载书源 {source_id} 吗？", abort=True)

    async with open_app() as application:
        removed = await application.sources.delete(source_id)

    if not removed:
        raise _not_found(source_id)
    console.print(f"已卸载 [bold]{source_id}[/bold]")


@app.command("enable")
@command
async def enable_source(source_id: str = typer.Argument(..., help="书源 ID")) -> None:
    """启用书源。"""
    async with open_app() as application:
        await application.sources.set_enabled(source_id, True)
    console.print(f"已启用 [bold]{source_id}[/bold]")


@app.command("disable")
@command
async def disable_source(source_id: str = typer.Argument(..., help="书源 ID")) -> None:
    """禁用书源（保留定义，只是不再被调度）。"""
    async with open_app() as application:
        await application.sources.set_enabled(source_id, False)
    console.print(f"已禁用 [bold]{source_id}[/bold]")


@app.command("rescan")
@command
async def rescan(
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """用磁盘上的定义重建索引。

    手动改过 source.yaml、或者把整个 data 目录拷到另一台机器上时用。
    已存在的书源保留启用状态和体检结果，只更新定义本身。
    """
    async with open_app() as application:
        entries = await application.sources.rescan()

    emit([{"id": e.id, "version": e.spec.version} for e in entries], json_output=json_output)
    if json_output:
        return

    console.print(f"扫描到 [bold]{len(entries)}[/bold] 个书源")
    for entry in entries:
        console.print(f"  {entry.id} @ {entry.spec.version}")


# ---------------------------------------------------------------------------
# 体检
# ---------------------------------------------------------------------------
@app.command("doctor")
@command
async def doctor(
    source_id: str | None = typer.Argument(None, help="书源 ID；省略则检查全部"),
    live: bool = typer.Option(False, "--live", help="额外访问一次主页确认可达"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """书源体检（规划书 §54）。

    默认只做离线检查（定义能否加载、lint 是否通过）。加 ``--live`` 会真的
    访问一次主页 —— 那才说明站点还活着。
    """
    async with open_app() as application:
        if source_id:
            entry = await application.sources.get(source_id)
            if entry is None:
                raise _not_found(source_id)
            entries = [entry]
        else:
            entries = await application.sources.list_all()

        results = []
        for item in entries:
            problems: list[str] = []
            report = lint(item.spec)
            if report.errors:
                problems.append(f"{len(report.errors)} 项校验错误")

            if live and item.spec.homepage:
                try:
                    await application.http.fetch(
                        "GET",
                        item.spec.homepage,
                        source_id=item.id,
                        allowed_domains=item.spec.permissions.network,
                        use_cache=False,
                    )
                except Exception as exc:
                    problems.append(f"主页不可达（{type(exc).__name__}）")

            if not problems:
                health = HealthStatus.HEALTHY
                detail = "离线检查通过" if not live else "离线检查通过，主页可达"
            elif any("校验错误" in p for p in problems):
                health = HealthStatus.BROKEN
                detail = "；".join(problems)
            else:
                health = HealthStatus.DEGRADED
                detail = "；".join(problems)

            await application.sources.set_health(item.id, health)
            results.append({"id": item.id, "health": health.value, "detail": detail})

    emit(results, json_output=json_output)
    if json_output:
        return

    if not results:
        console.print("[yellow]没有已安装的书源[/yellow]")
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("结果")
    table.add_column("说明")
    for item in results:
        table.add_row(
            item["id"], _HEALTH_MARK.get(HealthStatus(item["health"]), "?"), item["detail"]
        )
    console.print(table)


# ---------------------------------------------------------------------------
# 脚手架
# ---------------------------------------------------------------------------
_TEMPLATE = """\
# SPDX-License-Identifier: GPL-3.0-only
#
# MoGrab Source Specification v1
# 规范见 docs/source-spec/source-spec-v1.md
#
# 两个版本字段语义不同：
#   spec_version —— 规范版本，v1 恒为 1
#   version      —— 书源自己的语义化版本

spec_version: 1

id: {source_id}
name: {name}
version: 1.0.0
homepage: https://example.com
# 书源自身的发布地址。填上之后 `mog source show` 会提示用户去这里取新版 ——
# MoGrab 不做远端版本检查（那需要一套分发协议），更新靠用户自己。
repository: null
description: 待补充

capabilities:
  - search
  - book
  - chapters
  - content

network:
  concurrency: 2
  request_interval_ms: 500
  headers:
    User-Agent: "{{{{user_agent}}}}"

permissions:
  network:
    - example.com
  cookies: false
  filesystem: false
  script: false

search:
  request:
    method: GET
    url: https://example.com/search
    query:
      q: "{{{{keyword}}}}"
  result:
    list: ".book-item"
    fields:
      title: ".title"
      author: ".author"
      url: "a@href"

book:
  request:
    method: GET
    url: "{{{{book.url}}}}"
  fields:
    title: "h1"
    author: ".author"
    intro: ".intro"

chapters:
  request:
    method: GET
    url: "{{{{book.url}}}}"
  result:
    list: ".chapter-list a"
    fields:
      title: "@text"
      url: "@href"

content:
  request:
    method: GET
    url: "{{{{chapter.url}}}}"
  body: "#content"
  clean:
    remove:
      - "script"
      - "style"
"""


@app.command("init")
def init_source(
    name: str = typer.Argument(..., help="新书源目录名，同时也是书源 ID"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="建在哪个目录下"),
) -> None:
    """生成书源脚手架（规划书 §51）。"""
    from mograb.domain.source import SOURCE_ID_RE

    if not SOURCE_ID_RE.match(name):
        console.print("[red]ID 不合法[/red]：要求小写字母开头，只含 a-z0-9 与 - _")
        raise typer.Exit(code=2)

    target = directory / name
    if target.exists():
        console.print(f"[red]目录已存在[/red] {target}")
        raise typer.Exit(code=1)

    (target / "fixtures").mkdir(parents=True)
    (target / "source.yaml").write_text(
        _TEMPLATE.format(source_id=name, name=name.replace("-", " ").title()),
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {name}\n\n书源说明：站点、支持的能力、已知限制。\n",
        encoding="utf-8",
    )

    console.print(f"已生成 [bold]{target}[/bold]")
    console.print(f"[dim]接着改 source.yaml，然后 `mog source lint {target / 'source.yaml'}`[/dim]")


__all__ = ["app"]
