# SPDX-License-Identifier: GPL-3.0-only
"""生成应用图标。

**纯 Python 画，不引依赖。** 图标要能随时重新生成（改个颜色、调个圆角），
而 Pillow / cairosvg 都是不小的依赖，只为生成几个 PNG 不值得。
PNG 和 ICO 的编码器本身也就几十行 —— zlib 和 struct 都是标准库。

设计：圆角方块 + 白色翻开的书 + 向下的箭头。
书是「小说」，箭头是「抓取」—— 合起来就是 MoGrab。

用法::

    uv run python scripts/make_icon.py              # 生成图标
    uv run python scripts/make_icon.py --preview    # 顺带出一张对照图

输出：

=====================  ============================================
``assets/icon.png``    512×512，README 与桌面端打包
``assets/icon.ico``    Windows exe 图标（16→256 多尺寸）
=====================  ============================================

``--preview`` 额外写出 ``assets/_preview.png``：各档尺寸分别压在浅色和深色
背景上排一行，用来核对「两种任务栏上都清楚」这个前提。它是**看样用的临时
产物，不进版本库**（见 ``.gitignore``）。

**小尺寸不做简化版图形。** 实测到 16px，书脊缝仍有 2px 宽、箭头仍是独立
连通域 —— 结构没塌，所以同一个图形从 256 一路用到 16 就够。这条不变量在
``tests/unit/test_make_icon.py`` 里有断言，改几何时会被拦住。
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_ROOT / "assets"

MASTER = 1024
"""主图尺寸。所有小尺寸都从这里降采样 —— 一次高质量渲染，多次采样。"""

SUPERSAMPLE = 2
"""超采样倍数。圆角和多边形边缘靠它抹平，否则小尺寸下锯齿很明显。"""

# 配色。饱和的靛蓝→紫罗兰渐变配白字，浅色和深色任务栏上都清楚。
TOP_COLOR = (79, 70, 229)  # #4F46E5 indigo-600
BOTTOM_COLOR = (109, 40, 217)  # #6D28D9 violet-700
GLYPH_COLOR = (255, 255, 255)

CORNER_RADIUS = 0.22
"""底板的圆角，占边长的比例。Windows 应用图标大致在这个量级。"""

GLYPH_ROUND = 0.016
"""图形自身的圆角。

