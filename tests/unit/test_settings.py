# SPDX-License-Identifier: GPL-3.0-only
"""配置项的接线测试。

**盯的是「声明了但没接线」。** 这个项目已经栽过四次：字段、类型、文档都写好了，
链路断在半路，而失效方式是**静默**的 —— 用户配了以为生效，其实没生效。

`download.proxy` 是第五个。`HttpClientConfig.proxy` 一直存在、也传给了 httpx，
但 settings 里没有它、`config.toml` 模板里也没有，所以**永远是 `None`**。
用户实测时发现「不挂代理搜索失败」，正是撞在这上面。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mograb.app import create_application
from mograb.config import get_paths, load_settings

pytestmark = pytest.mark.unit


class TestProxySetting:
    def test_默认是_None(self) -> None:
        assert load_settings().download.proxy is None

    def test_从配置文件读(self) -> None:
        config = get_paths().config_file
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            '[download]\nproxy = "http://127.0.0.1:7890"\n',
            encoding="utf-8",
        )

        assert load_settings().download.proxy == "http://127.0.0.1:7890"

    def test_环境变量优先(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOGRAB_DOWNLOAD__PROXY", "socks5://127.0.0.1:1080")

        assert load_settings().download.proxy == "socks5://127.0.0.1:1080"

    def test_默认模板里带注释示例(self, tmp_path: Path) -> None:
        """模板里要有这一项，否则用户不知道能配。"""
        from mograb.config.settings import DEFAULT_CONFIG_TOML

        assert "proxy" in DEFAULT_CONFIG_TOML


class TestProxyWiring:
    """配置里的 proxy 必须真的传到 HTTP 客户端。

    这一段就是当初断掉的地方 —— settings 有字段、客户端有字段，
    中间那行没写。所以断言直接看客户端拿到的配置（白盒，但这正是要验的）。
    """

    async def test_传到_http_客户端(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOGRAB_DOWNLOAD__PROXY", "http://127.0.0.1:7890")

        async with create_application() as app:
            assert app.settings.download.proxy == "http://127.0.0.1:7890"
            # 白盒：HttpClient 没暴露 config 的公开访问器，而这里要验的
            # 恰恰是「传进去了没有」。
            assert app.http._config.proxy == "http://127.0.0.1:7890"

    async def test_不配时是_None(self) -> None:
        async with create_application() as app:
            assert app.http._config.proxy is None
