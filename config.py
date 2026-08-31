# -*- coding: utf-8 -*-
"""全局配置：读取环境变量中的大模型 Key，并决定 LLM 运行模式。
- 有 DEEPSEEK_API_KEY：走真实 DeepSeek 大模型
- 无 Key：自动回退到本地启发式（保证离线可跑、可演示、可评测）
"""
import os


def _clean_env(name):
    """读取环境变量并清洗：去掉首尾空白与误带的引号。

    兼容 `set KEY="sk-xxx"`（CMD 下引号会变成值的一部分）这类写法，
    避免 API Key 末尾混入 `"` 导致 401 Authentication Fails。
    """
    val = os.environ.get(name)
    if val is None:
        return None
    return val.strip().strip('"').strip("'").strip()


DEEPSEEK_API_KEY = _clean_env("DEEPSEEK_API_KEY")
SILICONFLOW_API_KEY = _clean_env("SILICONFLOW_API_KEY")

# 是否使用真实大模型（无 key 时为 False，使用 mock 兜底）
USE_REAL_LLM = bool(DEEPSEEK_API_KEY)

# SiliconFlow 用于 RAG 的 embedding（中文 bge-m3）；无 key 时 RAG 回退关键词检索
USE_REAL_EMBEDDING = bool(SILICONFLOW_API_KEY)


def llm_mode():
    return "deepseek" if USE_REAL_LLM else "mock(heuristic)"
