# -*- coding: utf-8 -*-
"""
送 VLM 前的截图预处理抽象层。
将「原始截图 -> 发给模型的图像」解耦为可插拔的预处理器，便于后续接入不同方案（网格标注、仅缩放、SoM 打标等）。
"""

import base64
import logging
import sys
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, Optional

logger = logging.getLogger("gui_agent.preprocessors")


@dataclass
class PreprocessResult:
    """预处理结果：送 VLM 的图像与元数据。"""
    image_base64: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def action_mode(self) -> str:
        """动作空间模式：grid | pixel | som 等，供 prompt/执行层按需使用。"""
        return self.metadata.get("action_mode", "grid")


class ScreenshotPreprocessor:
    """
    截图预处理器抽象基类。
    子类实现 prepare()，将原始截图字节转为送 VLM 的图像（base64）及可选元数据。
    """

    def prepare(
        self,
        raw_screenshot: bytes,
        screen_width: int,
        screen_height: int,
        **kwargs: Any,
    ) -> PreprocessResult:
        """
        对原始截图做预处理，得到送 VLM 的图像与元数据。

        Args:
            raw_screenshot: 原始截图 PNG 字节
            screen_width: 逻辑屏幕宽度（与点击坐标一致）
            screen_height: 逻辑屏幕高度
            **kwargs: 预处理器可选参数（如 enable_grid、grid_rows 等）

        Returns:
            PreprocessResult.image_base64: 送 VLM 的图片 base64（无 data URL 前缀）
            PreprocessResult.metadata: 可选，如 action_mode、grid_rows、grid_cols、som_elements 等
        """
        raise NotImplementedError


class GridPreprocessor(ScreenshotPreprocessor):
    """
    网格标注预处理器：缩放到逻辑分辨率并在图上绘制网格与格子索引 (row,col)。
    对应原 ANNOTATE_SCREENSHOT + ANNOTATE_GRID 方案。
    """

    def __init__(
        self,
        grid_rows: int = 20,
        grid_cols: int = 20,
        enable_grid: bool = True,
    ):
        self.grid_rows = grid_rows
        self.grid_cols = grid_cols
        self.enable_grid = enable_grid

    def prepare(
        self,
        raw_screenshot: bytes,
        screen_width: int,
        screen_height: int,
        **kwargs: Any,
    ) -> PreprocessResult:
        from screenshot_annotate import annotate_screenshot_with_coordinates
        grid_rows = kwargs.get("grid_rows", self.grid_rows)
        grid_cols = kwargs.get("grid_cols", self.grid_cols)
        enable_grid = kwargs.get("enable_grid", self.enable_grid)
        annotated = annotate_screenshot_with_coordinates(
            raw_screenshot,
            screen_width,
            screen_height,
            enable_grid=enable_grid,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
        )
        b64 = base64.b64encode(annotated).decode("utf-8")
        return PreprocessResult(
            image_base64=b64,
            metadata={
                "action_mode": "grid",
                "grid_rows": grid_rows,
                "grid_cols": grid_cols,
            },
        )


