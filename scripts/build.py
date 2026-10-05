# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab 构建脚本（规划书 §57.2、§57.3）。

用法::

    python scripts/build.py cli      --version 0.1.0    # 构建 CLI（PyInstaller onedir）
    python scripts/build.py backend  --version 0.1.0    # 构建 Desktop 后端 sidecar
    python scripts/build.py clean                        # 清理产物

设计约束（§57.2）：

- 使用 PyInstaller **onedir**，**不追求单文件 EXE**。
- 最终产物**不包含** uv / 开发环境。
- 用户解压后即可运行，无需安装 Python。
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from _console import force_utf8_stdio

force_utf8_stdio()

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "release-artifacts"
BUILD_DIR = REPO_ROOT / "build"

ICON = REPO_ROOT / "assets" / "icon.ico"

# 首次运行时必须建出来的数据子目录。
#
# **刻意不 import `mograb.config.paths._SUBDIRS`** —— 冒烟测试要验的是「产物的
# 行为符合预期」，预期得独立于被测代码才有效力。代价是会漂，所以
# `tests/unit/test_build_script.py` 有一条测试盯着它和 `_SUBDIRS` 保持同步
# （删掉 `data/cache/` 时就漂过一次，冒烟测试当场拦下来了）。
EXPECTED_DATA_SUBDIRS = ("covers", "logs", "exports", "sources")
"""Windows exe 图标。由 ``scripts/make_icon.py`` 生成，改了配色/几何要重新跑一遍。"""

# 各目标产物配置
#
# entry 用 scripts/ 下的专用入口，而不是包的 __main__.py —— 后者是相对导入，
# 被 PyInstaller 当独立脚本跑时会失败。
#
# paths 显式给出源码目录：包是以 editable 方式装的，PyInstaller 未必能顺着
# editable finder 找到源码，直接指路径更可靠。
TARGETS = {
    "cli": {
        "entry": REPO_ROOT / "scripts" / "entry_cli.py",
        "name": "mog",
        "out": ARTIFACTS / "MoGrab-CLI",
        "paths": [
            REPO_ROOT / "apps" / "cli" / "src",
            REPO_ROOT / "packages" / "mograb" / "src",
        ],
        "metadata": ["mograb", "mograb-cli"],
    },
    "backend": {
        "entry": REPO_ROOT / "scripts" / "entry_api.py",
        "name": "mograb-api",
        "out": ARTIFACTS / "backend",
        "paths": [
            REPO_ROOT / "apps" / "api" / "src",
            REPO_ROOT / "packages" / "mograb" / "src",
        ],
        "metadata": ["mograb", "mograb-api"],
    },
}

# 需要排除的模块（减小体积、避免误打包）
EXCLUDES = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "IPython",
    "pytest",
    "pyright",
    "ruff",
]

# 动态导入、PyInstaller 静态分析发现不了的模块
# 有「按名字动态导入子模块」的包，**整包收集**。
#
# 为什么不逐个列 `--hidden-import`：那要猜包内部会导入什么，猜漏一次就是
# 一个只有用户能撞见的崩溃。已经栽过两次 ——
#
#   - `aiosqlite`：SQLAlchemy 按字符串导入驱动包（rc1 的产物打不开数据库）
#   - `shellingham.nt`：Typer 的补全探测按
#     `importlib.import_module(".{}".format(os.name))` 导入平台实现
#     （rc3 的产物 `--install-completion` 直接崩）
#
# 这两个包都很小，整包带上的代价可以忽略。
COLLECT_SUBMODULES = [
    "shellingham",
    "aiosqlite",
]

HIDDEN_IMPORTS = [
    # SQLAlchemy 的 dialect 是按名字动态加载的。
    # 下面这两条只解决 dialect **适配器**；真正的 DBAPI **驱动包**
    # 见上面的 COLLECT_SUBMODULES。
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    # uvicorn 的运行期依赖
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]


