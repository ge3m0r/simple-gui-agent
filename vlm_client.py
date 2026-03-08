# -*- coding: utf-8 -*-
"""
VLM 客户端：统一多模型接口。
默认支持 Qwen3-VL（DashScope OpenAI 兼容）、OpenAI GPT-4V，可扩展其他 VL 模型。
"""

import os
import logging
from typing import List, Dict, Any, Optional

from config import (
    DEFAULT_VLM_MODEL,
    DASHSCOPE_API_KEY,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
)

logger = logging.getLogger("gui_agent.vlm")


def _openai_compatible_chat(
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str:
    """使用 OpenAI 兼容 API（含 DashScope 兼容端点）发送多模态对话。"""
    try:
        from openai import OpenAI, AuthenticationError
    except ImportError:
        raise RuntimeError("请安装 openai: pip install openai")

    base_url = OPENAI_BASE_URL.rstrip("/")
    # 使用 DashScope 端点时必须用 DASHSCOPE_API_KEY，否则会 401
    if "dashscope.aliyuncs.com" in base_url:
        api_key = DASHSCOPE_API_KEY
        if not api_key:
            raise ValueError(
                "当前 OPENAI_BASE_URL 为 DashScope，请仅在 .env 中设置 DASHSCOPE_API_KEY（阿里云控制台获取），不要使用 OpenAI 的 Key。"
            )
    else:
        api_key = OPENAI_API_KEY or DASHSCOPE_API_KEY
        if not api_key:
            raise ValueError("请设置 OPENAI_API_KEY 或 DASHSCOPE_API_KEY 环境变量")

    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        return content or ""
    except AuthenticationError:
        logger.error(
            "API Key 认证失败(401)。请检查: 1) .env 中 DASHSCOPE_API_KEY 是否填写正确且无多余空格; "
            "2) 是否在阿里云模型服务灵积(DashScope)控制台创建并启用了 API Key。"
        )
        raise


def _dashscope_native_chat(
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str:
    """使用 DashScope 原生 SDK（适用于部分 Qwen-VL 模型）。"""
    try:
        import dashscope
        from http import HTTPStatus
    except ImportError:
        raise RuntimeError("请安装 dashscope: pip install dashscope")

    if not DASHSCOPE_API_KEY:
        raise ValueError("请设置 DASHSCOPE_API_KEY 环境变量")

    # 将 OpenAI 格式 messages 转为 DashScope 多模态格式
    qwen_messages = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        parts = []
        for part in content:
            if part.get("type") == "text":
                parts.append({"text": part["text"]})
            elif part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if url.startswith("data:image"):
                    # base64 内联：DashScope 支持 image 字段 base64
                    b64 = url.replace("data:image/png;base64,", "").replace("data:image/jpeg;base64,", "")
                    parts.append({"image": f"data:image/png;base64,{b64}"})
                else:
                    parts.append({"image": url})
        qwen_messages.append({"role": role, "content": parts})

    # 多模态对话
    response = dashscope.MultiModalConversation.call(
        model=model,
        messages=qwen_messages,
        result_format="message",
        max_length=max_tokens,
        temperature=temperature,
    )

    if response.status_code != HTTPStatus.OK:
        logger.error("DashScope 调用失败: %s %s", response.code, response.message)
        return ""

    try:
        return response.output["choices"][0]["message"]["content"][0].get("text", "")
    except (KeyError, IndexError, TypeError):
        return str(response.output)


# 模型到后端的映射
OPENAI_COMPATIBLE_PREFIXES = ("qwen", "gpt", "gpt-4", "gpt-4o", "gpt-4v")
DASHSCOPE_NATIVE_MODELS = ("qwen-vl-plus", "qwen-vl-max", "qwen2-vl-7b-instruct", "qwen2-vl-72b-instruct")


def call_vlm(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str:
    """
    统一 VLM 调用入口。
    messages: OpenAI 格式，content 可为 list，含 type=text 与 type=image_url。
    model: 不传则用 config.DEFAULT_VLM_MODEL。
    """
    model = (model or DEFAULT_VLM_MODEL).strip()
    if not model:
        raise ValueError("未指定 VLM 模型")

    # Qwen3-VL 等建议用 OpenAI 兼容端点（DashScope 提供 compatible-mode）
    use_openai_compat = any(model.lower().startswith(p) for p in ("qwen3", "qwen-vl", "qwen2-vl", "gpt"))
    use_openai_compat = use_openai_compat or model in OPENAI_COMPATIBLE_PREFIXES

    if use_openai_compat or not (model in DASHSCOPE_NATIVE_MODELS and DASHSCOPE_API_KEY):
        return _openai_compatible_chat(model, messages, max_tokens=max_tokens, temperature=temperature)
    return _dashscope_native_chat(model, messages, max_tokens=max_tokens, temperature=temperature)
