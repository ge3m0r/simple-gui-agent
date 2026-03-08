# -*- coding: utf-8 -*-
"""本地桌面环境：截图与屏幕信息。"""

import base64
import logging
from io import BytesIO
from typing import Optional

import pyautogui

logger = logging.getLogger("gui_agent.env")

# 使用 mss 可跨平台且更快；若无则退回 pyautogui.screenshot
try:
    import mss
    import mss.tools
    _USE_MSS = True
except ImportError:
    _USE_MSS = False


def get_screen_size() -> tuple:
    """返回 (width, height)。优先 mss（多屏时 monitors[0] 为全屏）。"""
    try:
        if _USE_MSS:
            with mss.mss() as sct:
                mon = sct.monitors[0]
                return mon["width"], mon["height"]
        size = pyautogui.size()
        return size.width, size.height
    except Exception as e:
        logger.warning("获取屏幕尺寸失败: %s，使用默认 1920x1080", e)
        return 1920, 1080


def get_logical_screen_size() -> tuple:
    """
    返回 PyAutoGUI 使用的逻辑屏幕尺寸 (width, height)。
    与 pyautogui.click(x,y) / moveTo(x,y) 的坐标空间一致，用于保证「截图送 VLM」与「实际点击」同一坐标系。
    Windows 高 DPI 下 mss 可能得到物理像素，而 PyAutoGUI 使用逻辑像素，故此处仅用 pyautogui.size()。
    """
    try:
        size = pyautogui.size()
        return size.width, size.height
    except Exception as e:
        logger.warning("获取逻辑屏幕尺寸失败: %s，使用默认 1920x1080", e)
        return 1920, 1080


def capture_screenshot(
    region: Optional[tuple] = None,
    format: str = "png"
) -> bytes:
    """
    截取屏幕图像，返回 PNG 字节流。
    region: (left, top, width, height)，None 表示全屏。
    """
    if _USE_MSS and region is None:
        with mss.mss() as sct:
            mon = sct.monitors[0]
            shot = sct.grab(mon)
            img = __mss_to_png(shot)
            return img
    if _USE_MSS and region is not None:
        left, top, width, height = region
        with mss.mss() as sct:
            shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
            img = __mss_to_png(shot)
            return img
    # 回退到 pyautogui
    pil = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
    buf = BytesIO()
    pil.save(buf, format=format or "png")
    return buf.getvalue()


def __mss_to_png(shot: "mss.tools.ScreenShot") -> bytes:
    from PIL import Image
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def screenshot_to_base64(region: Optional[tuple] = None) -> str:
    """截屏并转为 base64 字符串（data URL 去掉前缀，仅内容）。"""
    raw = capture_screenshot(region=region)
    return base64.b64encode(raw).decode("utf-8")


def screenshot_to_base64_resized(screen_width: int, screen_height: int) -> str:
    """
    截屏后缩放到 (screen_width, screen_height) 再转 base64。
    保证送 VLM 的图像与点击使用的逻辑坐标 1:1 对应，避免物理分辨率与逻辑分辨率不一致导致坐标错位。
    """
    raw = capture_screenshot(region=None)
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(raw)).convert("RGB")
        orig_w, orig_h = img.size
        if (orig_w, orig_h) != (screen_width, screen_height):
            try:
                img = img.resize((screen_width, screen_height), Image.Resampling.LANCZOS)
            except AttributeError:
                img = img.resize((screen_width, screen_height), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG")
            raw = buf.getvalue()
    except Exception as e:
        logger.warning("截图缩放到逻辑分辨率失败 %s，使用原图", e)
    return base64.b64encode(raw).decode("utf-8")


def capture_screenshot_logical(screen_width: int, screen_height: int) -> bytes:
    """
    使用 PyAutoGUI 截取全屏，得到与逻辑坐标一致的图像（Windows 高 DPI 下与 pyautogui 点击空间一致）。
    返回 PNG 字节。若需指定尺寸，由调用方再 resize。
    """
    try:
        pil = pyautogui.screenshot()
        buf = BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning("PyAutoGUI 截图失败 %s，回退到 capture_screenshot", e)
        return capture_screenshot(region=None)


def screenshot_to_base64_annotated(
    screen_width: int,
    screen_height: int,
    region: Optional[tuple] = None,
    enable_grid: bool = True,
    use_logical_capture: bool = False,
    grid_rows: Optional[int] = None,
    grid_cols: Optional[int] = None,
) -> str:
    """
    截屏后做坐标标注并「强制」缩放到 (screen_width, screen_height)，再转为 base64。
    grid_rows, grid_cols: 若提供则绘制与动作空间一致的网格并标注格子索引 (row,col)。
    """
    from screenshot_annotate import annotate_screenshot_with_coordinates
    if use_logical_capture and region is None:
        raw = capture_screenshot_logical(screen_width, screen_height)
    else:
        raw = capture_screenshot(region=region)
    annotated = annotate_screenshot_with_coordinates(
        raw, screen_width, screen_height, enable_grid=enable_grid,
        grid_rows=grid_rows, grid_cols=grid_cols,
    )
    return base64.b64encode(annotated).decode("utf-8")
