# -*- coding: utf-8 -*-
"""
无障碍树 / DOM 提供者抽象：按系统获取可交互元素列表（id, 文本, 类型, bbox），供混合架构「截图+结构化」使用。
支持按平台扩展：Windows (UI Automation)、macOS (AXAPI)、Linux (AT-SPI) 等。
"""

import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gui_agent.accessibility")


@dataclass
class AccessibleElement:
    """单个可交互元素：id 为当次快照内的序号，用于模型输出与执行层解析。"""
    id: int
    name: str
    role: str
    bbox: tuple  # (left, top, width, height) 屏幕坐标，与 PyAutoGUI 一致
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": (self.name or "").strip() or "(无文本)",
            "role": self.role,
            "bbox": list(self.bbox),
            **self.extra,
        }

    @property
    def center(self) -> tuple:
        """bbox 中心点 (x, y)，用于点击。"""
        left, top, w, h = self.bbox
        return (left + w / 2.0, top + h / 2.0)


class AccessibilityProvider:
    """
    无障碍树提供者抽象。
    子类按平台实现 get_elements()，返回当前屏幕/前台窗口下的可交互元素列表。
    """

    def get_elements(self) -> List[AccessibleElement]:
        """
        获取当前可交互元素列表（如按钮、输入框、链接等）。
        返回的 bbox 须为屏幕坐标系，与 PyAutoGUI 一致。
        """
        raise NotImplementedError


class NoOpAccessibilityProvider(AccessibilityProvider):
    """占位实现：无法获取无障碍树时返回空列表。"""

    def get_elements(self) -> List[AccessibleElement]:
        return []


def _is_valid_rect(left: float, top: float, right: float, bottom: float) -> bool:
    if right <= left or bottom <= top:
        return False
    if right - left < 2 or bottom - top < 2:
        return False
    return True


def _get_elements_pywinauto(
    elements: List[AccessibleElement],
    element_id: List[int],
    foreground_only: bool = True,
) -> None:
    """使用 pywinauto UIA 后端枚举元素。foreground_only 为 True 时仅枚举前台窗口；多窗口时前台窗口优先；窗内按 BFS 先外层后内层。"""
    import warnings
    from collections import deque
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        try:
            from pywinauto import Desktop
            from pywinauto import Application
        except ImportError as e:
            raise ImportError("pywinauto 未安装在当前 Python 环境，请在本项目激活的虚拟环境下执行: pip install pywinauto") from e
    try:
        desktop = Desktop(backend="uia")
    except Exception as e:
        logger.warning("pywinauto Desktop 初始化失败: %s", e)
        return
    windows_to_scan = []
    fg_hwnd = None
    if foreground_only:
        try:
            import win32gui
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd:
                app = Application(backend="uia").connect(handle=fg_hwnd)
                windows_to_scan = app.windows()
        except Exception as e:
            logger.debug("仅枚举前台窗口失败，回退全桌面: %s", e)
    if not windows_to_scan:
        windows_to_scan = list(desktop.windows())
    if windows_to_scan and fg_hwnd is None and sys.platform == "win32":
        try:
            import win32gui
            fg_hwnd = win32gui.GetForegroundWindow()
        except Exception:
            pass
    # 多窗口时把前台窗口排在最前，使最外层窗口的元素 id 更靠前
    if fg_hwnd is not None and len(windows_to_scan) > 1:
        def _order(w):
            h = getattr(w, "handle", None)
            return (0 if h == fg_hwnd else 1)
        try:
            windows_to_scan = sorted(windows_to_scan, key=_order)
        except Exception:
            pass

    def _add_control(ctrl: Any, role_default: str = "Control") -> None:
        try:
            r = ctrl.rectangle()
            if not r or not _is_valid_rect(r.left, r.top, r.right, r.bottom):
                return
            name = getattr(ctrl, "window_text", None) or getattr(ctrl, "name", None) or ""
            ctype = type(ctrl).__name__.replace("Wrapper", "") if hasattr(ctrl, "__class__") else role_default
            w, h = r.right - r.left, r.bottom - r.top
            elements.append(AccessibleElement(
                id=element_id[0], name=str(name), role=ctype,
                bbox=(r.left, r.top, w, h),
            ))
            element_id[0] += 1
        except Exception:
            pass

    try:
        for win in windows_to_scan:
            try:
                rect = win.rectangle()
                if rect and _is_valid_rect(rect.left, rect.top, rect.right, rect.bottom):
                    name = getattr(win, "window_text", None) or ""
                    w, h = rect.right - rect.left, rect.bottom - rect.top
                    elements.append(AccessibleElement(
                        id=element_id[0], name=str(name), role="Window",
                        bbox=(rect.left, rect.top, w, h),
                    ))
                    element_id[0] += 1
                # 按 BFS 枚举子控件，使最外层（直接子控件）的 id 优先于内层
                try:
                    children = win.children()
                except Exception:
                    children = []
                q = deque(children)
                while q:
                    node = q.popleft()
                    _add_control(node)
                    try:
                        for c in node.children():
                            q.append(c)
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception as e:
        logger.warning("pywinauto 枚举窗口失败: %s", e)


