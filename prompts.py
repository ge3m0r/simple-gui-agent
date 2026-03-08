# -*- coding: utf-8 -*-
"""GUI Agent 系统 Prompt，结构化：最终目标、当前目标、历史动作、可用工具、期望回答。"""

from typing import Any, Dict, List, Optional

from config import SCREEN_WIDTH, SCREEN_HEIGHT, GRID_ROWS, GRID_COLS

X_MAX = SCREEN_WIDTH
Y_MAX = SCREEN_HEIGHT

# 动作空间 JSON 格式说明（点击类优先推荐网格坐标，输出空间小、命中率高）
ACTION_JSON_EXAMPLES = f"""
- 按元素 id 点击（当存在【可交互元素】时最推荐，精度最高）: {{"action_type": "CLICK_ELEMENT", "element_id": 5}} 表示点击列表中 id 为 5 的控件
- 网格坐标: {GRID_ROWS} 行 x {GRID_COLS} 列，grid_row 取 0～{GRID_ROWS-1}、grid_col 取 0～{GRID_COLS-1}。例如 {{"action_type": "CLICK", "grid_row": 10, "grid_col": 12}}
- 移动光标: {{"action_type": "MOVE_TO", "x": 100, "y": 200}} 或 {{"action_type": "MOVE_TO", "grid_row": 2, "grid_col": 4}}
- 左键单击: {{"action_type": "CLICK", "grid_row": 1, "grid_col": 2}} 或 {{"action_type": "CLICK", "x": 500, "y": 300}}
- 右键/双击: {{"action_type": "RIGHT_CLICK", "grid_row": 0, "grid_col": 0}}、{{"action_type": "DOUBLE_CLICK", "grid_row": 5, "grid_col": 5}}
- 拖拽: {{"action_type": "DRAG_TO", "grid_row": 4, "grid_col": 6}}
- 归一化坐标（0-1000）: {{"action_type": "CLICK", "norm_x": 500, "norm_y": 300}} 表示水平50%、垂直30%
- 滚轮: {{"action_type": "SCROLL", "dy": 3}} 或 {{"action_type": "SCROLL", "dy": -3}}
- 输入文字（仅普通字符）: {{"action_type": "TYPING", "text": "notepad"}}
- 单键: {{"action_type": "PRESS", "key": "enter"}}
- 组合键（必须用 HOTKEY）: {{"action_type": "HOTKEY", "keys": ["ctrl", "c"]}} 或 ["win", "r"] 打开运行
- 等待: {{"action_type": "WAIT", "seconds": 2}}
- 任务完成: {{"action_type": "DONE"}}
- 任务无法完成: {{"action_type": "FAIL"}}
"""

# 无障碍树模式专用（每步传元素列表时）：用 element_id 点击
ACTION_JSON_EXAMPLES_ACCESSIBILITY = """
- 点击控件（唯一方式）: {"action_type": "CLICK_ELEMENT", "element_id": N}，N 为【可交互元素】列表中的 id，禁止使用 CLICK、grid_row、grid_col、x、y、norm
- 输入文字: {"action_type": "TYPING", "text": "notepad"}
- 单键: {"action_type": "PRESS", "key": "enter"}
- 组合键: {"action_type": "HOTKEY", "keys": ["ctrl", "c"]} 或 ["win", "r"]
- 滚轮: {"action_type": "SCROLL", "dy": 3} 或 {"action_type": "SCROLL", "dy": -3}
- 等待: {"action_type": "WAIT", "seconds": 2}
- 任务完成: {"action_type": "DONE"}
- 任务无法完成: {"action_type": "FAIL"}
"""

# 无障碍树按需模式（不传元素列表，仅当需要点击时用控件名称）：用 name 指定要点击的控件
ACTION_JSON_EXAMPLES_ACCESSIBILITY_BY_NAME = """
- 点击控件: {"action_type": "CLICK_ELEMENT", "name": "控件上显示的文字"}，如 {"action_type": "CLICK_ELEMENT", "name": "确定"}。禁止使用 CLICK、grid_row、grid_col、x、y、norm
- 输入文字: {"action_type": "TYPING", "text": "notepad"}
- 单键: {"action_type": "PRESS", "key": "enter"}
- 组合键: {"action_type": "HOTKEY", "keys": ["ctrl", "c"]} 或 ["win", "r"]
- 滚轮: {"action_type": "SCROLL", "dy": 3} 或 {"action_type": "SCROLL", "dy": -3}
- 等待: {"action_type": "WAIT", "seconds": 2}
- 任务完成: {"action_type": "DONE"}
- 任务无法完成: {"action_type": "FAIL"}
"""

