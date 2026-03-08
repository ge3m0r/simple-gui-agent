# -*- coding: utf-8 -*-
"""GUI Agent 系统 Prompt，结构化：最终目标、当前目标、历史动作、可用工具、期望回答。"""

from typing import Any, Dict, List, Optional

from config import SCREEN_WIDTH, SCREEN_HEIGHT, GRID_ROWS, GRID_COLS

X_MAX = SCREEN_WIDTH
Y_MAX = SCREEN_HEIGHT

# 动作空间 JSON 格式说明；顺序上先列「规划常用」的快捷键/输入，再列点击，避免模型默认倾向点击
ACTION_JSON_EXAMPLES = f"""
- 组合键（打开入口、复制粘贴、切换输入法等，必须用 HOTKEY）: {{"action_type": "HOTKEY", "keys": ["win", "r"]}} 打开运行，{{"action_type": "HOTKEY", "keys": ["ctrl", "c"]}} 复制；切换输入法用 ["ctrl", "space"] 或 ["win", "space"]
- 输入文字（仅普通字符）: {{"action_type": "TYPING", "text": "notepad"}}。输入英文/URL/命令前若当前可能是中文输入法，先一步 HOTKEY 切到英文再 TYPING；输入中文前先一步切到中文输入法
- 单键: {{"action_type": "PRESS", "key": "enter"}}
- 等待: {{"action_type": "WAIT", "seconds": 2}}
- 按元素 id 点击（当存在【可交互元素】时用，精度高）: {{"action_type": "CLICK_ELEMENT", "element_id": 5}}
- 网格点击（{GRID_ROWS}行x{GRID_COLS}列，grid_row/grid_col 取 0～{GRID_ROWS-1}/0～{GRID_COLS-1}）: {{"action_type": "CLICK", "grid_row": 10, "grid_col": 12}}
- 移动/左键/右键/双击/拖拽: {{"action_type": "MOVE_TO", "grid_row": 2, "grid_col": 4}}、{{"action_type": "CLICK", "x": 500, "y": 300}}、{{"action_type": "RIGHT_CLICK"}}、{{"action_type": "DOUBLE_CLICK"}}、{{"action_type": "DRAG_TO", "grid_row": 4, "grid_col": 6}}
- 归一化坐标（0-1000）: {{"action_type": "CLICK", "norm_x": 500, "norm_y": 300}}
- 滚轮: {{"action_type": "SCROLL", "dy": 3}} 或 {{"action_type": "SCROLL", "dy": -3}}
- 任务完成/无法完成: {{"action_type": "DONE"}}、{{"action_type": "FAIL"}}
"""

# 无障碍树模式专用（每步传元素列表时）：用 element_id 点击；顺序上先列规划常用 HOTKEY/TYPING
ACTION_JSON_EXAMPLES_ACCESSIBILITY = """
- 组合键（打开入口、切换输入法）: {"action_type": "HOTKEY", "keys": ["win", "r"]} 或 ["ctrl", "space"] 切英文
- 输入文字: {"action_type": "TYPING", "text": "notepad"}。输入英文/URL/命令前先一步 HOTKEY 切英文；输入中文前先一步切中文
- 单键: {"action_type": "PRESS", "key": "enter"}
- 等待: {"action_type": "WAIT", "seconds": 2}
- 点击控件（需点击时用）: {"action_type": "CLICK_ELEMENT", "element_id": N}，N 为【可交互元素】中的 id
- 滚轮: {"action_type": "SCROLL", "dy": 3} 或 {"action_type": "SCROLL", "dy": -3}
- 任务完成/无法完成: {"action_type": "DONE"}、{"action_type": "FAIL"}
"""