def _get_windows_uia_elements() -> List[AccessibleElement]:
    """通过 Windows UI Automation 枚举可交互元素。优先 uiautomation，其次 pywinauto。"""
    elements: List[AccessibleElement] = []
    element_id = [0]

    interactive_roles = {
        "Button", "Edit", "Hyperlink", "ListItem", "MenuItem", "TreeItem",
        "CheckBox", "RadioButton", "ComboBox", "TabItem",
        "Text", "Document", "Pane", "Window", "Group", "TitleBar",
    }

    def add_control(name: str, role: str, left: float, top: float, right: float, bottom: float) -> None:
        if not _is_valid_rect(left, top, right, bottom):
            return
        w, h = right - left, bottom - top
        elements.append(AccessibleElement(
            id=element_id[0], name=name or "", role=role,
            bbox=(int(left), int(top), int(w), int(h)),
        ))
        element_id[0] += 1

    try:
        import uiautomation as auto
    except ImportError:
        try:
            from config import ACCESSIBILITY_FOREGROUND_ONLY
            _get_elements_pywinauto(elements, element_id, foreground_only=ACCESSIBILITY_FOREGROUND_ONLY)
        except ImportError as e:
            logger.warning(
                "uiautomation 未安装且 pywinauto 导入失败: %s。请确认当前 Python 与 pip 一致（如 .venv 下先 pip install pywinauto），或 pip install uiautomation",
                e,
            )
        if not elements:
            logger.warning("Windows 无障碍树未获取到任何元素，CLICK_ELEMENT 将不可用。")
        return elements

    try:
        root = auto.GetRootControl()
    except Exception as e:
        logger.warning("Windows UIA 获取根控件失败: %s", e)
        return elements

    def walk(c: Any, depth: int) -> None:
        if depth > 30:
            return
        try:
            name = getattr(c, "Name", None) or ""
            ctype = getattr(c, "ControlTypeName", None) or getattr(c, "ControlType", None) or ""
            if isinstance(ctype, int):
                ctype = str(ctype)
            rect = getattr(c, "BoundingRectangle", None)
            if rect:
                try:
                    if hasattr(rect, "Left"):
                        left, top, right, bottom = rect.Left, rect.Top, rect.Right, rect.Bottom
                    else:
                        left, top, right, bottom = rect
                except (TypeError, ValueError):
                    pass
                else:
                    add_control(str(name), ctype or "Unknown", left, top, right, bottom)
            for child in c.GetChildren():
                walk(child, depth + 1)
        except Exception:
            pass

    try:
        for child in root.GetChildren():
            walk(child, 0)
    except Exception as e:
        logger.warning("遍历 Windows UIA 控件失败: %s", e)

    if not elements:
        try:
            from config import ACCESSIBILITY_FOREGROUND_ONLY
            _get_elements_pywinauto(elements, element_id, foreground_only=ACCESSIBILITY_FOREGROUND_ONLY)
            if elements:
                logger.info("uiautomation 返回 0 项，已用 pywinauto 回退，得到 %d 项", len(elements))
        except Exception as e:
            logger.warning("pywinauto 回退失败: %s", e)
    if not elements:
        logger.warning("Windows 无障碍树未获取到任何元素，CLICK_ELEMENT 将不可用。可尝试以管理员运行或检查 uiautomation/pywinauto 环境。")
    return elements


class WindowsUIAProvider(AccessibilityProvider):
    """Windows：使用 UI Automation 获取桌面可交互元素。"""

    def get_elements(self) -> List[AccessibleElement]:
        return _get_windows_uia_elements()


def _get_macos_elements() -> List[AccessibleElement]:
    """macOS：使用 AXAPI 获取可访问元素。占位，后续可接 pyobjc 或 subprocess 调用。"""
    logger.debug("macOS 无障碍提供者尚未实现，返回空列表")
    return []


class MacOSAXProvider(AccessibilityProvider):
    """macOS：使用 AXAPI。当前为占位。"""

    def get_elements(self) -> List[AccessibleElement]:
        return _get_macos_elements()


def _get_linux_elements() -> List[AccessibleElement]:
    """Linux：使用 AT-SPI。占位，后续可接 pyatspi。"""
    logger.debug("Linux 无障碍提供者尚未实现，返回空列表")
    return []


class LinuxATSPIProvider(AccessibilityProvider):
    """Linux：使用 AT-SPI。当前为占位。"""

    def get_elements(self) -> List[AccessibleElement]:
        return _get_linux_elements()


_PROVIDER: Optional[AccessibilityProvider] = None


def get_accessibility_provider(force_platform: Optional[str] = None) -> AccessibilityProvider:
    """
    根据当前系统返回无障碍提供者。可强制指定平台（用于测试或覆盖）。
    force_platform: "windows" | "macos" | "linux" | None（自动检测）
    """
    global _PROVIDER
    if force_platform is not None:
        plat = force_platform.strip().lower()
        if plat == "windows":
            return WindowsUIAProvider()
        if plat == "macos":
            return MacOSAXProvider()
        if plat == "linux":
            return LinuxATSPIProvider()
        return NoOpAccessibilityProvider()

    if _PROVIDER is not None:
        return _PROVIDER

    if sys.platform == "win32":
        _PROVIDER = WindowsUIAProvider()
    elif sys.platform == "darwin":
        _PROVIDER = MacOSAXProvider()
    else:
        _PROVIDER = LinuxATSPIProvider()
    return _PROVIDER
