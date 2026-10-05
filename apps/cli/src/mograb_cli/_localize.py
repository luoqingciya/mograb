# SPDX-License-Identifier: GPL-3.0-only
"""把 Typer / Click 的内置英文文案换成中文。

为什么需要这个模块
------------------

Typer 和 Click 的界面文案是**写死在库里的英文**，没有配置项。于是 ``mog --help``
中英混排：

```
┌─ Options ───────────────────────────────────────────────┐
│ --install-completion   Install completion for the current shell. │
│ --help                 Show this message and exit.               │
└─────────────────────────────────────────────────────────┘
```

Typer 没有本地化开关。它的 ``_()`` 就是 ``gettext.gettext``，走那条路要装
gettext 目录、配 locale、带 ``.mo`` 文件 —— 对一个自带运行时的便携程序太重，
而且用户机器上未必有对应的 locale。

所以这里直接改**模块级变量**和**几个函数引用**。

**都是「改值」不是「改逻辑」，Typer 升级后可能失效** —— ``tests/unit/test_localize.py``
盯着这些文案，失效会红。

改不动的地方
------------

Click 的部分错误文案是在**抛异常的那一刻用 f-string 拼好的**
（比如 ``Group.get_command`` 里的 ``No such command 'x'.``），没有常量可改。
这里用一层文本替换兜住常见几种。真要有漏网的，它会是英文 —— 不影响功能。
"""

from __future__ import annotations

from typing import Any

from typer import _click, rich_utils
from typer import main as typer_main
from typer._click import exceptions as click_exceptions

__all__ = ["localize_typer"]

# 固定文案：面板标题与标记
_PANEL_TITLES: dict[str, str] = {
    "ARGUMENTS_PANEL_TITLE": "参数",
    "OPTIONS_PANEL_TITLE": "选项",
    "COMMANDS_PANEL_TITLE": "命令",
    "ERRORS_PANEL_TITLE": "错误",
}
_MARKERS: dict[str, str] = {
    "REQUIRED_LONG_STRING": "[必填]",
    "DEFAULT_STRING": "[默认: {}]",
    "ENVVAR_STRING": "[环境变量: {}]",
    "DEPRECATED_STRING": "（已废弃）",
    "ABORTED_TEXT": "已中断。",
    "RICH_HELP": "用 [blue]'{command_path} {help_option}'[/] 看帮助。",
}

# 选项说明
_INSTALL_COMPLETION_HELP = "为当前 shell 安装补全"
_SHOW_COMPLETION_HELP = "输出补全脚本，供复制或自行安装"
_HELP_OPTION_HELP = "显示这条帮助并退出"

_USAGE_PREFIX = "用法: "

# 错误文案的兜底替换。顺序有意义：长的先替，否则「Missing argument」会先吃掉
# 「Missing option」的一半。
_ERROR_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("Got unexpected extra argument", "多出了参数"),
    ("Got unexpected extra option", "多出了选项"),
    ("Missing argument", "缺少参数"),
    ("Missing option", "缺少选项"),
    ("Missing parameter", "缺少参数"),
    ("No such option", "没有这个选项"),
    ("No such command", "没有这个命令"),
    ("Invalid value for", "值不合法："),
    ("Invalid value", "值不合法"),
    ("Aborted!", "已中断。"),
)


def localize_typer() -> None:
    """就地替换 Typer / Click 的内置英文文案。幂等。

    在命令真正跑起来之前调用即可；放在模块导入时最省心。面板标题是渲染时
    才读的，所以和 ``Typer`` 实例的创建顺序无关。
    """
    _localize_constants()
    _localize_help_options()
    _localize_usage_prefix()
    _localize_error_messages()


def _localize_constants() -> None:
    """面板标题和标记是模块级全局，函数运行时才读 —— 直接赋值即可。"""
    for name, text in {**_PANEL_TITLES, **_MARKERS}.items():
        setattr(rich_utils, name, text)


def _localize_help_options() -> None:
    """``--install-completion`` / ``--show-completion``。

    这两个参数由 ``typer.main.get_command`` 每次构建命令时现造，
    来源是 ``get_install_completion_arguments()``。注意要打在 ``typer.main``
    上 —— 它用的是**导入时绑定的引用**，改 ``typer.completion`` 里的同名函数
    不会生效。
    """
    original = typer_main.get_install_completion_arguments

    def patched() -> Any:
        install_param, show_param = original()
        # 标成 Any 再赋值：`Parameter` 的类型标注里没有 `help`（只有 `Option` 有），
        # 直接赋值 pyright 会报；而 `setattr` 会被 ruff 的 B010 拦。
        # 运行时这两个确实是 Option。
        install: Any = install_param
        show: Any = show_param
        install.help = _INSTALL_COMPLETION_HELP
        show.help = _SHOW_COMPLETION_HELP
        return install_param, show_param

    typer_main.get_install_completion_arguments = patched

    # `--help` 由 Click 的 `Command.get_help_option()` 现造，同样没有配置项。
    original_help = _click.Command.get_help_option

    def patched_help(self: Any, ctx: Any) -> Any:
        option = original_help(self, ctx)
        if option is not None:
            help_option: Any = option
            help_option.help = _HELP_OPTION_HELP
        return option

    _click.Command.get_help_option = patched_help


def _localize_usage_prefix() -> None:
    """``Usage: `` 前缀。

    ``HelpFormatter.write_usage`` 本身支持传 ``prefix``，但 ``Command.format_usage``
    没传、用了默认值。这里补上。
    """

    def patched(self: Any, ctx: Any, formatter: Any) -> None:
        pieces = self.collect_usage_pieces(ctx)
        formatter.write_usage(ctx.command_path, " ".join(pieces), prefix=_USAGE_PREFIX)

    _click.Command.format_usage = patched


def _localize_error_messages() -> None:
    """常见错误文案。

    这几个类的 ``format_message`` 各写各的英文，得逐个包一层。
    ``No such command`` 那种是拼好字符串传进来的，走基类。
    """
    for cls in (
        click_exceptions.ClickException,
        click_exceptions.BadParameter,
        click_exceptions.MissingParameter,
        click_exceptions.NoSuchOption,
    ):
        original = cls.format_message

        def patched(self: Any, _original: Any = original) -> str:
            return _translate_error(_original(self))

        cls.format_message = patched


def _translate_error(text: str) -> str:
    for english, chinese in _ERROR_REPLACEMENTS:
        text = text.replace(english, chinese)
    # Click 拼的是西文句号。中文句子用全角 —— 项目对全角标点是一贯要求
    # （Ruff 的 RUF001/002/003 就是为此忽略的）。
    text = text.replace("'. ", "'。")
    if text.endswith("."):
        text = text[:-1] + "。"
    return text
