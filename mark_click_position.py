# -*- coding: utf-8 -*-
"""
在屏幕上标记指定坐标位置，并将鼠标移动到该位置。
用于调试：输入 Agent 输出的 (x, y)，确认实际点击位置是否正确。

用法:
  python mark_click_position.py 500 300
  python mark_click_position.py 500 300 --no-move   # 只标记，不移动鼠标
  python mark_click_position.py                     # 交互输入 x y
"""

import argparse
import time
import sys


def move_mouse(x: float, y: float) -> None:
    """将鼠标移动到 (x, y)。"""
    try:
        import pyautogui
        pyautogui.moveTo(x, y, duration=0.3)
        print("鼠标已移动到 (%.0f, %.0f)" % (x, y))
    except Exception as e:
        print("移动鼠标失败:", e)


def show_marker(x: float, y: float, radius: int = 30, duration: float = 5.0) -> None:
    """
    在屏幕 (x, y) 处显示一个红色圆形标记，持续 duration 秒后关闭。
    """
    try:
        import tkinter as tk
    except ImportError:
        print("未安装 tkinter，仅移动鼠标，不显示标记")
        return

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.9)
    # 窗口置于 (x - radius, y - radius)，大小 2*radius
    root.geometry("%dx%d+%d+%d" % (2 * radius, 2 * radius, int(x) - radius, int(y) - radius))

    canvas = tk.Canvas(root, width=2 * radius, height=2 * radius, highlightthickness=0, bg="white")
    canvas.pack(fill="both", expand=True)
    canvas.create_oval(2, 2, 2 * radius - 2, 2 * radius - 2, outline="red", width=4, fill="")
    canvas.create_text(radius, radius, text="(%d,%d)" % (int(x), int(y)), font=("Consolas", 10))

    def close():
        root.destroy()

    root.after(int(duration * 1000), close)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="在屏幕上标记坐标并移动鼠标到该位置")
    parser.add_argument("x", type=float, nargs="?", help="横坐标 x")
    parser.add_argument("y", type=float, nargs="?", help="纵坐标 y")
    parser.add_argument("--no-move", action="store_true", help="仅显示标记，不移动鼠标")
    parser.add_argument("--no-marker", action="store_true", help="仅移动鼠标，不显示标记")
    parser.add_argument("--duration", type=float, default=5.0, help="标记显示秒数，默认 5")
    parser.add_argument("--radius", type=int, default=30, help="标记圆半径（像素），默认 30")
    args = parser.parse_args()

    x, y = args.x, args.y
    if x is None or y is None:
        print("请输入坐标 (x y)，例如: 500 300")
        try:
            line = input().strip().replace(",", " ").replace("，", " ")
            parts = line.split()
            if len(parts) >= 2:
                x, y = float(parts[0]), float(parts[1])
            else:
                print("需要两个数字: x y")
                sys.exit(1)
        except EOFError:
            print("需要两个数字: x y")
            sys.exit(1)

    print("坐标: (%.2f, %.2f)" % (x, y))

    if not args.no_move:
        move_mouse(x, y)

    if not args.no_marker:
        show_marker(x, y, radius=args.radius, duration=args.duration)


if __name__ == "__main__":
    main()
