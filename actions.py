# -*- coding: utf-8 -*-
"""
动作空间定义与 PyAutoGUI 执行器。
参考 OSWorld desktop_env/actions.py 与文档中的 Action Space。
"""

import re
import json
import time
import random
import logging
from typing import Any, List, Dict, Optional

import pyautogui

from config import (
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    GRID_ROWS,
    GRID_COLS,
    TYPING_IME_SWITCH_FOR_ASCII,
)

logger = logging.getLogger("gui_agent.actions")

# 屏幕边界（用于校验）
X_MAX = SCREEN_WIDTH
Y_MAX = SCREEN_HEIGHT

# 键盘按键列表（与 pyautogui 兼容的键名）
KEYBOARD_KEYS = [
    '\t', '\n', '\r', ' ', '!', '"', '#', '$', '%', '&', "'", '(', ')', '*', '+', ',', '-', '.', '/',
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ':', ';', '<', '=', '>', '?', '@', '[', '\\', ']', '^', '_', '`',
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
    '{', '|', '}', '~',
    'enter', 'return', 'backspace', 'tab', 'esc', 'escape', 'space', 'delete', 'up', 'down', 'left', 'right',
    'home', 'end', 'pageup', 'pagedown', 'insert',
    'ctrl', 'alt', 'shift', 'win', 'command', 'option',
    'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
    'capslock', 'numlock', 'scrolllock', 'pause',
]

# 动作类型与说明（用于 prompt）
ACTION_SPACE_DESC = [
    {"action_type": "CLICK_ELEMENT", "note": "按无障碍树元素 id 点击（混合架构）；需提供 element_id", "parameters": {"element_id": "int，见【可交互元素】列表"}},
    {"action_type": "MOVE_TO", "note": "将光标移动到指定坐标", "parameters": {"x": "float [0, X_MAX]", "y": "float [0, Y_MAX]"}},
    {"action_type": "CLICK", "note": "左键单击；可指定 button: left/right/middle，可指定 x,y 或使用当前光标位置", "parameters": {"button": "可选", "x": "可选", "y": "可选", "num_clicks": "可选 1/2/3"}},
    {"action_type": "RIGHT_CLICK", "note": "右键单击", "parameters": {"x": "可选", "y": "可选"}},
    {"action_type": "DOUBLE_CLICK", "note": "双击", "parameters": {"x": "可选", "y": "可选"}},
    {"action_type": "DRAG_TO", "note": "按住左键拖拽到目标位置", "parameters": {"x": "float", "y": "float"}},
    {"action_type": "SCROLL", "note": "滚轮滚动", "parameters": {"dx": "int 水平", "dy": "int 垂直，正数向上"}},
    {"action_type": "TYPING", "note": "输入文本", "parameters": {"text": "str"}},
    {"action_type": "PRESS", "note": "按下并释放单个键", "parameters": {"key": "str"}},
    {"action_type": "HOTKEY", "note": "组合键", "parameters": {"keys": "list[str]，如 ['ctrl', 'c']"}},
    {"action_type": "WAIT", "note": "等待若干秒", "parameters": {"seconds": "float"}},
    {"action_type": "DONE", "note": "任务完成"},
    {"action_type": "FAIL", "note": "任务无法完成"},
]


def clamp_xy(x: Optional[float], y: Optional[float]) -> tuple:
    """将坐标限制在屏幕范围内。"""
    if x is not None:
        x = max(0, min(X_MAX, float(x)))
    if y is not None:
        y = max(0, min(Y_MAX, float(y)))
    return x, y


# 模型常输出的键名与 pyautogui 的映射（参考 UI-TARS 等实现，提高鲁棒性）
_KEY_ALIASES = {
    "arrowleft": "left",
    "arrowright": "right",
    "arrowup": "up",
    "arrowdown": "down",
    "space": " ",
}


def _normalize_key(key: str) -> str:
    """将常见键名规范化为 pyautogui 可识别的形式。"""
    if not key:
        return key
    k = str(key).strip().lower()
    return _KEY_ALIASES.get(k, key)