# 系统角色与规则（不含任务与历史，由 agent 拼接）
SYS_PROMPT_SCREENSHOT_ACTION = f"""
你是一个桌面自动化助手。根据「最终目标」「当前目标」和「历史动作及执行情况」，结合当前截图，决定下一步的单一操作。

【坐标系统 - 务必遵守】
- 你看到的截图宽度为 {X_MAX} 像素、高度为 {Y_MAX} 像素。执行点击时使用的就是该坐标系，二者 1:1 对应。
- 方式一（最推荐，网格）：屏幕划分为 {GRID_ROWS} 行 x {GRID_COLS} 列，每格对应较小屏幕区域。grid_row 取值 0 到 {GRID_ROWS-1}，grid_col 取值 0 到 {GRID_COLS-1}。请选择「包含目标控件中心」的那一格，图中每个格子已标为 row,col，系统会点击该格子中心。
- 方式二（像素）：使用 x, y，0 <= x <= {X_MAX}, 0 <= y <= {Y_MAX}。
- 方式三（比例）：使用 norm_x, norm_y，取值 [0, 1000]。norm_x=500 为水平 50%，norm_y=300 为垂直 30%。

重要规则：
1. 组合键（如 Win+R、Ctrl+C）必须用 HOTKEY，keys 为列表如 ["win", "r"]，不能用 TYPING；TYPING 仅用于输入可见字符。
2. 每步只输出一个动作的 JSON，用 ```json ... ``` 包裹或直接输出合法 JSON。
3. 若上一步已执行但当前截图显示未达到预期（如弹窗未出现、点击无反应、界面无变化），不得重复同一动作（相同 action_type 与相同 x/y 或 norm_x/norm_y）。必须换方式：换点击坐标、用快捷键、右键菜单、其它区域，或返回 FAIL。
4. 确认任务已完成后返回 DONE；确实无法完成时返回 FAIL。
5. 需要点击/移动时，优先使用 grid_row、grid_col（网格索引），其次 norm_x/norm_y 或 x/y。网格方式将「回归坐标」变为「选择格子」，显著提高命中率。
6. 若某格子或坐标多次点击均未命中，请换相邻格子、换方式（键盘/右键）或返回 FAIL，勿反复使用同一位置。
""".strip()

# 无障碍树模式专用系统提示（传元素列表时）：点击用 element_id
SYS_PROMPT_ACCESSIBILITY = """
你是一个桌面自动化助手。根据「最终目标」「当前目标」和「历史动作及执行情况」，结合当前截图与【可交互元素】列表，决定下一步的单一操作。

【无障碍树模式 - 务必遵守】
- 每步用户消息会附带【可交互元素】列表（id | name | role），截图中已用绿色框与 [id] 标出各控件。
- 需要点击界面上的按钮、链接、输入框等控件时，必须且仅能使用 {"action_type": "CLICK_ELEMENT", "element_id": N}，N 为列表中该控件的 id。禁止使用 CLICK、grid_row、grid_col、x、y、norm_x、norm_y 等任何坐标形式。
- 不需要点击时可使用 TYPING、HOTKEY、PRESS、SCROLL、WAIT、DONE、FAIL。

重要规则：
1. 组合键（如 Win+R、Ctrl+C）必须用 HOTKEY，keys 为列表如 ["win", "r"]，不能用 TYPING；TYPING 仅用于输入可见字符。
2. 每步只输出一个动作的 JSON，用 ```json ... ``` 包裹或直接输出合法 JSON。
3. 若上一步已执行但当前截图显示未达到预期，不得重复同一动作，须换 element_id 或换方式或返回 FAIL。
4. 确认任务已完成后返回 DONE；确实无法完成时返回 FAIL。
""".strip()

# 无障碍树按需模式（不传元素列表）：点击时用控件显示的文字 name
SYS_PROMPT_ACCESSIBILITY_BY_NAME = """
你是一个桌面自动化助手。根据「最终目标」「当前目标」和「历史动作及执行情况」，结合当前截图，决定下一步的单一操作。

【无障碍树按需模式 - 务必遵守】
- 需要点击界面上的按钮、链接、输入框等控件时，使用 {"action_type": "CLICK_ELEMENT", "name": "控件上显示的文字"}，例如 {"action_type": "CLICK_ELEMENT", "name": "确定"}。name 填写该控件在界面上可见的文本（按钮文字、链接文字等）。禁止使用 CLICK、grid_row、grid_col、x、y、norm_x、norm_y 等任何坐标形式。
- 不需要点击时可使用 TYPING、HOTKEY、PRESS、SCROLL、WAIT、DONE、FAIL。

重要规则：
1. 组合键（如 Win+R、Ctrl+C）必须用 HOTKEY，keys 为列表如 ["win", "r"]，不能用 TYPING；TYPING 仅用于输入可见字符。
2. 每步只输出一个动作的 JSON，用 ```json ... ``` 包裹或直接输出合法 JSON。
3. 若上一步已执行但当前截图显示未达到预期，不得重复同一动作，须换 name 或换方式或返回 FAIL。
4. 确认任务已完成后返回 DONE；确实无法完成时返回 FAIL。
""".strip()

