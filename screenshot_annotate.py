# -*- coding: utf-8 -*-
"""
截图坐标标注：将截图缩放到逻辑分辨率并标注参考点与网格，使 VLM 看到的图像与坐标系统 1:1 对应。
参考：https://github.com/tylerelyt/test_bed/blob/main/src/search_engine/gui_agent_service.py
"""

import logging
from io import BytesIO
from typing import Tuple, Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("gui_agent.annotate")


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """获取字体，优先系统字体，否则默认字体。"""
    candidates = []
    try:
        import sys
        if sys.platform == "win32":
            candidates = [
                "C:\\Windows\\Fonts\\arial.ttf",
                "C:\\Windows\\Fonts\\msyh.ttc",
            ]
        elif sys.platform == "darwin":
            candidates = ["/System/Library/Fonts/Helvetica.ttc"]
        else:
            candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
    except Exception:
        pass
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_bbox(draw: ImageDraw.Draw, text: str, font) -> Tuple[int, int, int, int]:
    """获取文本边界框，兼容 PIL 10+ 与旧版。"""
    try:
        return draw.textbbox((0, 0), text, font=font)
    except AttributeError:
        # 旧版 PIL 无 textbbox，用 textsize
        try:
            w, h = draw.textsize(text, font=font)
            return 0, 0, w, h
        except Exception:
            return 0, 0, len(text) * 8, 16