def _click_like_action_equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """判断两个动作为同类型的点击/移动且坐标相同（用于检测重复）。"""
    at_a = (a.get("action_type") or a.get("type") or "").strip().upper()
    at_b = (b.get("action_type") or b.get("type") or "").strip().upper()
    if at_a != at_b:
        return False
    if at_a == "CLICK_ELEMENT":
        return a.get("element_id") == b.get("element_id")
    if at_a not in ("CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "MOVE_TO", "DRAG_TO"):
        return False
    # 比较网格坐标
    gr_a, gc_a = a.get("grid_row"), a.get("grid_col")
    gr_b, gc_b = b.get("grid_row"), b.get("grid_col")
    if gr_a is not None or gc_a is not None or gr_b is not None or gc_b is not None:
        if gr_a != gr_b or gc_a != gc_b:
            return False
        if gr_a is not None or gc_a is not None:
            return True
    # 比较归一化坐标或像素坐标
    for key in ("norm_x", "norm_y", "x", "y"):
        va, vb = a.get(key), b.get(key)
        if va is not None or vb is not None:
            if va is None or vb is None:
                return False
            if abs(float(va) - float(vb)) > 1e-6:
                return False
    return True


def apply_retry_offset(action: Dict[str, Any], pixel_offset: int = 8) -> Dict[str, Any]:
    """
    对点击/移动类动作施加小幅随机偏移，避免与上一步完全同一点重复点击。
    复制一份 action 再修改，不改变原字典。
    """
    import copy
    act = copy.deepcopy(action)
    at = (act.get("action_type") or act.get("type") or "").strip().upper()
    if at not in ("CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "MOVE_TO", "DRAG_TO"):
        return act
    if act.get("grid_row") is not None or act.get("grid_col") is not None:
        # 网格坐标：在相邻格子内随机偏移
        r = int(act.get("grid_row", 0))
        c = int(act.get("grid_col", 0))
        r = r + random.randint(-1, 1)
        c = c + random.randint(-1, 1)
        act["grid_row"] = max(0, min(GRID_ROWS - 1, r))
        act["grid_col"] = max(0, min(GRID_COLS - 1, c))
    elif act.get("norm_x") is not None or act.get("norm_y") is not None:
        # 归一化坐标 0-1000：偏移约 5 单位（0.5%）
        norm_offset = 5
        if act.get("norm_x") is not None:
            n = float(act["norm_x"]) + random.uniform(-norm_offset, norm_offset)
            act["norm_x"] = max(0, min(1000, round(n, 2)))
        if act.get("norm_y") is not None:
            n = float(act["norm_y"]) + random.uniform(-norm_offset, norm_offset)
            act["norm_y"] = max(0, min(1000, round(n, 2)))
    else:
        if act.get("x") is not None:
            act["x"] = max(0, min(X_MAX, float(act["x"]) + random.randint(-pixel_offset, pixel_offset)))
        if act.get("y") is not None:
            act["y"] = max(0, min(Y_MAX, float(act["y"]) + random.randint(-pixel_offset, pixel_offset)))
    logger.info("检测到与上一步相同的点击/移动动作，已施加小幅随机偏移后执行: %s", act)
    return act


def resolve_xy(action: Dict[str, Any]) -> tuple:
    """
    从动作中解析出 (x, y) 像素坐标。
    优先级：grid_row/grid_col > norm_x/norm_y > x/y。
    网格坐标：取格子中心，即 (grid_col + 0.5) * cell_w, (grid_row + 0.5) * cell_h。
    """
    grid_row = action.get("grid_row")
    grid_col = action.get("grid_col")
    if grid_row is not None or grid_col is not None:
        r = int(grid_row) if grid_row is not None else 0
        c = int(grid_col) if grid_col is not None else 0
        r = max(0, min(GRID_ROWS - 1, r))
        c = max(0, min(GRID_COLS - 1, c))
        cell_w = X_MAX / float(GRID_COLS)
        cell_h = Y_MAX / float(GRID_ROWS)
        x = (c + 0.5) * cell_w
        y = (r + 0.5) * cell_h
        return x, y
    norm_x = action.get("norm_x")
    norm_y = action.get("norm_y")
    if norm_x is not None or norm_y is not None:
        x = float(norm_x) * X_MAX / 1000.0 if norm_x is not None else None
        y = float(norm_y) * Y_MAX / 1000.0 if norm_y is not None else None
        return x, y
    return action.get("x"), action.get("y")


def execute_action(
    action: Dict[str, Any],
    step_delay: float = 0.3,
    element_list: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    使用 PyAutoGUI 执行单条动作。
    element_list: 无障碍树元素列表（每项含 id, name, role, bbox），用于 CLICK_ELEMENT。
    返回 True 表示执行成功，False 表示遇到 DONE/FAIL 或异常。
    """
    if not action or not isinstance(action, dict):
        return True

    action_type = (action.get("action_type") or action.get("type") or "").strip().upper()
    if not action_type:
        logger.warning("动作缺少 action_type: %s", action)
        return True

    if action_type == "DONE":
        logger.info("任务标记为完成 (DONE)")
        return False
    if action_type == "FAIL":
        logger.info("任务标记为无法完成 (FAIL)")
        return False

    try:
        if action_type == "CLICK_ELEMENT":
            eid = action.get("element_id")
            name = action.get("name")
            if name is not None:
                name = (name or "").strip()
            # 按 element_id 解析：需要已有 element_list
            if eid is not None and element_list is not None:
                try:
                    eid_int = int(eid)
                except (TypeError, ValueError):
                    logger.warning("CLICK_ELEMENT 的 element_id 无法转为整数: %s", eid)
                    return True
                el = next((e for e in element_list if int(e.get("id", -1)) == eid_int), None)
                if el is None:
                    ids = [e.get("id") for e in element_list[:20]]
                    logger.warning(
                        "未找到 element_id=%s 的元素（当前列表共 %d 项，前项 id: %s）",
                        eid, len(element_list), ids,
                    )
                    return True
            elif name:
                # 按 name 解析：当未提供元素列表或列表为空时拉取当前可交互元素（与 ACCESSIBILITY_FETCH_ON_CLICK_ONLY 配合：预处理器不拉取则此处拉取）
                if element_list is None or len(element_list) == 0:
                    try:
                        from accessibility_providers import get_accessibility_provider
                        provider = get_accessibility_provider()
                        raw = provider.get_elements()
                        element_list = [e.to_dict() if hasattr(e, "to_dict") else {"id": e.id, "name": e.name, "role": e.role, "bbox": list(e.bbox)} for e in raw]
                    except Exception as e:
                        logger.warning("按 name 点击时拉取无障碍元素失败: %s", e)
                        return True
                # 优先精确匹配，其次包含；列表顺序已为最外层优先，取第一个匹配
                el = None
                for e in element_list:
                    en = (e.get("name") or "").strip()
                    if en == name:
                        el = e
                        break
                if el is None:
                    for e in element_list:
                        en = (e.get("name") or "").strip()
                        if name in en or en in name:
                            el = e
                            break
                if el is None:
                    logger.warning("未找到 name=%r 的控件（共 %d 项）", name, len(element_list))
                    return True
            else:
                logger.warning("CLICK_ELEMENT 需要 element_id（且提供 element_list）或 name")
                return True
            bbox = el.get("bbox")
            if not bbox or len(bbox) < 4:
                logger.warning("元素 bbox 无效: %s", el)
                return True
            left, top, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
            cx = left + w / 2.0
            cy = top + h / 2.0
            cx, cy = clamp_xy(cx, cy)
            pyautogui.click(cx, cy)
            time.sleep(step_delay)
            return True

        if action_type == "MOVE_TO":
            x, y = resolve_xy(action)
            x, y = clamp_xy(x, y)
            if x is not None and y is not None:
                pyautogui.moveTo(x, y, duration=0.2)
            time.sleep(step_delay)
            return True

        if action_type == "CLICK":
            x, y = resolve_xy(action)
            x, y = clamp_xy(x, y)
            button = (action.get("button") or "left").lower()
            num_clicks = int(action.get("num_clicks", 1))
            if x is not None and y is not None:
                pyautogui.click(x, y, clicks=num_clicks, button=button)
            else:
                pyautogui.click(clicks=num_clicks, button=button)
            time.sleep(step_delay)
            return True

        if action_type == "RIGHT_CLICK":
            x, y = resolve_xy(action)
            x, y = clamp_xy(x, y)
            if x is not None and y is not None:
                pyautogui.rightClick(x, y)
            else:
                pyautogui.rightClick()
            time.sleep(step_delay)
            return True

        if action_type == "DOUBLE_CLICK":
            x, y = resolve_xy(action)
            x, y = clamp_xy(x, y)
            if x is not None and y is not None:
                pyautogui.doubleClick(x, y)
            else:
                pyautogui.doubleClick()
            time.sleep(step_delay)
            return True

        if action_type == "DRAG_TO":
            x, y = resolve_xy(action)
            x, y = clamp_xy(x, y)
            if x is not None and y is not None:
                pyautogui.drag(x, y, duration=0.3)
            time.sleep(step_delay)
            return True

        if action_type == "SCROLL":
            dx = int(action.get("dx", 0))
            dy = int(action.get("dy", 0))
            if dy != 0:
                pyautogui.scroll(dy)
            if dx != 0:
                pyautogui.hscroll(dx)
            time.sleep(step_delay)
            return True

        if action_type == "TYPING":
            text = action.get("text", "")
            if text:
                # 若配置了“输入英文前切换输入法”且当前要输入的内容为纯 ASCII（英文/URL/命令等），先发送切换快捷键
                if TYPING_IME_SWITCH_FOR_ASCII and text.strip():
                    raw_to_type = text.rstrip("\r\n") if text.endswith("\n") else text
                    if raw_to_type.isascii():
                        try:
                            keys = [k.strip().lower() for k in TYPING_IME_SWITCH_FOR_ASCII.split(",") if k.strip()]
                            if keys:
                                pyautogui.hotkey(*[_normalize_key(k) for k in keys])
                                time.sleep(0.15)
                        except Exception as e:
                            logger.debug("TYPING 前切换输入法失败: %s", e)
                # 输入前先 Ctrl+A 选中当前焦点处全部内容，再输入，避免在已有内容后追加导致错误
                try:
                    pyautogui.hotkey("ctrl", "a")
                    time.sleep(0.05)
                except Exception:
                    pass
                # 末尾换行表示“输入后提交”，先输入正文再按 Enter（与 UI-TARS 等一致）
                if text.endswith("\n"):
                    text = text.rstrip("\r\n")
                    if text:
                        pyautogui.write(text, interval=0.05)
                    pyautogui.press("enter")
                else:
                    pyautogui.write(text, interval=0.05)
            time.sleep(step_delay)
            return True

        if action_type == "PRESS":
            key = action.get("key", "")
            if key:
                pyautogui.press(_normalize_key(key))
            time.sleep(step_delay)
            return True

        if action_type == "HOTKEY":
            keys = action.get("keys", [])
            if isinstance(keys, str):
                keys = [keys]
            if keys:
                normalized = [_normalize_key(k) for k in keys]
                pyautogui.hotkey(*normalized)
            time.sleep(step_delay)
            return True

        if action_type == "WAIT":
            seconds = float(action.get("seconds", 1.0))
            time.sleep(max(0, seconds))
            return True

        logger.warning("未知动作类型: %s", action_type)
        return True
    except Exception as e:
        logger.exception("执行动作失败: %s, error: %s", action, e)
        return True


def parse_actions_from_response(response: str) -> List[Dict[str, Any]]:
    """
    从 VLM 返回文本中解析出动作列表。
    支持：```json ... ``` 或 纯 JSON 单行/多行。
    """
    text = (response or "").strip()
    if text.upper() in ("WAIT", "DONE", "FAIL"):
        return [{"action_type": text.upper()}]

    actions = []
    # 优先匹配 ```json ... ```
    for match in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text):
        part = match.strip()
        if not part:
            continue
        try:
            obj = json.loads(part)
            if isinstance(obj, list):
                actions.extend(obj)
            else:
                actions.append(obj)
            if actions:
                return actions
        except json.JSONDecodeError:
            continue

    # 尝试整段为 JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
        return [obj]
    except json.JSONDecodeError:
        pass

    # 尝试找 {...} 片段
    for match in re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
        try:
            actions.append(json.loads(match))
        except json.JSONDecodeError:
            continue
    return actions if actions else []