# 可用工具描述（当前仅截图+键盘鼠标，预留扩展）
AVAILABLE_TOOLS_DESC = """
可用工具：当前仅支持通过动作空间操作（鼠标、键盘、等待）。无额外工具。
"""


def format_elements_for_prompt(elements: List[Dict[str, Any]], max_items: int = 80) -> str:
    """将无障碍元素列表格式化为 prompt 中的【可交互元素】文本。"""
    if not elements:
        return ""
    lines = ["id | name | role"]
    for el in elements[:max_items]:
        eid = el.get("id", "")
        name = (el.get("name") or "")[:40]
        role = el.get("role", "")
        lines.append(f"{eid} | {name} | {role}")
    if len(elements) > max_items:
        lines.append(f"... 共 {len(elements)} 项，仅展示前 {max_items} 项")
    return "\n".join(lines)


def build_step_prompt(
    final_goal: str,
    current_goal_hint: str,
    history_lines: list,
    expected_output_hint: str,
    last_action_no_repeat: Optional[str] = None,
    repeated_action_force_hint: Optional[str] = None,
    elements: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    构建单步请求的文本部分（不含截图）。
    history_lines: 每项为一行字符串，如 "步骤1: 已执行 CLICK (100,200); 界面未出现预期变化"
    last_action_no_repeat: 若提供，追加到期望回答中，明确上一步动作且要求本步勿重复
    repeated_action_force_hint: 若提供，表示最近多步内已重复某操作多次，本步必须换方式或 FAIL
    elements: 无障碍树可交互元素列表（混合架构）；若提供则加入【可交互元素】并优先使用 CLICK_ELEMENT
    """
    blocks = [
        "【1. 最终目标】",
        final_goal,
        "",
        "【2. 当前目标】",
        current_goal_hint or "根据截图与历史，推断当前应完成的子目标（如：打开运行对话框、在输入框输入内容等）。",
        "",
        "【3. 历史动作及执行情况】",
    ]
    if history_lines:
        blocks.extend(history_lines)
    else:
        blocks.append("（无历史，这是第一步。）")

    if elements:
        blocks.extend([
            "",
            "【可交互元素】图中已用绿色框与 [id] 标出各控件。点击时必须且仅能使用 CLICK_ELEMENT + element_id，禁止使用 grid_row、grid_col、x、y、norm_x、norm_y。",
            format_elements_for_prompt(elements),
        ])

    expect = expected_output_hint or "仅输出一个动作的 JSON，或 WAIT/DONE/FAIL。不要重复上一步无效的动作。"
    if elements:
        expect = (
            "【无障碍树模式】需要点击时只能输出 {\"action_type\": \"CLICK_ELEMENT\", \"element_id\": N}（N 为上方列表中的 id），禁止输出 CLICK 与 grid_row/grid_col/x/y/norm。\n"
            + expect
        )
    if repeated_action_force_hint:
        expect = "【重要】" + repeated_action_force_hint + "\n" + expect
    if last_action_no_repeat:
        expect = expect + "\n" + last_action_no_repeat
    blocks.extend([
        "",
        "【4. 可用工具】",
        AVAILABLE_TOOLS_DESC.strip(),
        "",
        "【5. 期望回答】",
        expect,
    ])
    return "\n".join(blocks)


def get_task_system_suffix(instruction: str, action_mode: Optional[str] = None, accessibility_by_name: bool = False) -> str:
    """系统消息中任务相关后缀：最终目标 + 动作示例。action_mode==accessibility 时用无障碍专用示例；accessibility_by_name 为 True 时用按 name 点击的示例。"""
    if (action_mode or "").strip().lower() == "accessibility":
        examples = ACTION_JSON_EXAMPLES_ACCESSIBILITY_BY_NAME.strip() if accessibility_by_name else ACTION_JSON_EXAMPLES_ACCESSIBILITY.strip()
    else:
        examples = ACTION_JSON_EXAMPLES.strip()
    return (
        f"用户给出的最终目标：{instruction}\n\n"
        "可选动作格式（每步仅输出一个）：\n" + examples
    )


def get_system_text(instruction: str, action_mode: Optional[str] = None, elements: Optional[List[Dict[str, Any]]] = None) -> str:
    """根据 action_mode 与 elements 返回完整系统消息。无障碍且无元素列表时使用按 name 点击的提示。"""
    mode = (action_mode or "").strip().lower()
    if mode == "accessibility":
        use_by_name = not elements or len(elements) == 0
        prompt = SYS_PROMPT_ACCESSIBILITY_BY_NAME if use_by_name else SYS_PROMPT_ACCESSIBILITY
        return prompt + "\n\n" + get_task_system_suffix(instruction, "accessibility", accessibility_by_name=use_by_name)
    return SYS_PROMPT_SCREENSHOT_ACTION + "\n\n" + get_task_system_suffix(instruction, None)
