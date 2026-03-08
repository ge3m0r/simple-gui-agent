# -*- coding: utf-8 -*-
"""
GUI Agent 主入口：本地运行，用户输入任务后执行观察-推理-执行循环。
使用 Qwen3-VL（默认）或通过环境变量/参数指定其他 VLM。
"""

import argparse
import logging
import sys

from config import (
    DEFAULT_VLM_MODEL,
    MAX_STEPS,
    OPENAI_BASE_URL,
    DASHSCOPE_API_KEY,
    OPENAI_API_KEY,
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    IMAGE_PREPROCESSOR,
)
from agent import GUIAgent
from env_local import get_screen_size, get_logical_screen_size

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("gui_agent")


def main():
    parser = argparse.ArgumentParser(description="GUI Agent: run desktop automation from task + screenshot")
    parser.add_argument("--task", "-t", type=str, default="", help="Task description; if empty, read from stdin")
    parser.add_argument("--model", "-m", type=str, default=DEFAULT_VLM_MODEL, help="VLM model name, e.g. qwen-vl-plus")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS, help="Max steps per run")
    parser.add_argument("--dry-run", action="store_true", help="Print config and task only, do not run")
    args = parser.parse_args()

    task = args.task.strip()
    if not task:
        print("请输入任务描述（一行），按 Enter 结束：")
        task = sys.stdin.readline().strip()
    if not task:
        logger.error("未提供任务描述")
        sys.exit(1)

    api_key = OPENAI_API_KEY or DASHSCOPE_API_KEY
    if not api_key and not args.dry_run:
        logger.error("请设置环境变量 OPENAI_API_KEY 或 DASHSCOPE_API_KEY")
        sys.exit(1)

    if args.dry_run:
        print("模型:", args.model)
        print("API Base:", OPENAI_BASE_URL)
        print("任务:", task)
        print("最大步数:", args.max_steps)
        return

    # 使用 PyAutoGUI 逻辑尺寸，保证「送 VLM 的图」与「点击坐标」一致
    logical_w, logical_h = get_logical_screen_size()
    try:
        capture_w, capture_h = get_screen_size()
    except Exception:
        capture_w, capture_h = logical_w, logical_h
    logger.info(
        "截图预处理方式=%s，输出尺寸 %dx%d（= 点击坐标空间）；原始捕获约 %dx%d。若点击仍偏移可设 GUI_AGENT_DEBUG_SAVE_SCREENSHOT=true 查看送 VLM 的图。",
        IMAGE_PREPROCESSOR, SCREEN_WIDTH, SCREEN_HEIGHT, capture_w, capture_h,
    )
    if (SCREEN_WIDTH, SCREEN_HEIGHT) != (logical_w, logical_h):
        logger.warning(
            "配置的屏幕尺寸 %dx%d 与 PyAutoGUI 逻辑尺寸 %dx%d 不一致，可能影响点击准确度。建议不设 GUI_AGENT_SCREEN_*。",
            SCREEN_WIDTH, SCREEN_HEIGHT, logical_w, logical_h,
        )

    agent = GUIAgent(model=args.model, max_steps=args.max_steps)

    def on_step(step, screenshot_b64, response, actions, done_reason):
        logger.info("步骤 %d: 动作数量=%d, 首动作=%s", step + 1, len(actions), actions[0] if actions else None)

    result = agent.run(task, on_step=on_step)
    logger.info("结束: success=%s, reason=%s, steps=%d", result["success"], result["reason"], result["steps"])
    if not result["success"] and result["last_response"]:
        print("最后一条模型回复:", result["last_response"][:500])
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
