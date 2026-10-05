# SPDX-License-Identifier: GPL-3.0-only
"""图标生成器的测试。

图标是**算出来的**，不是手画的位图 —— 所以能断言的东西比通常多：几何、
编码、以及「小尺寸下还认不认得出」都可以量化。

这里刻意**不把生成的 PNG 读回来人工看**：自动化测试看不了图，而「小尺寸
效果好不好」本来就该用可计算的判据回答，不该靠眼睛。

判据（都在**理想几何**上算，不碰抗锯齿，所以结果不随阈值漂移）：

- **书脊那一行断成两段** —— 不断的话书看起来是一块实心板。
- **书脊缝至少跨两行** —— 只有一行高的话，真实屏幕上会被抗锯齿抹平。
- **箭头那一行是一段** —— 断成两段或消失都说明箭头糊了。
- **圆角没有凸出原始多边形** —— 凸出来说明圆角用错了圆心。

这几条就是「小尺寸不用另画简化版」这个决定的依据。改几何时这里会先炸，
而不是等发版后有人盯着任务栏发现图标糊了。

> 判据刻意**不用「白连通域数量」**。那个量依赖抗锯齿后的 alpha 阈值：
> 同一张图，按 8 连通算是一块、按 4 连通算是三块，换个阈值又是另一个数。
> 用它当断言，测的是阈值不是图形。
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS = REPO_ROOT / "assets"


@pytest.fixture(scope="module")
def make_icon(load_script):
    return load_script("make_icon.py")


# ---------------------------------------------------------------------------
# 判据工具
# ---------------------------------------------------------------------------
def _insets(module) -> list[list[tuple[float, float]]]:
    """三块凸图形（左页 / 右页 / 箭头三角）各自内缩后的顶点。"""
    polygons = [*module._book_quads(), module._arrow_head_polygon()]
    return [module._inset_polygon(polygon, module.GLYPH_ROUND) for polygon in polygons]


def _glyph_mask(module, size: int) -> list[list[bool]]:
    """按 ``size×size`` 在像素中心采样，返回每格是不是白色图形。

    直接问几何函数，不走渲染 —— 图形本身是分辨率无关的，采样密度才是变量。
    """
    inner = _insets(module)
    mask: list[list[bool]] = []
    for py in range(size):
        y = (py + 0.5) / size
        row = []
        for px in range(size):
            x = (px + 0.5) / size
            row.append(
                module._inside_arrow_shaft(x, y)
                or any(module._inside_rounded_polygon(x, y, item) for item in inner)
            )
        mask.append(row)
    return mask


def _runs(row: list[bool]) -> list[int]:
    """一行里白色连续段的长度。"""
    out: list[int] = []
    current = 0
    for cell in row:
        if cell:
            current += 1
        elif current:
            out.append(current)
            current = 0
    if current:
        out.append(current)
    return out


# ---------------------------------------------------------------------------
# 小尺寸可读性
# ---------------------------------------------------------------------------
class TestSmallSizeLegibility:
    """小尺寸下图形还认不认得出。

    这是「不做简化版图形」这个决定的依据：正因为到 16px 关键结构都还在，
    同一个图形才能从 256 一路用到 16。图标糊掉是**静默**的 —— 没有测试
    就只能靠人盯着任务栏发现。
    """

    @pytest.mark.parametrize("size", [16, 24, 32, 48])
    def test_书脊缝把书断成两页(self, make_icon, size: int) -> None:
        """书的中部那一行必须断成两段，否则书看起来是一块实心板。"""
        runs = _runs(_glyph_mask(make_icon, size)[round(0.47 * size)])

        assert len(runs) == 2, f"{size}px 下书脊那一行的白段是 {runs}，期望 2 段"
        assert min(runs) >= 2, f"{size}px 下有一页只剩 {min(runs)}px 宽"

    @pytest.mark.parametrize("size", [16, 24, 32, 48])
    def test_书脊缝至少跨两行(self, make_icon, size: int) -> None:
        """缝只有一行高的话，真实屏幕上会被抗锯齿抹平，看不出是书。"""
        rows_with_gap = sum(1 for row in _glyph_mask(make_icon, size) if len(_runs(row)) == 2)

        assert rows_with_gap >= 2, f"{size}px 下只有 {rows_with_gap} 行能看出书脊缝"

    @pytest.mark.parametrize("size", [16, 24, 32, 48])
    def test_箭头在书下方仍看得见(self, make_icon, size: int) -> None:
        runs = _runs(_glyph_mask(make_icon, size)[round(0.72 * size)])

        assert len(runs) == 1, f"{size}px 下箭头那一行的白段是 {runs}，期望 1 段"
        assert runs[0] >= 2, f"{size}px 下箭头只有 {runs[0]}px 宽，等于看不见"


# ---------------------------------------------------------------------------
# 几何
# ---------------------------------------------------------------------------
class TestRoundedPolygon:
    """圆角不能凸到原始多边形外面去。

    圆角多边形的做法是「内缩一圈 ∪ 各顶点上的圆」。圆心必须用**内缩后**的
    顶点 —— 用原始顶点的话圆会凸出去，角上像粘了几个孤立的小圆点。
    """

    @pytest.mark.parametrize("index", [0, 1, 2])
    def test_没有凸出原始多边形的采样点(self, make_icon, index: int) -> None:
        polygons = [*make_icon._book_quads(), make_icon._arrow_head_polygon()]
        original = polygons[index]
        inner = make_icon._inset_polygon(original, make_icon.GLYPH_ROUND)

        steps = 200
        outside: list[tuple[float, float]] = []
        for i in range(steps + 1):
            for j in range(steps + 1):
                x, y = i / steps, j / steps
                if make_icon._inside_rounded_polygon(x, y, inner) and not make_icon._inside_polygon(
                    x, y, original
                ):
                    outside.append((x, y))

        assert not outside, (
            f"第 {index} 块图形有 {len(outside)} 个采样点凸出原始多边形，"
            f"例如 {outside[:3]} —— 多半是圆角用错了圆心"
        )

    def test_内缩后顶点数不变且确实动了(self, make_icon) -> None:
        for polygon in [*make_icon._book_quads(), make_icon._arrow_head_polygon()]:
            inner = make_icon._inset_polygon(polygon, make_icon.GLYPH_ROUND)
            assert len(inner) == len(polygon)
            for (outer_x, outer_y), (inner_x, inner_y) in zip(polygon, inner, strict=True):
                assert (inner_x - outer_x) ** 2 + (inner_y - outer_y) ** 2 > 0


# ---------------------------------------------------------------------------
# 编码
# ---------------------------------------------------------------------------
class TestEncoding:
    def test_ico_头与目录项(self, make_icon) -> None:
        blob = make_icon.encode_ico([(16, b"a" * 10), (256, b"b" * 20)])

        assert blob[:6] == struct.pack("<HHH", 0, 1, 2)
        # 第一项 16：宽高字段都写 16
        assert (blob[6], blob[7]) == (16, 16)
        # 第二项 256：宽高字段只有 1 字节，256 要写 0 —— 这是 ICO 的历史包袱
        assert (blob[22], blob[23]) == (0, 0)
        # 第一项数据从「头 6 字节 + 两条目录项 32 字节」开始
        assert struct.unpack_from("<I", blob, 18)[0] == 6 + 32

    def test_png_签名与_IHDR(self, make_icon) -> None:
        blob = make_icon.encode_png(4, 4, bytearray([10, 20, 30, 255] * 16))

        assert blob[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack_from(">II", blob, 16) == (4, 4)
        assert blob[24] == 8, "位深应该是 8"
        assert blob[25] == 6, "颜色类型应该是 6（RGBA）"


# ---------------------------------------------------------------------------
# 入库的产物
# ---------------------------------------------------------------------------
class TestCommittedArtifacts:
    """仓库里那份图标和脚本配置得对得上。

    图标是生成物但**要入库**（打包和 README 直接用文件）。所以「改了脚本忘了
    重新生成」是个真实风险 —— 这里把它变成测试失败，而不是等打包时才发现。
    """

    def test_ico_包含脚本声明的全部尺寸(self, make_icon) -> None:
        data = (ASSETS / "icon.ico").read_bytes()
        count = struct.unpack_from("<H", data, 4)[0]
        sizes = sorted(data[6 + i * 16] or 256 for i in range(count))
        assert sizes == sorted(make_icon.ICO_SIZES)

    def test_ico_每张图都是合法_png(self, make_icon) -> None:
        data = (ASSETS / "icon.ico").read_bytes()
        count = struct.unpack_from("<H", data, 4)[0]
        for i in range(count):
            _, offset = struct.unpack_from("<II", data, 6 + i * 16 + 8)
            assert data[offset : offset + 8] == b"\x89PNG\r\n\x1a\n", f"第 {i} 张不是 PNG"

    def test_icon_png_是_512(self) -> None:
        data = (ASSETS / "icon.png").read_bytes()
        assert struct.unpack_from(">II", data, 16) == (512, 512)


# ---------------------------------------------------------------------------
# 看样对照图
# ---------------------------------------------------------------------------
class TestPreview:
    """``--preview`` 对照图的布局。用假的 ``scaled`` 测，不跑真实渲染。"""

    @staticmethod
    def _solid(size: int) -> bytearray:
        return bytearray([200, 100, 50, 255] * (size * size))

    def test_画布尺寸由各档之和与行数决定(self, make_icon) -> None:
        width, height, canvas = make_icon.render_preview(self._solid)

        assert width == sum(s + make_icon.PREVIEW_PAD for s in make_icon.PREVIEW_SIZES)
        assert height == max(make_icon.PREVIEW_SIZES) * len(make_icon.PREVIEW_BACKGROUNDS)
        assert len(canvas) == width * height * 4

    def test_底色铺满没有透明像素(self, make_icon) -> None:
        """留透明的话查看器的背景色会顶上来，「浅色/深色底」的对照就废了。"""
        _width, _height, canvas = make_icon.render_preview(self._solid)

        assert all(canvas[i] == 255 for i in range(3, len(canvas), 4))
