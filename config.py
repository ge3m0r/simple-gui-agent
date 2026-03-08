# -*- coding: utf-8 -*-
"""GUI Agent 配置。"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("gui_agent.config")

# 屏幕分辨率：与 PyAutoGUI 执行点击的坐标空间一致，避免 DPI/多屏导致坐标错位
# 使用 get_logical_screen_size()（仅 pyautogui.size()），不混用 mss 的物理像素
def _get_screen_size_default():
    try:
        from env_local import get_logical_screen_size
        w, h = get_logical_screen_size()
        return str(w), str(h)
    except Exception as e:
        logger.warning("自动获取逻辑屏幕尺寸失败 %s，使用 1920x1080", e)
        return "1920", "1080"

_default_w, _default_h = _get_screen_size_default()
SCREEN_WIDTH = int(os.environ.get("GUI_AGENT_SCREEN_WIDTH", _default_w))
SCREEN_HEIGHT = int(os.environ.get("GUI_AGENT_SCREEN_HEIGHT", _default_h))

# 默认 VLM：Qwen3-VL 使用 qwen-vl-plus（DashScope）；也可填 qwen3-vl-plus 等
DEFAULT_VLM_MODEL = os.environ.get("GUI_AGENT_VLM_MODEL", "qwen-vl-plus")

# API 配置
# DashScope（阿里云）: 设置 DASHSCOPE_API_KEY，base_url 使用 DashScope 兼容端点
# OpenAI 兼容: 设置 OPENAI_API_KEY 和可选的 OPENAI_BASE_URL
# 读取时去除首尾空格，避免 .env 中误输入空格导致 401
DASHSCOPE_API_KEY = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
# 使用 DashScope 时默认用兼容 OpenAI 的端点；OpenAI 直连时设为 https://api.openai.com/v1
OPENAI_BASE_URL = os.environ.get(
    "OPENAI_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 执行配置
MAX_STEPS = int(os.environ.get("GUI_AGENT_MAX_STEPS", "30"))
STEP_DELAY = float(os.environ.get("GUI_AGENT_STEP_DELAY", "1.0"))
MAX_TRAJECTORY_LENGTH = int(os.environ.get("GUI_AGENT_MAX_TRAJECTORY", "3"))

# 网格化动作空间：将屏幕划分为 N 行 M 列，模型输出 grid_row、grid_col。网格越密则每格对应屏幕范围越小、定位越准
# 默认 20x20：每格约 (宽/20) x (高/20) 像素，便于点击小按钮（如运行对话框中的确定、搜索结果项）
GRID_ROWS = int(os.environ.get("GUI_AGENT_GRID_ROWS", "20"))
GRID_COLS = int(os.environ.get("GUI_AGENT_GRID_COLS", "20"))

# 送 VLM 前截图预处理方式：grid（网格标注）| resize_only（仅缩放）。可扩展注册其他方案（如 som）
IMAGE_PREPROCESSOR = os.environ.get("GUI_AGENT_IMAGE_PREPROCESSOR", "grid").strip().lower()

# 网格预处理器下是否绘制网格线（仅当 IMAGE_PREPROCESSOR=grid 时生效）
ANNOTATE_GRID = os.environ.get("GUI_AGENT_ANNOTATE_GRID", "true").strip().lower() in ("1", "true", "yes")

# 调试：是否在第一步保存送 VLM 的标注截图到 debug_screenshot_0.png（便于核对模型看到的图与坐标）
DEBUG_SAVE_SCREENSHOT = os.environ.get("GUI_AGENT_DEBUG_SAVE_SCREENSHOT", "false").strip().lower() in ("1", "true", "yes")

# 无障碍树：是否仅枚举前台窗口（减少项数、加快枚举，prompt 前 80 项多为当前窗口）
ACCESSIBILITY_FOREGROUND_ONLY = os.environ.get("GUI_AGENT_ACCESSIBILITY_FOREGROUND_ONLY", "true").strip().lower() in ("1", "true", "yes")

# 无障碍树：是否仅在模型返回点击/双击等需要点控件的动作时才获取元素（True=按需获取，用 name 解析；False=每步都获取并传 element_id）
ACCESSIBILITY_FETCH_ON_CLICK_ONLY = os.environ.get("GUI_AGENT_ACCESSIBILITY_FETCH_ON_CLICK_ONLY", "false").strip().lower() in ("1", "true", "yes")

# TYPING 前是否自动切换输入法：当要输入的内容为纯英文/数字/符号（URL、命令、路径等）时，先发送该快捷键再输入。留空则不自动切换，由模型在 prompt 中规划。示例: "ctrl,space" 或 "win,space"
TYPING_IME_SWITCH_FOR_ASCII = (os.environ.get("GUI_AGENT_TYPING_IME_SWITCH_FOR_ASCII", "") or "").strip()
