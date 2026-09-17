# -*- coding: utf-8 -*-
"""LLM-as-Judge：用 DeepSeek 当阅卷老师，对单条回答做语义评分。

复用 utils.llm.complete_json（已接 DeepSeek）。无 API Key（mock 模式）时
直接返回 None，评测脚本判 N/A，不崩——与现有 USE_REAL_LLM 行为一致。
"""
from config import USE_REAL_LLM
from utils.llm import complete_json

# 阅卷 system prompt：五维打分(1-5) + 是否可用 + 理由，只输出 JSON
_JUDGE_SYSTEM = """你是天气出行助手的阅卷老师。给定【用户问题】【助手回答】【真实天气数据】【知识库检索片段】，
仅从以下 5 个维度各打 1-5 分，并给出 pass（总体是否可用）与 reason（简短理由）：
- relevance 相关性：是否答到用户点上
- factuality 事实准确性：天气/建议是否编造、是否与真实天气数据一致
- completeness 完整性：该说的点是否说到
- safety 安全性：是否有不当或危险建议
- conciseness 简洁性：是否啰嗦、信息密度是否合适、有无废话
不要编造天气数据。只输出 JSON，不要其他文字。格式：
{"relevance":, "factuality":, "completeness":, "safety":, "conciseness":, "pass":, "reason":""}"""

_cache = {}  # 相同问题不重复评分


def _fmt_weather(weather_data):
    if not weather_data:
        return "（无）"
    return "\n".join(
        f"- {w.get('city', '?')}：{w.get('temp', '?')}，{w.get('condition', '?')}，风速 {w.get('wind', '?')}"
        for w in weather_data
    )


def _fmt_docs(docs):
    if not docs:
        return "（无）"
    return "\n".join(f"- {d.get('text', '')}" for d in docs)


def judge(question, answer, weather_data=None, docs=None):
    """对单条回答评分。返回 dict 或 None（降级/异常）。"""
    if not USE_REAL_LLM:
        return None
    if question in _cache:
        return _cache[question]
    user = (f"【用户问题】{question}\n【助手回答】{answer}\n"
            f"【真实天气数据】{_fmt_weather(weather_data)}\n"
            f"【知识库检索片段】{_fmt_docs(docs)}")
    try:
        r = complete_json(user, system=_JUDGE_SYSTEM)
        out = {
            "relevance": int(r.get("relevance", 0)),
            "factuality": int(r.get("factuality", 0)),
            "completeness": int(r.get("completeness", 0)),
            "safety": int(r.get("safety", 0)),
            "conciseness": int(r.get("conciseness", 0)),
            "pass": bool(r.get("pass", False)),
            "reason": str(r.get("reason", "")),
        }
        _cache[question] = out
        return out
    except Exception:
        return None
