# SPDX-License-Identifier: GPL-3.0-only
"""``BookStatus.parse`` —— 书源提取到的状态文本怎么映射成枚举。

背景：这个枚举的文档一直写着「由书源尽力解析，未知时为 UNKNOWN」，
但从书源到 ``Book.status`` 的链路是断的，它永远只能是 UNKNOWN。
补链路的时候顺手把映射规则钉住。
"""

from __future__ import annotations

import pytest

from mograb.domain.enums import BookStatus

pytestmark = pytest.mark.unit


class TestCanonicalValues:
    def test_规范值原样认(self) -> None:
        assert BookStatus.parse("ongoing") is BookStatus.ONGOING
        assert BookStatus.parse("completed") is BookStatus.COMPLETED
        assert BookStatus.parse("unknown") is BookStatus.UNKNOWN

    def test_大小写不敏感(self) -> None:
        assert BookStatus.parse("ONGOING") is BookStatus.ONGOING
        assert BookStatus.parse("Completed") is BookStatus.COMPLETED

    def test_去首尾空白(self) -> None:
        assert BookStatus.parse("  已完结  ") is BookStatus.COMPLETED


class TestChineseAliases:
    def test_连载(self) -> None:
        for value in ("连载", "连载中", "連載", "連載中"):
            assert BookStatus.parse(value) is BookStatus.ONGOING, value

    def test_完结(self) -> None:
        for value in ("完结", "已完结", "完本", "已完本", "全本"):
            assert BookStatus.parse(value) is BookStatus.COMPLETED, value

    def test_英文同义词(self) -> None:
        for value in ("finished", "complete", "serializing"):
            assert BookStatus.parse(value) in (BookStatus.COMPLETED, BookStatus.ONGOING)


class TestUnknownFallback:
    def test_空值(self) -> None:
        assert BookStatus.parse(None) is BookStatus.UNKNOWN
        assert BookStatus.parse("") is BookStatus.UNKNOWN
        assert BookStatus.parse("   ") is BookStatus.UNKNOWN

    def test_认不出来就_UNKNOWN(self) -> None:
        """状态是锦上添花的元数据，不该因为它让整本书登记失败。"""
        for value in ("???", "连载/完结", "连载中（第2部）"):
            assert BookStatus.parse(value) is BookStatus.UNKNOWN, value

    def test_刻意不接受_0_和_1(self) -> None:
        """这两个值的含义每个站点都不一样，引擎没有依据去猜。

        本站 "1" 是已完结，换个站可能正好相反。书源该用锚定整值的
        regex_replace 自己转成规范值 —— 转换规则跟着书源一起被审阅。
        """
        assert BookStatus.parse("0") is BookStatus.UNKNOWN
        assert BookStatus.parse("1") is BookStatus.UNKNOWN

    def test_不做子串匹配(self) -> None:
        """「非连载」被子串匹配会得到完全相反的结论。"""
        assert BookStatus.parse("非连载") is BookStatus.UNKNOWN
        assert BookStatus.parse("尚未完结") is BookStatus.UNKNOWN
