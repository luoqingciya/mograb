# SPDX-License-Identifier: GPL-3.0-only
"""``mog server`` —— 本地 API Server 控制（规划书 §34）。

CLI 不 import ``mograb_api`` —— 两个应用是兄弟，直接依赖会把它们绑死。
这里用子进程拉起 server：打包后是同目录下的 ``mograb-api``，
开发时是当前解释器跑 ``-m mograb_api``。这也正是 Desktop 用 sidecar 的方式。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import typer

from mograb.config import ensure_token, get_paths, load_settings

from ._common import console, emit

app = typer.Typer(no_args_is_help=True, help="本地 API Server")

PID_FILENAME = "server.pid"
STARTUP_TIMEOUT_SECONDS = 15.0


def _pid_file() -> Path:
    return get_paths().root / PID_FILENAME


def _api_command() -> list[str]:
    """找到 API server 的启动命令。"""
    exe_dir = Path(sys.executable).resolve().parent
    for name in ("mograb-api.exe", "mograb-api"):
        candidate = exe_dir / name
        if candidate.is_file():
            return [str(candidate)]
    return [sys.executable, "-m", "mograb_api"]


def _read_pid() -> int | None:
    path = _pid_file()
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _process_alive(pid: int) -> bool:
    """进程还在不在。

    ``os.kill(pid, 0)`` 在 Windows 上不适用，用 ``tasklist`` 更可靠。
    这里只在 POSIX 上用信号探测，Windows 走 tasklist。
    """
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@app.command("start")
def start(
    host: str | None = typer.Option(None, "--host", help="监听地址"),
    port: int | None = typer.Option(None, "--port", "-p", help="监听端口"),
    background: bool = typer.Option(
        False, "--background", "-b", help="后台运行（默认前台，Ctrl+C 停止）"
    ),
) -> None:
    """启动本地 API Server。

    默认只监听 ``127.0.0.1``（§40）。前台运行方便看日志；
    要让 Desktop 或 ``mog task`` 连上，用 ``--background``。
    """
    settings = load_settings()
    listen_host = host or settings.server.host
    listen_port = port or settings.server.port

    if is_running_sync(listen_host, listen_port):
        console.print(f"[yellow]已经有一个 server 在 {listen_host}:{listen_port} 上跑着[/yellow]")
        raise typer.Exit(code=1)

    command = _api_command()
    env = {
        **os.environ,
        "MOGRAB_SERVER__HOST": listen_host,
        "MOGRAB_SERVER__PORT": str(listen_port),
    }

    if not background:
        console.print(f"启动 API Server: {listen_host}:{listen_port}（Ctrl+C 停止）")
        try:
            subprocess.run(command, env=env, check=False)
        except KeyboardInterrupt:
            console.print("\n已停止")
        return

    creationflags = 0
    if os.name == "nt":
        # 脱离当前控制台，父进程退出后继续活着
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    _pid_file().write_text(str(process.pid), encoding="utf-8")

    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if is_running_sync(listen_host, listen_port):
            console.print(
                f"已启动 [bold]http://{listen_host}:{listen_port}[/bold]（pid {process.pid}）"
            )
            console.print(
                "[dim]接口需要令牌，`mog server token` 可以打印出来；"
                "CLI 和 Desktop 会自己读，不用手填[/dim]"
            )
            return
        if process.poll() is not None:
            console.print(f"[red]server 启动失败[/red]，退出码 {process.returncode}")
            _pid_file().unlink(missing_ok=True)
            raise typer.Exit(code=1)
        time.sleep(0.3)

    console.print("[red]等待 server 就绪超时[/red]，进程可能还在启动，用 `mog server status` 看看")
    raise typer.Exit(code=1)


def is_running_sync(host: str, port: int) -> bool:
    """同步版健康检查 —— 命令是同步函数，不值得为这个起事件循环。"""
    import httpx

    try:
        response = httpx.get(f"http://{host}:{port}/health", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@app.command("status")
def status(json_output: bool = typer.Option(False, "--json", help="以 JSON 输出")) -> None:
    """查看 Server 运行状态。"""
    settings = load_settings()
    running = is_running_sync(settings.server.host, settings.server.port)
    pid = _read_pid()

    emit(
        {
            "running": running,
            "host": settings.server.host,
            "port": settings.server.port,
            "pid": pid if running else None,
        },
        json_output=json_output,
    )
    if json_output:
        return

    if running:
        console.print(
            f"[green]运行中[/green] http://{settings.server.host}:{settings.server.port}"
            + (f"（pid {pid}）" if pid else "")
        )
    else:
        console.print("[dim]未运行[/dim]")


@app.command("stop")
def stop() -> None:
    """停止由 ``mog server start --background`` 启动的 server。"""
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]没有记录到 server 进程[/yellow]")
        console.print("[dim]只有 --background 启动的 server 才会写 pid 文件[/dim]")
        raise typer.Exit(code=1)

    if not _process_alive(pid):
        console.print(f"[dim]进程 {pid} 已经不在了，清理 pid 文件[/dim]")
        _pid_file().unlink(missing_ok=True)
        raise typer.Exit(code=1)

    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        console.print(f"[red]停止失败[/red] {exc}")
        raise typer.Exit(code=1) from exc

    _pid_file().unlink(missing_ok=True)
    console.print(f"已停止（pid {pid}）")


@app.command("token")
def token(
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """打印 API 访问令牌。

    CLI 和 Desktop 自己会读，这个命令是给手工调接口用的（curl、Swagger UI、
    脚本）。**别把输出贴到公开的地方** —— 拿到令牌就等于拿到这个 API 的全部权限。
    """
    paths = get_paths()
    value = ensure_token(paths)

    emit({"token": value, "path": str(paths.token_file)}, json_output=json_output)
    if json_output:
        return

    console.print(value)
    console.print(f"[dim]{paths.token_file}[/dim]")


__all__ = ["app"]