def verify_metadata_version(packages: list[str], expected: str) -> None:
    """确认已安装包的元数据版本和要构建的版本一致。

    editable 安装的元数据是**缓存**的：改了 ``VERSION`` 之后 ``uv sync``
    不会重装，dist-info 里还是旧版本号。而 PyInstaller 用 ``--copy-metadata``
    把那份元数据拷进产物，于是打出来的 exe 报一个错误的版本 ——
    而且只有跑起来才发现。

    CI 是全新环境所以碰不到，本地反复构建时很容易踩。
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    for name in packages:
        try:
            installed = dist_version(name)
        except PackageNotFoundError:
            raise SystemExit(f"未安装 {name}。先跑 uv sync --all-packages --group build") from None
        if installed != expected:
            reinstalls = " ".join(f"--reinstall-package {p}" for p in packages)
            raise SystemExit(
                f"{name} 的元数据版本是 {installed}，与要构建的 {expected} 不一致。\n"
                "editable 安装的元数据不会跟着 VERSION 文件更新，强制重装一次：\n"
                f"  uv sync --all-packages --group build {reinstalls}"
            )


def build(target: str, version: str) -> Path:
    """构建指定目标。"""
    if target not in TARGETS:
        raise SystemExit(f"未知构建目标: {target}（可选: {', '.join(TARGETS)}）")

    cfg = TARGETS[target]
    entry: Path = cfg["entry"]
    out_dir: Path = cfg["out"]

    if not entry.is_file():
        raise SystemExit(f"入口文件不存在: {entry}")

    # 版本号是运行时从元数据读的，所以构建前必须先对齐 ——
    # 不对齐的话产物里的版本号是错的，而且不报错。
    verify_metadata_version(list(cfg["metadata"]), version)

    print(f"[build] 目标={target} 版本={version}")
    print(f"[build] 入口={entry}")
    print(f"[build] 输出={out_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",  # §57.2：目录型产物，非单文件
        "--name",
        str(cfg["name"]),
        "--distpath",
        str(out_dir),
        "--workpath",
        str(BUILD_DIR / target),
        "--specpath",
        str(BUILD_DIR),
        "--console",
    ]
    for module in EXCLUDES:
        args += ["--exclude-module", module]
    for module in HIDDEN_IMPORTS:
        args += ["--hidden-import", module]
    for package in COLLECT_SUBMODULES:
        args += ["--collect-submodules", package]
    for source_path in cfg["paths"]:
        args += ["--paths", str(source_path)]
    # 把 dist-info 元数据一起打进去。版本号是运行时从
    # importlib.metadata 读的，不复制元数据的话会退化成 0.0.0+unknown。
    for dist in cfg["metadata"]:
        args += ["--copy-metadata", dist]
    # 图标只在 Windows 上有意义 —— .ico 是 Windows 的资源格式。
    #
    # 不传 --icon 时 PyInstaller **不会报错**，它会塞一个自己的默认图标，
    # 产物照样能跑，只是任务栏上不是我们的图标。所以漏接是完全静默的，
    # 后面 smoke 里专门核对了尺寸集合。
    if os.name == "nt":
        if not ICON.is_file():
            raise SystemExit(
                f"找不到图标 {ICON}。先生成一次：\n  uv run python scripts/make_icon.py"
            )
        args += ["--icon", str(ICON)]
    args.append(str(entry))

    subprocess.run(args, check=True, cwd=REPO_ROOT)

    flatten_dist(out_dir, str(cfg["name"]))
    strip_runtime_data(out_dir)

    print(f"[build] 完成: {out_dir}")
    return out_dir


def strip_runtime_data(out_dir: Path) -> None:
    """删掉产物目录里的 ``data/`` —— 那是运行期数据，不属于构建产物。

    程序跑起来会在可执行文件旁边建 ``data/``（数据库、缓存、**API 令牌**）。
    只要有人在打包前跑过一次这个 exe，这份数据就会被原样打进发布包 ——
    而 ``data/token`` 是访问令牌，**所有装这个包的用户会共用同一个**。

    构建产物里出现 ``data/`` 永远不是正常的，所以这里直接删掉，
    并且把话说清楚（CI 里出现这行日志就说明有人提前跑了 exe）。
    """
    data_dir = out_dir / "data"
    if not data_dir.is_dir():
        return

    print(
        f"[build] 警告：产物目录里发现运行期数据 {data_dir}，已删除。\n"
        "[build]       构建前不该运行这个可执行文件 —— 里面的 data/token 是"
        "访问令牌，打进去会让所有用户共用一个。",
        file=sys.stderr,
    )
    shutil.rmtree(data_dir)


def flatten_dist(out_dir: Path, name: str) -> None:
    """把 PyInstaller 多套的那层目录拍平。

    PyInstaller 的 onedir 产物固定是 ``<distpath>/<name>/...``，
    拍平之后可执行文件直接落在 ``out_dir`` 下，打包出来的 ZIP 里顶层就是
    ``MoGrab-CLI/``，不会多一层 ``mog/``。

    注意 Linux：可执行文件名和目录名都叫 ``mog``，逐个搬的话第一个就撞上自己
    （目标路径正是 nested 本身）。所以先把整层挪到临时目录再搬。
    """
    nested = out_dir / name
    if not nested.is_dir():
        return

    staging = out_dir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    nested.rename(staging)

    try:
        for item in staging.iterdir():
            target = out_dir / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))
    finally:
        if staging.exists():
            shutil.rmtree(staging)


# ---------------------------------------------------------------------------
# 产物图标核对
# ---------------------------------------------------------------------------
# PyInstaller **不带 --icon 时也会塞一个默认图标**，所以「资源段里有没有图标」
# 完全没有区分力。漏接 --icon 的产物照样能跑，只是任务栏上是 PyInstaller 的
# 默认图标 —— 又一次「构建成功但产物不对」。唯一能判断的办法是比对内容：
# 把 PE 资源里 RT_GROUP_ICON 声明的尺寸集合，和 assets/icon.ico 的比。


def _ico_sizes(path: Path) -> list[int]:
    """读 .ico 里各张图的边长。

    宽高字段只有 1 字节，所以 256 记作 0 —— 这是 ICO 格式的历史包袱。
    """
    data = path.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    return sorted(data[6 + i * 16] or 256 for i in range(count))


def _pe_icon_sizes(path: Path) -> list[int]:
    """读 PE 资源里 RT_GROUP_ICON（类型 14）声明的图标边长。

    走一遍 PE 的资源目录树：类型 → 资源 ID → 语言 → 数据项。数据项给的是
    RVA，还要借节表换算成文件偏移。
    """
    data = path.read_bytes()
    if data[:2] != b"MZ":
        return []
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        return []

    coff = pe + 4
    n_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic not in (0x10B, 0x20B):  # PE32 / PE32+
        return []
    # 数据目录从可选头的固定偏移开始，PE32 和 PE32+ 差 16 字节。
    # 第 2 项（偏移 16）是资源表。
    dirs = opt + (112 if magic == 0x20B else 96)
    res_rva, res_size = struct.unpack_from("<II", data, dirs + 16)
    if not res_rva or not res_size:
        return []

    sections: list[tuple[int, int, int]] = []
    for i in range(n_sections):
        s = opt + opt_size + i * 40
        vaddr = struct.unpack_from("<I", data, s + 12)[0]
        raw_size, raw_ptr = struct.unpack_from("<II", data, s + 16)
        sections.append((vaddr, raw_size, raw_ptr))

    def to_offset(rva: int) -> int | None:
        for vaddr, raw_size, raw_ptr in sections:
            if vaddr <= rva < vaddr + raw_size:
                return raw_ptr + (rva - vaddr)
        return None

    res = to_offset(res_rva)
    if res is None:
        return []

    def children(rel: int) -> list[tuple[int, int]]:
        """资源目录某一层的 (ID, 子项偏移)。偏移都是相对资源目录起点的。"""
        n_named, n_id = struct.unpack_from("<HH", data, res + rel + 12)
        return [
            (
                struct.unpack_from("<I", data, res + rel + 16 + i * 8)[0] & 0x7FFFFFFF,
                struct.unpack_from("<I", data, res + rel + 20 + i * 8)[0] & 0x7FFFFFFF,
            )
            for i in range(n_named + n_id)
        ]

    sizes: list[int] = []
    for type_id, type_sub in children(0):
        if type_id != 14:
            continue
        for _icon_id, name_sub in children(type_sub):
            for _lang, leaf in children(name_sub):
                rva, size = struct.unpack_from("<II", data, res + leaf)
                start = to_offset(rva)
                if start is None:
                    continue
                group = data[start : start + size]
                if len(group) < 6:
                    continue
                count = struct.unpack_from("<H", group, 4)[0]
                # 每个 GRPICONDIRENTRY 14 字节，第 1 个字节是宽度（0 表示 256）
                sizes.extend(group[6 + i * 14] or 256 for i in range(count))
    return sorted(sizes)


def _assert_exe_icon(out_dir: Path, target: str) -> None:
    """确认产物真的带上了我们的图标。

    只在 Windows 上跑 —— 别的平台的 PyInstaller 不处理 .ico。
    """
    if os.name != "nt":
        return

    exe = out_dir / f"{TARGETS[target]['name']}.exe"
    if not exe.is_file():
        sys.exit(f"[icon] 找不到 {exe}")

    expected = _ico_sizes(ICON)
    actual = _pe_icon_sizes(exe)
    if actual != expected:
        sys.exit(
            f"[icon] {exe.name} 里的图标尺寸是 {actual}，期望 {expected}。\n"
            "[icon] 尺寸对不上说明 --icon 没生效（PyInstaller 会退回自己的默认"
            "图标），或者 assets/icon.ico 是旧的 —— 重新跑 scripts/make_icon.py。"
        )
    print(f"[icon] {exe.name} 图标尺寸核对通过：{actual}")


def smoke_test(out_dir: Path, target: str, version: str) -> None:
    """跑一遍产物，确认它真的能用。

    **这一步是补上去的。** rc1 的 CLI 能跑 ``--version``、能出 ``--help``，
    但一碰数据库就 ``ModuleNotFoundError: No module named 'aiosqlite'`` ——
    SQLAlchemy 是按名字动态导入驱动包的，PyInstaller 静态分析看不见。
    桌面端内置的后端**同样坏了**（lifespan 启动直接失败）。

    构建、CI、发布三道关全都没拦住，两个包就这么发出去了。

    教训：**「构建成功」不等于「产物能用」。** 只验文件存在、体积合理是不够的，
    必须真的执行一遍。

    Args:
        out_dir: 拍平后的产物目录。
        target: ``cli`` 或 ``backend``。
        version: 期望的版本号。

    Raises:
        SystemExit: 任一项不通过。
    """
    if target == "cli":
        _smoke_cli(out_dir, version)
    else:
        _smoke_backend(out_dir, version)

    # 图标和「能不能跑」无关，但同样属于「构建成功 ≠ 产物正确」那一类，
    # 而且漏了完全静默，所以放在这里一起把关。
    _assert_exe_icon(out_dir, target)


def _smoke_cli(out_dir: Path, version: str) -> None:
    exe = out_dir / ("mog.exe" if os.name == "nt" else "mog")
    if not exe.is_file():
        sys.exit(f"[smoke] 找不到可执行文件 {exe}")

    # **数据目录在 exe 旁边，不是 cwd。** 冻结模式走的是便携模式
    # （`runtime_dir()` 返回 `sys.executable` 的父目录），从哪儿调用都一样。
    # 跑完必须删掉，否则会连 data/token 一起打进发布包。
    data_dir = out_dir / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)

    checks: list[tuple[list[str], list[str], str]] = [
        # 入口 + 版本元数据（--copy-metadata 有没有生效）
        (["--version"], [], version),
        # 帮助界面必须是中文 —— Typer 的内置文案靠猴补丁换成中文的，
        # 打包漏了模块或补丁失效都会**静默**退回英文，不报错。
        (["--help"], ["选项", "命令"], ""),
        # 配置解析：不碰数据库，但会打印全部路径
        (["config", "path"], ["data"], ""),
        # **数据库读写**：这条是当初漏掉 aiosqlite 的地方
        (["source", "list"], [], ""),
        # 查询路径：本地全文搜索，走章节仓储
        (["find", "不存在的关键词"], [], "没有匹配"),
        # 书架列表：`mog export` 要的 book_id 从这里查
        (["book"], [], "书架是空的"),
    ]

    # 允许非零退出、但**绝不能抛异常**的探测。
    #
    # 有些能力在 CI 那种环境里天然不可用（`--show-completion` 探测不到父
    # 进程就退 1），但「不可用」和「崩了」是两回事 —— 后者说明打包漏了模块。
    crash_free: list[list[str]] = [
        # 走 shellingham 的平台分支（见 HIDDEN_IMPORTS 里的说明）
        ["--show-completion"],
    ]

    try:
        for args in crash_free:
            label = " ".join(args)
            result = subprocess.run(
                [str(exe), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if "Traceback" in output or "ModuleNotFoundError" in output:
                sys.exit(f"[smoke] `mog {label}` 抛异常了: {output}")

        for args, expect_any, expect_all in checks:
            label = " ".join(args)
            result = subprocess.run(
                [str(exe), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if result.returncode != 0:
                sys.exit(f"[smoke] `mog {label}` 退出码 {result.returncode}\n{output}")
            if "Traceback" in output or "ModuleNotFoundError" in output:
                sys.exit(f"[smoke] `mog {label}` 抛异常了\n{output}")
            for token in expect_any:
                if token not in output:
                    sys.exit(f"[smoke] `mog {label}` 输出里没有 {token!r}\n{output}")
            if expect_all and expect_all not in output:
                sys.exit(f"[smoke] `mog {label}` 输出里没有 {expect_all!r}\n{output}")

        # 首次运行必须把数据目录结构建全 —— 用户报告过这里不对
        missing = [name for name in EXPECTED_DATA_SUBDIRS if not (data_dir / name).is_dir()]
        if missing:
            sys.exit(f"[smoke] 数据目录没建全，缺: {', '.join(missing)}")

        # 输出必须是 UTF-8：打包后的 exe 会无视 PYTHONUTF8 / PYTHONIOENCODING，
        # 默认按控制台代码页输出，于是 --json 产出的不是合法 JSON。
        # 直接按字节比对 —— 解码成 str 再看就绕过了要验的东西。
        probe = subprocess.run([str(exe), "find", "测试"], capture_output=True, timeout=120)
        if "没有匹配".encode() not in probe.stdout:
            sys.exit(
                "[smoke] 输出不是 UTF-8 —— mograb.console 没生效。\n"
                f"[smoke] 实际字节: {probe.stdout[:60]!r}"
            )
    finally:
        # 产物里绝不能留运行期数据（里面有 API 令牌）
        if data_dir.exists():
            shutil.rmtree(data_dir)

    print(f"[smoke] cli 产物通过 {len(checks)} 项检查，数据目录与编码正常")


def _smoke_backend(out_dir: Path, version: str) -> None:
    """起一次后端，确认它能真正提供服务。

    桌面端内置的就是这个产物 —— 它坏了整个桌面端都用不了，
    而 CLI 的检查完全覆盖不到它，所以必须单独起一遍。

    ``/health`` 不碰数据库，**光看它通不出结论**：当初漏掉 aiosqlite 时
    lifespan 就炸了，而 ``/health`` 本身是好的。所以还要带令牌打一个
    走数据库的端点。
    """
    import json
    import socket
    import time
    import urllib.error
    import urllib.request

    exe = out_dir / ("mograb-api.exe" if os.name == "nt" else "mograb-api")
    if not exe.is_file():
        sys.exit(f"[smoke] 找不到可执行文件 {exe}")

    data_dir = out_dir / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)

    # 挑个空闲端口，免得和本机正在跑的实例撞上
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    proc = subprocess.Popen(
        [str(exe)],
        env={**os.environ, "MOGRAB_SERVER__PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    base = f"http://127.0.0.1:{port}"

    try:
        deadline = time.monotonic() + 60
        body = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                log = proc.stdout.read() if proc.stdout else "(无输出)"
                sys.exit(f"[smoke] 后端自己退出了（码 {proc.returncode}）\n{log}")
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=2) as resp:
                    body = resp.read().decode("utf-8")
                break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.5)
        else:
            sys.exit("[smoke] 后端 60 秒内没起来")

        payload = json.loads(body)
        if payload.get("status") != "ok":
            sys.exit(f"[smoke] /health 返回异常: {body}")
        if payload.get("version") != version:
            sys.exit(f"[smoke] /health 报的版本是 {payload.get('version')!r}，期望 {version!r}")

        # 带令牌打一个**走数据库**的端点 —— 这才是当初漏 aiosqlite 的地方
        token = (data_dir / "token").read_text(encoding="utf-8").strip()
        request = urllib.request.Request(
            f"{base}/api/v1/sources", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(request, timeout=10) as resp:
            if json.loads(resp.read().decode("utf-8")) != []:
                sys.exit("[smoke] 新装环境里 /api/v1/sources 应该是空列表")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if data_dir.exists():
            shutil.rmtree(data_dir)

    print("[smoke] backend 产物通过：/health 正常，带令牌的数据库端点可用")


def clean() -> None:
    """清理构建产物。"""
    for path in (ARTIFACTS, BUILD_DIR):
        if path.exists():
            shutil.rmtree(path)
            print(f"[clean] 已删除 {path}")
    for spec in REPO_ROOT.glob("*.spec"):
        spec.unlink()
        print(f"[clean] 已删除 {spec}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MoGrab 构建脚本")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in (*TARGETS, "all"):
        p = sub.add_parser(name, help=f"构建 {name}")
        p.add_argument("--version", default="0.0.0", help="版本号（写入产物元数据）")
        p.add_argument("--no-smoke", action="store_true", help="跳过构建后的产物冒烟测试")

    sub.add_parser("clean", help="清理构建产物")

    args = parser.parse_args()

    if args.command == "clean":
        clean()
        return

    targets = TARGETS if args.command == "all" else (args.command,)
    for target in targets:
        out_dir = build(target, args.version)
        if not args.no_smoke:
            smoke_test(out_dir, target, args.version)


if __name__ == "__main__":
    main()
