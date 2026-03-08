# GUI Agent

基于视觉语言模型（VLM）的桌面自动化 Agent：根据用户任务与当前屏幕截图，自动执行鼠标、键盘等操作，直至任务完成或达到步数上限。架构与 Prompt 参考 [OSWorld](https://github.com/xlang-ai/OSWorld) 与 [GUI Automation Agent 文档](https://tylerelyt.github.io/test_bed/docs/gui-agent/)。

---

## 功能概述

- **观察**：每步截取当前屏幕，可选网格标注或无障碍树标注
- **推理**：将截图与任务描述发送给 VLM，得到下一步动作（JSON 或 WAIT/DONE/FAIL）
- **执行**：使用 PyAutoGUI 执行点击、输入、滚轮、组合键等；支持按无障碍元素 id/名称精确点击
- **循环**：重复「观察 → 推理 → 执行」直至返回 DONE/FAIL 或达到最大步数

默认使用 **Qwen-VL**（阿里云 DashScope，OpenAI 兼容接口），也可通过环境变量使用其他 VLM（如 GPT-4V）。

---

## 环境要求

- Python >= 3.10
- Windows / macOS / Linux（PyAutoGUI、mss 支持多平台）
- 使用无障碍树模式（`accessibility`）时：Windows 建议安装 `uiautomation` 或 `pywinauto`，用于获取可点击控件列表

---

## 安装

### 使用 uv（推荐）

```bash
cd gui-agent
uv venv

# Windows PowerShell 激活
.venv\Scripts\Activate.ps1

# 安装依赖（不激活时指定 venv 的 Python）
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

### 使用 pip

```bash
cd gui-agent
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1

# Linux / macOS
# source .venv/bin/activate

pip install -r requirements.txt
```

---

## 配置

1. 复制环境变量示例并填写 API Key：

   ```bash
   # Windows
   copy .env.example .env

   # Linux / macOS
   cp .env.example .env
   ```

2. 在 `.env` 中配置（常用项如下）：

   | 变量 | 说明 |
   |------|------|
   | `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key（用于 Qwen-VL） |
   | `OPENAI_API_KEY` | 可选，使用 OpenAI 或其它兼容端点时填写 |
   | `OPENAI_BASE_URL` | 可选，默认 DashScope 兼容端点；OpenAI 直连可设为 `https://api.openai.com/v1` |
   | `GUI_AGENT_VLM_MODEL` | 可选，默认 `qwen-vl-plus` |
   | `GUI_AGENT_SCREEN_WIDTH` / `GUI_AGENT_SCREEN_HEIGHT` | 可选，默认自动获取逻辑分辨率；与点击坐标一致 |
   | `GUI_AGENT_MAX_STEPS` | 可选，单次任务最大步数，默认 30 |
   | `GUI_AGENT_STEP_DELAY` | 可选，每步执行后延迟（秒），默认 1.0 |
   | `GUI_AGENT_IMAGE_PREPROCESSOR` | 可选，`grid`（网格） / `resize_only`（仅缩放） / `accessibility`（无障碍树） |
   | `GUI_AGENT_GRID_ROWS` / `GUI_AGENT_GRID_COLS` | 可选，网格行列数，默认 20x20 |
   | `GUI_AGENT_ANNOTATE_GRID` | 可选，网格模式下是否绘制网格线，默认 true |
   | `GUI_AGENT_ACCESSIBILITY_FOREGROUND_ONLY` | 可选，无障碍模式是否只枚举前台窗口，默认 true |
   | `GUI_AGENT_ACCESSIBILITY_FETCH_ON_CLICK_ONLY` | 可选，是否仅在点击类动作时再获取元素（用 name 解析），默认 true |
   | `GUI_AGENT_DEBUG_SAVE_SCREENSHOT` | 可选，第一步是否保存送 VLM 的截图到 `debug_screenshot_0.png`，默认 false |

3. **坐标准确性与 DPI**（若点击位置有偏差可重点看）：

   - 点击使用 **PyAutoGUI 逻辑分辨率**（`pyautogui.size()`）；送 VLM 的截图由 mss 截取后**缩放到该逻辑尺寸**，保证图上像素与点击坐标 1:1。
   - 模型可输出 **归一化坐标** `norm_x`, `norm_y`（0–1000）或 **网格** `grid_row`, `grid_col` 以减轻误差。
   - 无障碍模式可输出 **CLICK_ELEMENT** + `element_id` 或 `name`，由系统解析控件 bbox 后点击，精度更高。
   - 调试：设 `GUI_AGENT_DEBUG_SAVE_SCREENSHOT=true` 查看第一步送 VLM 的图；运行 `python get_screen_size.py` 查看逻辑尺寸；`python mark_click_position.py 500 300` 可校验坐标 (500,300) 的实际位置。

---

## 使用方式

```bash
# 指定任务直接运行
python run.py --task "打开记事本"

# 从标准输入读取任务（一行）
python run.py

# 指定模型与最大步数
python run.py --task "在桌面新建文件夹" --model qwen-vl-plus --max-steps 20

# 仅打印配置与任务，不调用 API、不执行操作
python run.py --task "打开计算器" --dry-run
```

使用 uv 且未激活虚拟环境时：

```bash
.venv\Scripts\python.exe run.py --task "打开记事本"
```

---

## 动作空间

Agent 每步输出一个动作（JSON），支持类型包括：

| 动作类型 | 说明 | 示例参数 |
|----------|------|----------|
| `CLICK_ELEMENT` | 按无障碍元素点击（id 或 name） | `element_id` 或 `name`（如 `"确定"`） |
| `MOVE_TO` | 移动光标 | `x`, `y` 或 `grid_row`, `grid_col` |
| `CLICK` | 左键单击 | `x`, `y` 或 `grid_row`, `grid_col` |
| `RIGHT_CLICK` | 右键单击 | 同上 |
| `DOUBLE_CLICK` | 双击 | 同上 |
| `DRAG_TO` | 拖拽 | `x`, `y` |
| `SCROLL` | 滚轮 | `dy`（正数向上） |
| `TYPING` | 输入文字 | `text`（末尾 `\n` 会再按 Enter） |
| `PRESS` | 单键 | `key` |
| `HOTKEY` | 组合键 | `keys`（如 `["ctrl", "c"]`） |
| `WAIT` | 等待 | `seconds`（可选） |
| `DONE` | 任务完成 | - |
| `FAIL` | 任务无法完成 | - |

示例：`{"action_type": "CLICK", "grid_row": 10, "grid_col": 12}` 或 `{"action_type": "CLICK_ELEMENT", "name": "确定"}`，也可直接返回 `WAIT` / `DONE` / `FAIL`。

---

## 项目结构

```
gui-agent/
  config.py              # 配置（分辨率、API、步数、预处理与无障碍开关）
  run.py                 # 主入口
  agent.py               # Agent：观察-推理-执行循环与历史
  actions.py              # 动作空间定义、PyAutoGUI 执行、响应解析
  prompts.py              # 系统 Prompt 与步骤 Prompt
  image_preprocessors.py  # 截图预处理（grid / resize_only / accessibility）
  accessibility_providers.py  # 无障碍树元素获取（Windows UIA / pywinauto）
  env_local.py            # 本地环境：截图（mss）、base64、逻辑分辨率
  vlm_client.py           # VLM 调用（DashScope / OpenAI 兼容）
  get_screen_size.py      # 查看当前逻辑屏幕尺寸
  mark_click_position.py  # 调试：在指定坐标画点以核对点击位置
  requirements.txt
  .env.example
  README.md
```

---

## 参考

- [OSWorld](https://github.com/xlang-ai/OSWorld)：多模态 Agent 基准与桌面环境
- [GUI Automation Agent 文档](https://tylerelyt.github.io/test_bed/docs/gui-agent/)：架构与任务执行说明