# 无障碍树按需模式（不传元素列表，仅当需要点击时用控件名称）：用 name 指定要点击的控件
ACTION_JSON_EXAMPLES_ACCESSIBILITY_BY_NAME = """
- 组合键（打开入口、切换输入法）: {"action_type": "HOTKEY", "keys": ["win", "r"]} 或 ["ctrl", "space"] 切英文
- 输入文字: {"action_type": "TYPING", "text": "notepad"}。输入英文/URL/命令前先一步 HOTKEY 切英文；输入中文前先一步切中文
- 单键: {"action_type": "PRESS", "key": "enter"}
- 等待: {"action_type": "WAIT", "seconds": 2}
- 点击控件（需点击时用）: {"action_type": "CLICK_ELEMENT", "name": "确定"} 等，name 为控件上显示的文字
- 滚轮: {"action_type": "SCROLL", "dy": 3} 或 {"action_type": "SCROLL", "dy": -3}
- 任务完成/无法完成: {"action_type": "DONE"}、{"action_type": "FAIL"}
"""

# 系统角色与规则（不含任务与历史，由 agent 拼接）
SYS_PROMPT_SCREENSHOT_ACTION = f"""
你是一个桌面自动化助手。根据「最终目标」「当前目标」和「历史动作及执行情况」，结合当前截图，决定下一步的单一操作。

【决策顺序 - 先规划再选动作】
1. 先根据当前截图判断界面状态：是桌面/无目标窗口、已有运行框或搜索框、已有输入框获得焦点、已有弹窗等。
2. 再选择最合适的动作类型，不要默认选点击。冷启动（第一步或当前为桌面）时，优先用 HOTKEY（如 ["win", "r"] 打开运行、["win", "s"] 搜索）或 TYPING 打开入口；等目标窗口/输入框/按钮出现后，再使用 CLICK 或 CLICK_ELEMENT。
3. 需要点击时再使用网格或坐标；不需要点击时不要输出点击动作。

【坐标系统 - 点击时遵守】
- 截图宽度 {X_MAX}、高度 {Y_MAX} 像素，与点击坐标 1:1。网格：{GRID_ROWS} 行 x {GRID_COLS} 列，grid_row 0～{GRID_ROWS-1}、grid_col 0～{GRID_COLS-1}。也可用 x,y 或 norm_x,norm_y（0-1000）。

重要规则：
1. 组合键必须用 HOTKEY（keys 为列表如 ["win", "r"]），TYPING 仅用于输入可见字符。
2. 在输入框（地址栏、搜索框、运行框等）中输入时：系统会先清空该输入框再输入你给出的 text，直接输出 TYPING 即可，无需先发 Ctrl+A。
3. 输入法：要输入英文、URL、运行命令、路径、程序名等时，若当前可能为中文输入法，须先一步 HOTKEY 切换到英文（如 ["ctrl", "space"] 或 ["win", "space"]），下一步再 TYPING；要输入中文时，先一步切换到中文输入法再 TYPING。
4. 每步只输出一个动作的 JSON，用 ```json ... ``` 包裹或直接输出合法 JSON。
5. 若上一步已执行但当前截图未达到预期，不得重复同一动作，须换方式（快捷键/输入/不同点击）或返回 FAIL。
6. 任务完成返回 DONE；无法完成返回 FAIL。
7. 需要点击时优先 grid_row、grid_col；某位置多次未命中须换格子或换方式或 FAIL。
""".strip()

# 无障碍树模式专用系统提示（传元素列表时）：点击用 element_id
SYS_PROMPT_ACCESSIBILITY = """
你是一个桌面自动化助手。根据「最终目标」「当前目标」和「历史动作及执行情况」，结合当前截图与【可交互元素】列表，决定下一步的单一操作。

【决策顺序 - 先规划再选动作】
1. 先根据当前截图判断界面状态（桌面/无目标窗口、运行框已打开、输入框已出现、弹窗中有按钮等）。
2. 再选动作类型，不要默认选点击。冷启动或当前为桌面时，优先 HOTKEY（如 ["win", "r"]）、TYPING 打开入口；等目标窗口或可点击控件出现后再用 CLICK_ELEMENT。
3. 需要点击时使用 {"action_type": "CLICK_ELEMENT", "element_id": N}，N 为【可交互元素】中的 id；不需要点击时用 TYPING、HOTKEY、PRESS、SCROLL、WAIT、DONE、FAIL。

重要规则：
1. 组合键必须用 HOTKEY，keys 为列表如 ["win", "r"]；TYPING 仅用于输入可见字符。
2. 在输入框（地址栏、搜索框等）中输入时：系统会先清空该输入框再输入你给出的 text，直接输出 TYPING 即可。
3. 输入法：输入英文/URL/命令前若可能为中文输入法，先一步 HOTKEY（如 ["ctrl", "space"]）切英文再 TYPING；输入中文前先一步切中文。
4. 每步只输出一个动作的 JSON，用 ```json ... ``` 包裹或直接输出合法 JSON。
5. 上一步未达到预期时不得重复同一动作，须换方式或返回 FAIL。任务完成返回 DONE；无法完成返回 FAIL。
""".strip()