class ResizeOnlyPreprocessor(ScreenshotPreprocessor):
    """
    仅缩放预处理器：将截图缩放到逻辑分辨率，不绘制网格或标注。
    保证与点击坐标 1:1 对应，适合后续用像素/归一化坐标或自研方案。
    """

    def prepare(
        self,
        raw_screenshot: bytes,
        screen_width: int,
        screen_height: int,
        **kwargs: Any,
    ) -> PreprocessResult:
        try:
            from PIL import Image
        except ImportError:
            logger.warning("PIL 未安装，返回原图")
            return PreprocessResult(
                image_base64=base64.b64encode(raw_screenshot).decode("utf-8"),
                metadata={"action_mode": "pixel"},
            )
        img = Image.open(BytesIO(raw_screenshot)).convert("RGB")
        orig_w, orig_h = img.size
        if (orig_w, orig_h) != (screen_width, screen_height):
            try:
                img = img.resize((screen_width, screen_height), Image.Resampling.LANCZOS)
            except AttributeError:
                img = img.resize((screen_width, screen_height), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG")
            raw_screenshot = buf.getvalue()
        b64 = base64.b64encode(raw_screenshot).decode("utf-8")
        return PreprocessResult(
            image_base64=b64,
            metadata={"action_mode": "pixel"},
        )


class AccessibilityPreprocessor(ScreenshotPreprocessor):
    """
    无障碍树混合预处理器：缩放到逻辑分辨率；可选获取可交互元素并在图上标 id。
    当 ACCESSIBILITY_FETCH_ON_CLICK_ONLY 为 True 时，本步不获取元素（按需在执行点击时再获取，模型用 name 指定控件）。
    """

    def __init__(self, draw_ids_on_image: bool = True):
        self.draw_ids_on_image = draw_ids_on_image

    def prepare(
        self,
        raw_screenshot: bytes,
        screen_width: int,
        screen_height: int,
        **kwargs: Any,
    ) -> PreprocessResult:
        from PIL import Image, ImageDraw, ImageFont
        from accessibility_providers import get_accessibility_provider, AccessibleElement
        from config import ACCESSIBILITY_FETCH_ON_CLICK_ONLY

        img = Image.open(BytesIO(raw_screenshot)).convert("RGB")
        orig_w, orig_h = img.size
        if (orig_w, orig_h) != (screen_width, screen_height):
            try:
                img = img.resize((screen_width, screen_height), Image.Resampling.LANCZOS)
            except AttributeError:
                img = img.resize((screen_width, screen_height), Image.LANCZOS)

        elements = []
        if not ACCESSIBILITY_FETCH_ON_CLICK_ONLY:
            provider = get_accessibility_provider()
            elements = provider.get_elements()
            if self.draw_ids_on_image and elements:
                draw = ImageDraw.Draw(img, "RGBA")
                font = None
                if sys.platform == "win32":
                    try:
                        font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 14)
                    except Exception:
                        pass
                if font is None:
                    font = ImageFont.load_default()
                for el in elements:
                    left, top, w, h = el.bbox
                    if w <= 0 or h <= 0:
                        continue
                    draw.rectangle([left, top, left + w, top + h], outline=(0, 255, 0, 200), width=2)
                    label = f"[{el.id}]"
                    draw.text((left, max(top - 16, 0)), label, fill=(0, 255, 0, 255), font=font)

        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return PreprocessResult(
            image_base64=b64,
            metadata={
                "action_mode": "accessibility",
                "elements": [el.to_dict() for el in elements],
            },
        )


# 预处理器注册表：名称 -> 预处理器实例，便于通过配置切换
REGISTRY: Dict[str, ScreenshotPreprocessor] = {}


def _register_builtin() -> None:
    """注册内置预处理器。"""
    from config import GRID_ROWS, GRID_COLS, ANNOTATE_GRID
    REGISTRY["grid"] = GridPreprocessor(
        grid_rows=GRID_ROWS,
        grid_cols=GRID_COLS,
        enable_grid=ANNOTATE_GRID,
    )
    REGISTRY["resize_only"] = ResizeOnlyPreprocessor()
    REGISTRY["accessibility"] = AccessibilityPreprocessor(draw_ids_on_image=True)


def get_preprocessor(name: Optional[str] = None) -> ScreenshotPreprocessor:
    """
    根据名称获取预处理器。若未注册过则先注册内置项。

    Args:
        name: 预处理器名称，如 "grid"、"resize_only"。None 时使用 config.IMAGE_PREPROCESSOR。

    Returns:
        ScreenshotPreprocessor 实例

    Raises:
        KeyError: 未知名称
    """
    if not REGISTRY:
        _register_builtin()
    if name is None:
        from config import IMAGE_PREPROCESSOR
        name = IMAGE_PREPROCESSOR
    name = (name or "grid").strip().lower()
    if name not in REGISTRY:
        raise KeyError(f"未知的截图预处理器: {name}，可选: {list(REGISTRY.keys())}")
    return REGISTRY[name]


def register_preprocessor(name: str, preprocessor: ScreenshotPreprocessor) -> None:
    """注册自定义预处理器，便于扩展 SoM、Coarse-to-Fine 等方案。"""
    REGISTRY[name.strip().lower()] = preprocessor
    logger.info("已注册截图预处理器: %s", name)