不加的话书页是硬邦邦的平行四边形，小尺寸下显得很廉价。圆角多边形的做法是
「向内缩一圈的多边形 ∪ 各个顶点上的圆」—— 见 :func:`_inside_rounded_polygon`。
"""

# ---------------------------------------------------------------------------
# 图形几何。全部用 0..1 的归一化坐标，改起来不用管分辨率。
# ---------------------------------------------------------------------------
# 书：上下边缘都是「中间低、两边高」的 V 形，中间留一道书脊缝。
BOOK_LEFT_X = 0.185
BOOK_RIGHT_X = 0.815
BOOK_SPINE_GAP = 0.018
BOOK_TOP_OUTER = 0.275
BOOK_TOP_CENTER = 0.335
BOOK_BOTTOM_OUTER = 0.545
BOOK_BOTTOM_CENTER = 0.605

# 箭头：竖杆 + 三角头，压在书下方。
ARROW_TOP = 0.640
ARROW_SHAFT_HALF = 0.048
ARROW_SHAFT_BOTTOM = 0.790
ARROW_HEAD_TOP = 0.758
"""三角的顶边比竖杆下端**高一点**，两块重叠 —— 正好接上的话圆角会留一道缝。"""
ARROW_HEAD_HALF = 0.115
ARROW_HEAD_BOTTOM = 0.885


def _inside_rounded_rect(x: float, y: float, radius: float) -> bool:
    """点是否落在圆角方块内（0..1 空间）。"""
    if x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0:
        return False
    # 四个角各自按四分之一圆处理，其余区域是矩形
    cx = radius if x < radius else (1.0 - radius if x > 1.0 - radius else x)
    cy = radius if y < radius else (1.0 - radius if y > 1.0 - radius else y)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _inside_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """射线法判断点是否在多边形内。"""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_at = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < x_at:
                inside = not inside
    return inside


def _inset_polygon(polygon: list[tuple[float, float]], dist: float) -> list[tuple[float, float]]:
    """凸多边形向内缩 ``dist``，返回新顶点。

    每条边沿内法线平移，相邻两条平移后的边求交点就是新顶点。

    内法线取 ``(-dy, dx)`` —— 这只对**顺时针（屏幕坐标，y 向下）**的顶点
    顺序成立。本文件里所有多边形都按这个顺序给。
    """
    n = len(polygon)
    edges: list[tuple[float, float, float, float]] = []
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        nx, ny = -dy / length * dist, dx / length * dist
        edges.append((x1 + nx, y1 + ny, x2 + nx, y2 + ny))

    result: list[tuple[float, float]] = []
    for i in range(n):
        ax1, ay1, ax2, ay2 = edges[i - 1]
        bx1, by1, bx2, by2 = edges[i]
        denominator = (ax1 - ax2) * (by1 - by2) - (ay1 - ay2) * (bx1 - bx2)
        if abs(denominator) < 1e-12:
            result.append(polygon[i])
            continue
        determinant_a = ax1 * ay2 - ay1 * ax2
        determinant_b = bx1 * by2 - by1 * bx2
        result.append(
            (
                (determinant_a * (bx1 - bx2) - (ax1 - ax2) * determinant_b) / denominator,
                (determinant_a * (by1 - by2) - (ay1 - ay2) * determinant_b) / denominator,
            )
        )
    return result


def _inside_rounded_polygon(x: float, y: float, inner: list[tuple[float, float]]) -> bool:
    """圆角多边形 = 内缩后的多边形，向外膨胀 ``GLYPH_ROUND``。

    「膨胀」的等价写法是「在内缩多边形里，或离它的边界不超过 r」——
    而在凸顶点附近，最近点就是那个顶点本身，所以判据退化成
    **「在内缩多边形里，或落在以内缩顶点为心、r 为半径的圆里」**。

    > 圆心是**内缩后**的顶点，不是原始顶点 —— 用原始顶点的话圆会凸出到
    > 多边形外面去，看起来像四个孤立的圆点粘在角上。
    """
    if _inside_polygon(x, y, inner):
        return True
    radius_squared = GLYPH_ROUND**2
    return any((x - vx) ** 2 + (y - vy) ** 2 <= radius_squared for vx, vy in inner)


def _arrow_head_polygon() -> list[tuple[float, float]]:
    """箭头的三角部分。

    **和竖杆分开画**，不拼成一个多边形 —— 拼起来是**凹多边形**，而内缩
    算法只对凸多边形成立（凹角处会算飞）。分成两个凸形状再取并集，
    肩部的直角自然由三角的圆角处理掉，竖杆的下端则被三角盖住。
    """
    return [
        (0.5 - ARROW_HEAD_HALF, ARROW_HEAD_TOP),
        (0.5 + ARROW_HEAD_HALF, ARROW_HEAD_TOP),
        (0.5, ARROW_HEAD_BOTTOM),
    ]


def _inside_arrow_shaft(x: float, y: float) -> bool:
    """竖杆：一个圆角矩形。"""
    half = ARROW_SHAFT_HALF
    radius = min(GLYPH_ROUND, half)
    cx = min(max(x, 0.5 - half + radius), 0.5 + half - radius)
    cy = min(max(y, ARROW_TOP + radius), ARROW_SHAFT_BOTTOM - radius)
    if not (0.5 - half <= x <= 0.5 + half and ARROW_TOP <= y <= ARROW_SHAFT_BOTTOM):
        return False
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _book_quads() -> list[list[tuple[float, float]]]:
    """书的两页。左页右缘和右页左缘留出书脊的缝。"""
    left_inner = 0.5 - BOOK_SPINE_GAP
    right_inner = 0.5 + BOOK_SPINE_GAP
    return [
        [
            (BOOK_LEFT_X, BOOK_TOP_OUTER),
            (left_inner, BOOK_TOP_CENTER),
            (left_inner, BOOK_BOTTOM_CENTER),
            (BOOK_LEFT_X, BOOK_BOTTOM_OUTER),
        ],
        [
            (right_inner, BOOK_TOP_CENTER),
            (BOOK_RIGHT_X, BOOK_TOP_OUTER),
            (BOOK_RIGHT_X, BOOK_BOTTOM_OUTER),
            (right_inner, BOOK_BOTTOM_CENTER),
        ],
    ]


def render_master() -> tuple[int, bytearray]:
    """渲染主图，返回 ``(边长, RGBA 字节)``。"""
    size = MASTER * SUPERSAMPLE
    pixels = bytearray(size * size * 4)
    # 内缩多边形只算一次 —— 它在逐像素循环里，重复算会慢十几倍
    glyphs = [
        _inset_polygon(polygon, GLYPH_ROUND) for polygon in (*_book_quads(), _arrow_head_polygon())
    ]
    inv = 1.0 / size

    for py in range(size):
        y = (py + 0.5) * inv
        # 背景是垂直渐变，同一行颜色相同 —— 提到行外算
        ratio = y
        bg = tuple(round(TOP_COLOR[i] + (BOTTOM_COLOR[i] - TOP_COLOR[i]) * ratio) for i in range(3))
        row_base = py * size * 4
        for px in range(size):
            x = (px + 0.5) * inv
            if not _inside_rounded_rect(x, y, CORNER_RADIUS):
                continue  # 透明
            color = bg
            if _inside_arrow_shaft(x, y) or any(
                _inside_rounded_polygon(x, y, inner) for inner in glyphs
            ):
                color = GLYPH_COLOR
            offset = row_base + px * 4
            pixels[offset] = color[0]
            pixels[offset + 1] = color[1]
            pixels[offset + 2] = color[2]
            pixels[offset + 3] = 255
    return size, pixels


def downsample(size: int, pixels: bytearray, target: int) -> bytearray:
    """把 ``size`` 见方的图缩到 ``target`` 见方（盒式平均）。

    预乘 alpha 再平均，否则透明边缘会带出一圈深色描边。
    """
    factor = size // target
    out = bytearray(target * target * 4)
    area = factor * factor
    for ty in range(target):
        for tx in range(target):
            r = g = b = a = 0
            for dy in range(factor):
                base = ((ty * factor + dy) * size + tx * factor) * 4
                for dx in range(factor):
                    offset = base + dx * 4
                    alpha = pixels[offset + 3]
                    r += pixels[offset] * alpha
                    g += pixels[offset + 1] * alpha
                    b += pixels[offset + 2] * alpha
                    a += alpha
            offset = (ty * target + tx) * 4
            if a == 0:
                continue
            out[offset] = min(255, round(r / a))
            out[offset + 1] = min(255, round(g / a))
            out[offset + 2] = min(255, round(b / a))
            out[offset + 3] = round(a / area)
    return out


# ---------------------------------------------------------------------------
# 编码
# ---------------------------------------------------------------------------
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, pixels: bytearray) -> bytes:
    """编成 PNG。每行前面要加一个 filter 字节（0 = 不过滤）。"""
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride : (y + 1) * stride]
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def encode_ico(images: list[tuple[int, bytes]]) -> bytes:
    """编成 ICO。

    每一项直接塞 PNG（Vista 起支持），比塞未压缩的 BMP 小得多。
    宽高字段是 1 字节，所以 256 要写成 0。
    """
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    offset = 6 + 16 * len(images)
    for size, payload in images:
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(payload), offset)
        offset += len(payload)
    return header + entries + b"".join(payload for _, payload in images)


ICO_SIZES = [256, 128, 64, 48, 32, 24, 16]
"""Windows 会按显示场景挑最合适的一档，所以要多备几个。"""

# ---------------------------------------------------------------------------
# 看样对照图（--preview）
# ---------------------------------------------------------------------------
PREVIEW_SIZES = [16, 24, 32, 48, 64, 128, 256]
PREVIEW_PAD = 24
"""每档尺寸左右各留的余量，免得相邻两档贴在一起。"""

PREVIEW_BACKGROUNDS = [(243, 243, 243), (30, 30, 30)]
"""浅色 / 深色任务栏。配色方案的前提是「两种底上都清楚」，对照图就是核这个的。"""


def _flatten(icon: bytearray, size: int, background: tuple[int, int, int]) -> bytearray:
    """把带 alpha 的图标压到纯色底上，得到不透明的图。"""
    out = bytearray(size * size * 4)
    for i in range(size * size):
        alpha = icon[i * 4 + 3]
        for channel in range(3):
            out[i * 4 + channel] = (
                icon[i * 4 + channel] * alpha + background[channel] * (255 - alpha)
            ) // 255
        out[i * 4 + 3] = 255
    return out


def render_preview(scaled) -> tuple[int, int, bytearray]:
    """各档尺寸 × 浅色/深色底的对照图，返回 ``(宽, 高, RGBA)``。"""
    columns = [(size, size + PREVIEW_PAD) for size in PREVIEW_SIZES]
    row_height = max(PREVIEW_SIZES)
    width = sum(cell for _, cell in columns)
    height = row_height * len(PREVIEW_BACKGROUNDS)
    canvas = bytearray(width * height * 4)

    for row, background in enumerate(PREVIEW_BACKGROUNDS):
        # 整行先铺底色。留透明的话看图时会被查看器的背景色接管，
        # 「浅色底 / 深色底」这个对照就失去意义了。
        row_pixels = bytearray(bytes(background) + b"\xff") * width
        for y in range(row * row_height, (row + 1) * row_height):
            dst = y * width * 4
            canvas[dst : dst + width * 4] = row_pixels

        left = 0
        for size, cell in columns:
            icon = _flatten(scaled(size), size, background)
            x0 = left + (cell - size) // 2
            y0 = row * row_height + (row_height - size) // 2
            for y in range(size):
                src = y * size * 4
                dst = ((y0 + y) * width + x0) * 4
                canvas[dst : dst + size * 4] = icon[src : src + size * 4]
            left += cell
    return width, height, canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 MoGrab 应用图标")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="额外写出 assets/_preview.png（各档尺寸 × 浅色/深色底对照图）",
    )
    options = parser.parse_args()

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[icon] 渲染主图 {MASTER}×{MASTER}（超采样 ×{SUPERSAMPLE}）…")
    size, pixels = render_master()

    cache: dict[int, bytearray] = {}

    def scaled(target: int) -> bytearray:
        if target not in cache:
            cache[target] = downsample(size, pixels, target)
        return cache[target]

    png_path = ASSETS_DIR / "icon.png"
    png_path.write_bytes(encode_png(512, 512, scaled(512)))
    print(f"[icon] 写出 {png_path.relative_to(REPO_ROOT)}  (512×512)")

    ico_path = ASSETS_DIR / "icon.ico"
    ico_path.write_bytes(encode_ico([(s, encode_png(s, s, scaled(s))) for s in ICO_SIZES]))
    print(f"[icon] 写出 {ico_path.relative_to(REPO_ROOT)}  ({', '.join(map(str, ICO_SIZES))})")

    if options.preview:
        width, height, canvas = render_preview(scaled)
        preview_path = ASSETS_DIR / "_preview.png"
        preview_path.write_bytes(encode_png(width, height, canvas))
        print(
            f"[icon] 写出 {preview_path.relative_to(REPO_ROOT)}  ({width}×{height})"
            " —— 看样用，不进版本库"
        )


if __name__ == "__main__":
    sys.exit(main())