# 无障碍树按需模式（不传元素列表）：点击时用控件显示的文字 name
SYS_PROMPT_ACCESSIBILITY_BY_NAME = """
你是一个桌面自动化助手。根据「最终目标」「当前目标」和「历史动作及执行情况」，结合当前截图，决定下一步的单一操作。

【决策顺序 - 先规划再选动作】
1. 先根据当前截图判断界面状态（桌面、运行框已打开、输入框出现、弹窗中有按钮等）。
2. 再选动作类型，不要默认选点击。冷启动或当前为桌面时，优先 HOTKEY（如 ["win", "r"]）、TYPING 打开入口；等目标窗口或可点击控件出现后再用 CLICK_ELEMENT + name。
3. 需要点击时使用 {"action_type": "CLICK_ELEMENT", "name": "控件上显示的文字"}，如 {"action_type": "CLICK_ELEMENT", "name": "确定"}；不需要点击时用 TYPING、HOTKEY、PRESS、SCROLL、WAIT、DONE、FAIL。

重要规则：
1. 组合键必须用 HOTKEY，keys 为列表如 ["win", "r"]；TYPING 仅用于输入可见字符。
2. 在输入框（地址栏、搜索框等）中输入时：系统会先清空该输入框再输入你给出的 text，直接输出 TYPING 即可。
3. 输入法：输入英文/URL/命令前若可能为中文输入法，先一步 HOTKEY（如 ["ctrl", "space"]）切英文再 TYPING；输入中文前先一步切中文。
4. 每步只输出一个动作的 JSON，用 ```json ... ``` 包裹或直接输出合法 JSON。
5. 上一步未达到预期时不得重复同一动作，须换方式或返回 FAIL。任务完成返回 DONE；无法完成返回 FAIL。
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
    # 当前目标：强调先判断界面状态、再选动作类型，避免默认选点击
    default_goal = (
        "先根据截图判断当前界面状态（如：桌面、运行框未打开、输入框已出现等），"
        "再决定本步应使用的动作类型（快捷键/输入/点击/等待），不要默认选点击。"
        "若为第一步或当前为桌面，优先考虑用 HOTKEY 或 TYPING 打开入口。"
    )
    blocks = [
        "【1. 最终目标】",
        final_goal,
        "",
        "【2. 当前目标】",
        current_goal_hint or default_goal,
        "",
        "【3. 历史动作及执行情况】",
    ]
    if history_lines:
        blocks.extend(history_lines)
    else:
        blocks.append("（无历史，这是第一步。请根据截图规划本步动作类型，优先用快捷键或输入打开入口，不要盲目点击。）")

    if elements:
        blocks.extend([
            "",
            "【可交互元素】图中已用绿色框与 [id] 标出各控件。点击时必须且仅能使用 CLICK_ELEMENT + element_id，禁止使用 grid_row、grid_col、x、y、norm_x、norm_y。",
            format_elements_for_prompt(elements),
        ])

    expect = expected_output_hint or "根据当前界面选择最合适的一个动作（先规划类型再输出）。仅输出一个动作的 JSON，或 WAIT/DONE/FAIL。不要重复上一步无效的动作。"
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
