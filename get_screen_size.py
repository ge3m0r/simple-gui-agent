# -*- coding: utf-8 -*-
"""获取当前屏幕的宽和高（像素）。"""

def get_size():
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[0]
            return mon["width"], mon["height"]
    except ImportError:
        pass
    try:
        import pyautogui
        size = pyautogui.size()
        return size.width, size.height
    except Exception:
        pass
    return None, None


if __name__ == "__main__":
    w, h = get_size()
    if w is not None and h is not None:
        print("宽度(宽):", w)
        print("高度(高):", h)
    else:
        print("无法获取屏幕尺寸")