def annotate_screenshot_with_coordinates(
    screenshot_bytes: bytes,
    screen_width: int,
    screen_height: int,
    enable_grid: bool = True,
    grid_rows: Optional[int] = None,
    grid_cols: Optional[int] = None,
) -> bytes:
    """
    在截图上标注坐标信息并缩放到逻辑分辨率，使 VLM 看到的图像与 PyAutoGUI 坐标 1:1 对应。

    策略：先将截图缩放到 (screen_width, screen_height)，再绘制四角、中心坐标及可选网格。

    Args:
        screenshot_bytes: 原始截图 PNG 字节
        screen_width: 逻辑宽度（与 prompt/执行一致）
        screen_height: 逻辑高度
        enable_grid: 是否绘制网格辅助线
        grid_rows, grid_cols: 若均大于 0，则按该行列数绘制与动作空间一致的网格，并标注格子索引 (row,col)

    Returns:
        标注并缩放后的 PNG 字节
    """
    try:
        img = Image.open(BytesIO(screenshot_bytes)).convert("RGB")
        orig_w, orig_h = img.size

        if (orig_w, orig_h) != (screen_width, screen_height):
            try:
                img = img.resize((screen_width, screen_height), Image.Resampling.LANCZOS)
            except AttributeError:
                img = img.resize((screen_width, screen_height), Image.LANCZOS)
            logger.info(
                "截图缩放: 原始 %dx%d -> 目标(与点击坐标一致) %dx%d",
                orig_w, orig_h, screen_width, screen_height,
            )
        else:
            logger.debug("截图尺寸已与目标一致: %dx%d", screen_width, screen_height)

        draw = ImageDraw.Draw(img, "RGBA")
        font = _get_font(24)
        font_small = _get_font(18)

        # 五处参考点：四角 + 中心
        points = [
            (0, 0, "(0, 0)", "topleft"),
            (screen_width - 1, 0, f"({screen_width-1}, 0)", "topright"),
            (0, screen_height - 1, f"(0, {screen_height-1})", "bottomleft"),
            (screen_width - 1, screen_height - 1, f"({screen_width-1}, {screen_height-1})", "bottomright"),
            (screen_width // 2, screen_height // 2, f"({screen_width//2}, {screen_height//2})", "center"),
        ]

        for x, y, label, position in points:
            r = 8
            draw.ellipse(
                [x - r, y - r, x + r, y + r],
                fill=(255, 0, 0, 200),
                outline=(255, 255, 255, 255),
                width=2,
            )
            bbox = _text_bbox(draw, label, font_small)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            pad = 5
            if position == "topleft":
                tx, ty = x + r + pad, y + r + pad
            elif position == "topright":
                tx, ty = x - r - pad - tw, y + r + pad
            elif position == "bottomleft":
                tx, ty = x + r + pad, y - r - pad - th
            elif position == "bottomright":
                tx, ty = x - r - pad - tw, y - r - pad - th
            else:
                tx, ty = x + r + pad, y - th // 2
            bg = 4
            draw.rectangle(
                [tx - bg, ty - bg, tx + tw + bg, ty + th + bg],
                fill=(0, 0, 0, 180),
            )
            draw.text((tx, ty), label, fill=(255, 255, 255, 255), font=font_small)

        if enable_grid:
            font_tiny = _get_font(12)
            if grid_rows and grid_cols and grid_rows > 0 and grid_cols > 0:
                # 与动作空间一致的 N 行 x M 列网格，标注格子索引 (row, col)
                cell_w = screen_width / float(grid_cols)
                cell_h = screen_height / float(grid_rows)
                for c in range(1, grid_cols):
                    x = int(c * cell_w)
                    draw.line([(x, 0), (x, screen_height)], fill=(128, 128, 128, 120), width=1)
                for r in range(1, grid_rows):
                    y = int(r * cell_h)
                    draw.line([(0, y), (screen_width, y)], fill=(128, 128, 128, 120), width=1)
                for r in range(grid_rows):
                    for c in range(grid_cols):
                        cx = int((c + 0.5) * cell_w)
                        cy = int((r + 0.5) * cell_h)
                        label = f"{r},{c}"
                        bbox = _text_bbox(draw, label, font_tiny)
                        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                        bp = 2
                        draw.rectangle(
                            [cx - lw // 2 - bp, cy - lh // 2 - bp, cx + lw // 2 + bp, cy + lh // 2 + bp],
                            fill=(0, 0, 0, 140),
                        )
                        draw.text((cx - lw // 2, cy - lh // 2), label, fill=(220, 220, 220, 255), font=font_tiny)
            else:
                if max(screen_width, screen_height) < 1000:
                    grid_spacing = 100
                elif max(screen_width, screen_height) < 2000:
                    grid_spacing = 200
                else:
                    grid_spacing = 300
                for x in range(0, screen_width + 1, grid_spacing):
                    if x == 0 or x >= screen_width:
                        continue
                    for y in range(0, screen_height, 10):
                        draw.line([(x, y), (x, min(y + 5, screen_height))], fill=(128, 128, 128, 80), width=1)
                for y in range(0, screen_height + 1, grid_spacing):
                    if y == 0 or y >= screen_height:
                        continue
                    for x in range(0, screen_width, 10):
                        draw.line([(x, y), (min(x + 5, screen_width), y)], fill=(128, 128, 128, 80), width=1)
                for x in range(grid_spacing, screen_width, grid_spacing):
                    for y in range(grid_spacing, screen_height, grid_spacing):
                        if abs(x - screen_width // 2) < grid_spacing // 2 and abs(y - screen_height // 2) < grid_spacing // 2:
                            continue
                        label = f"({x},{y})"
                        bbox = _text_bbox(draw, label, font_tiny)
                        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                        bp = 2
                        draw.rectangle(
                            [x - lw // 2 - bp, y - lh // 2 - bp, x + lw // 2 + bp, y + lh // 2 + bp],
                            fill=(0, 0, 0, 120),
                        )
                        draw.text((x - lw // 2, y - lh // 2), label, fill=(200, 200, 200, 200), font=font_tiny)

        # 顶部中央分辨率文字
        res_label = f"Screen: {screen_width}x{screen_height}"
        if enable_grid:
            res_label += " [Grid]"
            if grid_rows and grid_cols:
                res_label += f" {grid_rows}x{grid_cols}"
        bbox = _text_bbox(draw, res_label, font)
        rw, rh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        rx = (img.width - rw) // 2
        ry = 10
        bp = 8
        draw.rectangle(
            [rx - bp, ry - bp, rx + rw + bp, ry + rh + bp],
            fill=(0, 0, 0, 200),
        )
        draw.text((rx, ry), res_label, fill=(0, 255, 0, 255), font=font)

        out = BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception as e:
        logger.warning("截图标注失败，返回原图: %s", e)
        return screenshot_bytes
