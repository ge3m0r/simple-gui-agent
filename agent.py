# -*- coding: utf-8 -*-
"""
GUI Agent：观察-推理-执行循环。
用户输入任务 -> 截图 -> VLM 推理 -> 解析动作 -> PyAutoGUI 执行 -> 循环直至 DONE/FAIL 或达到最大步数。
"""

import json
import logging
from typing import List, Dict, Any, Optional

from config import (
    MAX_STEPS,
    STEP_DELAY,
    MAX_TRAJECTORY_LENGTH,
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    GRID_ROWS,
    GRID_COLS,
    DEBUG_SAVE_SCREENSHOT,
)
from env_local import capture_screenshot, get_screen_size
from image_preprocessors import get_preprocessor
from prompts import get_system_text, build_step_prompt
from vlm_client import call_vlm
from actions import parse_actions_from_response, execute_action, _click_like_action_equal, apply_retry_offset

logger = logging.getLogger("gui_agent")


class GUIAgent:
    """基于截图的 GUI 自动化 Agent，每步截图后调用 VLM 得到下一动作并执行。"""

    def __init__(
        self,
        model: Optional[str] = None,
        max_steps: int = MAX_STEPS,
        step_delay: float = STEP_DELAY,
        max_trajectory_length: int = MAX_TRAJECTORY_LENGTH,
    ):
        self.model = model
        self.max_steps = max_steps
        self.step_delay = step_delay
        self.max_trajectory_length = max_trajectory_length
        self.observations: List[Dict[str, Any]] = []
        self.actions: List[Any] = []
        self.thoughts: List[str] = []

    def reset(self) -> None:
        """清空历史轨迹。"""
        self.observations = []
        self.actions = []
        self.thoughts = []

    def _format_history_lines(self, act_slice: list, thought_slice: list) -> list:
        """将历史动作格式化为【历史动作及执行情况】中的多行文本。"""
        lines = []
        for i, (action_list, thought) in enumerate(zip(act_slice, thought_slice), start=1):
            act = action_list[0] if action_list and isinstance(action_list, list) else action_list
            if isinstance(act, dict):
                at = (act.get("action_type") or act.get("type") or "").strip().upper()
                desc = at
                if at == "TYPING" and act.get("text") is not None:
                    desc = f"{at} text={repr(act.get('text'))}"
                elif at == "HOTKEY" and act.get("keys") is not None:
                    desc = f"{at} keys={act.get('keys')}"
                elif at == "CLICK_ELEMENT":
                    if act.get("element_id") is not None:
                        desc = f"{at} element_id={act.get('element_id')}"
                    elif act.get("name") is not None:
                        desc = f"{at} name={repr(act.get('name'))}"
                    else:
                        desc = at
                elif at in ("CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "MOVE_TO", "DRAG_TO") and (act.get("grid_row") is not None or act.get("grid_col") is not None):
                    desc = f"{at} grid_row={act.get('grid_row')} grid_col={act.get('grid_col')}"
                elif at in ("CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "MOVE_TO", "DRAG_TO") and (act.get("x") is not None or act.get("y") is not None):
                    desc = f"{at} x={act.get('x')} y={act.get('y')}"
                elif at in ("CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "MOVE_TO", "DRAG_TO") and (act.get("norm_x") is not None or act.get("norm_y") is not None):
                    desc = f"{at} norm_x={act.get('norm_x')} norm_y={act.get('norm_y')}"
                else:
                    desc = str(act)[:80]
            else:
                desc = str(act)[:80]
            lines.append(f"步骤{i}: 已执行 {desc}。请根据下一张截图判断是否达到预期；若未达到请勿重复同一动作。")
        return lines

    def _last_action_no_repeat_hint(self, act_slice: list) -> Optional[str]:
        """若有上一步动作，返回勿重复提示，用于本步期望回答。"""
        if not act_slice:
            return None
        last_list = act_slice[-1]
        act = last_list[0] if last_list and isinstance(last_list, list) else last_list
        if not isinstance(act, dict):
            return None
        at = (act.get("action_type") or act.get("type") or "").strip().upper()
        if at in ("DONE", "FAIL", "WAIT"):
            return None
        # 上一步为可重复的点击/移动等，明确要求本步若界面无变化则勿重复
        short = json.dumps(act, ensure_ascii=False)[:120]
        return f"上一步已执行: {short}。若当前截图与上一张相比无变化，说明该操作未生效，本步不得输出相同动作，必须换坐标或换方式（如快捷键、右键、其它区域）或返回 FAIL。"

    def _action_signature(self, act: Dict[str, Any]) -> Optional[str]:
        """生成动作的签名，用于检测重复。HOTKEY 按 keys 排序；点击类按坐标分桶（50 像素）。"""
        if not isinstance(act, dict):
            return None
        at = (act.get("action_type") or act.get("type") or "").strip().upper()
        if at == "HOTKEY":
            keys = act.get("keys") or []
            if isinstance(keys, str):
                keys = [keys]
            return "HOTKEY_" + "_".join(sorted(str(k).lower() for k in keys)) if keys else None
        if at == "CLICK_ELEMENT":
            eid = act.get("element_id")
            name = act.get("name")
            if eid is not None:
                return f"CLICK_ELEMENT_id_{eid}"
            if name is not None:
                return f"CLICK_ELEMENT_name_{name}"
            return None
        if at in ("CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "MOVE_TO", "DRAG_TO"):
            gr, gc = act.get("grid_row"), act.get("grid_col")
            if gr is not None or gc is not None:
                return f"{at}_g{int(gr or 0)}_{int(gc or 0)}"
            x, y = act.get("x"), act.get("y")
            nx, ny = act.get("norm_x"), act.get("norm_y")
            if nx is not None or ny is not None:
                bx = int(round(float(nx or 0) / 50) * 50) if nx is not None else 0
                by = int(round(float(ny or 0) / 50) * 50) if ny is not None else 0
                return f"{at}_{bx}_{by}"
            if x is not None or y is not None:
                bx = int(round(float(x or 0) / 50) * 50)
                by = int(round(float(y or 0) / 50) * 50)
                return f"{at}_{bx}_{by}"
        return None

    def _repeated_action_hint(self, act_slice: list, window: int = 6, min_repeat: int = 2) -> Optional[str]:
        """若最近 window 步内某动作签名出现 >= min_repeat 次，返回强制换方式/FAIL 的提示。"""
        if len(act_slice) < min_repeat:
            return None
        recent = act_slice[-window:] if len(act_slice) >= window else act_slice
        from collections import Counter
        sigs = []
        for action_list in recent:
            act = action_list[0] if action_list and isinstance(action_list, list) else action_list
            sig = self._action_signature(act) if isinstance(act, dict) else None
            if sig and (act.get("action_type") or act.get("type") or "").strip().upper() not in ("WAIT", "DONE", "FAIL"):
                sigs.append(sig)
        if not sigs:
            return None
        cnt = Counter(sigs)
        repeated = [s for s, c in cnt.items() if c >= min_repeat]
        if not repeated:
            return None
        desc = "、".join(repeated[:3])
        if len(repeated) > 3:
            desc += " 等"
        return f"最近 {len(recent)} 步内已多次执行以下操作且未达成目标：{desc}。本步不得再重复上述任一操作，必须换用其他方式（如不同坐标、键盘输入、右键菜单、其它区域）或返回 FAIL。"

    def _build_messages(
        self,
        instruction: str,
        current_screenshot_b64: str,
        preprocess_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """构建发给 VLM 的 messages：结构化 prompt + 截图。preprocess_meta 含 action_mode 时用对应系统提示（accessibility 下无 grid）；无 elements 时用按 name 点击的提示。"""
        action_mode = (preprocess_meta or {}).get("action_mode") if preprocess_meta else None
        elements = (preprocess_meta or {}).get("elements") if preprocess_meta else None
        system_text = get_system_text(instruction, action_mode, elements=elements)
        messages = [
            {"role": "system", "content": [{"type": "text", "text": system_text}]},
        ]

        n_obs = len(self.observations)
        n_act = len(self.actions)
        n_thought = len(self.thoughts)
        num_hist = min(n_act, n_thought, max(0, n_obs - 1))
        if num_hist <= 0:
            obs_slice, act_slice, thought_slice = [], [], []
        else:
            start_idx = -min(self.max_trajectory_length, num_hist)
            obs_slice = self.observations[start_idx:-1]
            act_slice = self.actions[start_idx:]
            thought_slice = self.thoughts[start_idx:]

        for idx, (obs, action_list, thought) in enumerate(zip(obs_slice, act_slice, thought_slice), start=1):
            prev_b64 = obs.get("screenshot") or ""
            # 该回合之前已执行的动作（用于该回合时的「历史」）
            hist_act = act_slice[:idx]
            hist_thought = thought_slice[:idx]
            hist_lines = self._format_history_lines(hist_act, hist_thought)
            step_text = build_step_prompt(
                final_goal=instruction,
                current_goal_hint="根据截图与历史推断当前子目标。",
                history_lines=hist_lines,
                expected_output_hint="仅输出一个动作的 JSON 或 WAIT/DONE/FAIL。若上一步未生效请换方式或 FAIL，不要重复。",
            )
            content = [{"type": "text", "text": step_text}]
            if prev_b64:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{prev_b64}", "detail": "high"},
                })
            messages.append({"role": "user", "content": content})
            action_str = str(action_list) if action_list else (thought or "WAIT")
            messages.append({"role": "assistant", "content": [{"type": "text", "text": action_str}]})

        # 当前步骤：历史汇总 + 当前截图；若有无障碍元素则注入【可交互元素】并优先 CLICK_ELEMENT
        history_lines = self._format_history_lines(act_slice, thought_slice) if act_slice else []
        last_no_repeat = self._last_action_no_repeat_hint(act_slice)
        repeated_hint = self._repeated_action_hint(act_slice, window=6, min_repeat=2)
        elements = (preprocess_meta or {}).get("elements") if preprocess_meta else None
        step_text = build_step_prompt(
            final_goal=instruction,
            current_goal_hint=None,
            history_lines=history_lines,
            expected_output_hint=None,
            last_action_no_repeat=last_no_repeat,
            repeated_action_force_hint=repeated_hint,
            elements=elements,
        )
        content = [
            {"type": "text", "text": step_text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{current_screenshot_b64}", "detail": "high"},
            },
        ]
        messages.append({"role": "user", "content": content})
        return messages

    def predict(
        self,
        instruction: str,
        screenshot_b64: str,
        preprocess_meta: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """
        根据当前截图与任务指令，预测下一步动作。
        preprocess_meta: 预处理器返回的 metadata（如 elements 用于无障碍混合架构）。
        返回 (response_text, actions_list)。
        """
        messages = self._build_messages(instruction, screenshot_b64, preprocess_meta=preprocess_meta)
        response = call_vlm(messages, model=self.model, max_tokens=1024, temperature=0.2)
        actions = parse_actions_from_response(response)
        self.thoughts.append(response)
        self.actions.append(actions)
        return response, actions

    def run(
        self,
        instruction: str,
        on_step: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        执行完整观察-推理-执行循环，直到 DONE/FAIL 或达到 max_steps。
        on_step(step_index, screenshot_b64, response, actions, done) 可选，用于回调（如保存截图、日志）。
        返回：{"success": bool, "reason": "DONE"|"FAIL"|"max_steps", "steps": int, "last_response": str}
        """
        self.reset()
        done_reason = None
        last_response = ""

        for step in range(self.max_steps):
            # 1. 观察：截图后经预处理器得到送 VLM 的图像（可配置 grid / resize_only / 后续扩展 SoM 等）
            raw_screenshot = capture_screenshot(region=None)
            preprocessor = get_preprocessor()
            result = preprocessor.prepare(raw_screenshot, SCREEN_WIDTH, SCREEN_HEIGHT)
            screenshot_b64 = result.image_base64
            self.observations.append({"screenshot": screenshot_b64, "preprocess_meta": result.metadata})

            # 调试：第一步保存送 VLM 的截图，便于核对「模型看到的图」与「实际点击坐标」是否一致
            if DEBUG_SAVE_SCREENSHOT and step == 0:
                try:
                    import base64
                    from pathlib import Path
                    raw = base64.b64decode(screenshot_b64)
                    path = Path("debug_screenshot_0.png")
                    path.write_bytes(raw)
                    logger.info(
                        "已保存送 VLM 的截图到 %s（尺寸=%dx%d，与点击坐标一致），可用其核对坐标准确性",
                        path.resolve(), SCREEN_WIDTH, SCREEN_HEIGHT,
                    )
                except Exception as e:
                    logger.warning("保存调试截图失败: %s", e)

            # 2. 推理：VLM 根据截图与任务预测下一动作（传入本步 preprocess_meta 以便注入可交互元素）
            current_meta = self.observations[-1].get("preprocess_meta") if self.observations else None
            response, actions = self.predict(instruction, screenshot_b64, preprocess_meta=current_meta)
            last_response = response

            # 3. 解析并执行
            if not actions:
                logger.warning("第 %d 步未解析到动作，视为 WAIT", step + 1)
                actions = [{"action_type": "WAIT", "seconds": 1}]

            if on_step:
                try:
                    on_step(step, screenshot_b64, response, actions, done_reason)
                except Exception as e:
                    logger.exception("on_step 回调异常: %s", e)

            # 执行第一个动作（每步只执行一个）
            act = actions[0] if actions else {}
            # CLICK_ELEMENT 使用系统 bbox 不施加偏移；其余点击/移动若与上一步相同则小幅偏移
            action_type_for_skip = (act.get("action_type") or act.get("type") or "").strip().upper()
            if action_type_for_skip != "CLICK_ELEMENT" and len(self.actions) >= 2:
                prev_list = self.actions[-2]
                prev_act = prev_list[0] if prev_list and isinstance(prev_list, list) else prev_list
                if isinstance(prev_act, dict) and _click_like_action_equal(prev_act, act):
                    act = apply_retry_offset(act)
            # 若该动作在最近 6 步内已出现 2 次及以上（重复无效），对点击类施加更大偏移（不含 CLICK_ELEMENT）
            if len(self.actions) >= 2 and isinstance(act, dict) and action_type_for_skip != "CLICK_ELEMENT":
                from collections import Counter
                recent = self.actions[-6:]
                sig = self._action_signature(act)
                at = (act.get("action_type") or act.get("type") or "").strip().upper()
                if sig and at in ("CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "MOVE_TO", "DRAG_TO"):
                    sigs_in_recent = []
                    for al in recent:
                        a = al[0] if al and isinstance(al, list) else al
                        if isinstance(a, dict):
                            s = self._action_signature(a)
                            if s:
                                sigs_in_recent.append(s)
                    if sigs_in_recent.count(sig) >= 2:
                        act = apply_retry_offset(act, pixel_offset=25)
            action_type = (act.get("action_type") or act.get("type") or "").strip().upper()
            if action_type == "DONE":
                done_reason = "DONE"
                break
            if action_type == "FAIL":
                done_reason = "FAIL"
                break

            element_list = (current_meta or {}).get("elements") if current_meta else None
            try:
                should_continue = execute_action(
                    act, step_delay=self.step_delay, element_list=element_list
                )
            except Exception as e:
                logger.exception("执行动作异常，本步跳过: %s", e)
                should_continue = True
            if not should_continue:
                if action_type in ("DONE", "FAIL"):
                    done_reason = action_type
                break

        if done_reason is None:
            done_reason = "max_steps"

        return {
            "success": done_reason == "DONE",
            "reason": done_reason,
            "steps": step + 1,
            "last_response": last_response,
        }
