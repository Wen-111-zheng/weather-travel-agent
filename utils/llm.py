# -*- coding: utf-8 -*-
"""LLM 调用适配层。

设计目标：
1. 生产环境用 DeepSeek 真实大模型（chat.completions）。
2. 无 Key / 离线环境自动回退到本地启发式（mock），保证工程可跑、可演示、可评测，
   而不是一没网就崩溃——这是 Agent 工程化"优雅降级"的一部分。
"""
import os
import re
import json
import threading
from openai import OpenAI

from config import DEEPSEEK_API_KEY, USE_REAL_LLM
from tracing import trace

SYSTEM_PROMPT = "你是一个专业的天气与出行助手，回答简洁、可执行（actionable），使用中文。"

MODEL_NAME = "deepseek-chat"


def _accumulate_tokens(prompt_tokens, completion_tokens, model=MODEL_NAME):
    """把一次调用的 token 用量累加到全局计数器（线程安全）。"""
    with _token_lock:
        _token_totals["prompt_tokens"] += prompt_tokens
        _token_totals["completion_tokens"] += completion_tokens
        _token_totals["calls"] += 1
        m = _token_totals["by_model"].setdefault(model, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
        m["prompt_tokens"] += prompt_tokens
        m["completion_tokens"] += completion_tokens
        m["calls"] += 1


def reset_token_usage():
    """清空 token 累加器。评测跑题前调用，保证只统计本轮。"""
    with _token_lock:
        _token_totals["prompt_tokens"] = 0
        _token_totals["completion_tokens"] = 0
        _token_totals["calls"] = 0
        _token_totals["by_model"] = {}


def get_token_usage():
    """返回本轮累计的 token 用量快照（线程安全拷贝）。"""
    with _token_lock:
        return {
            "prompt_tokens": _token_totals["prompt_tokens"],
            "completion_tokens": _token_totals["completion_tokens"],
            "calls": _token_totals["calls"],
            "by_model": {k: dict(v) for k, v in _token_totals["by_model"].items()},
        }


def _record_usage(resp, model=MODEL_NAME):
    """记录本次调用的 token 用量，做两件事：

    1) 【始终执行】累加到全局 token 累加器，供评测成本统计——
       即使 AGENT_TRACE 关闭也能统计，解决原来"关 trace 就丢 token 数据"的问题。
    2) 【受 AGENT_TRACE 控制】若追踪开着，把用量写进当前 span（原逻辑）。
    统计失败绝不抛异常影响主流程。
    """
    try:
        u = getattr(resp, "usage", None)
        if u is not None:
            p = getattr(u, "prompt_tokens", 0) or 0
            c = getattr(u, "completion_tokens", 0) or 0
            _accumulate_tokens(p, c, model)
    except Exception:
        pass

    try:
        from tracing import enabled, current_span
        if not enabled():
            return
        s = current_span()
        if s is None:
            return
        if u is not None:
            s.model = model
            s.prompt_tokens = getattr(u, "prompt_tokens", None)
            s.completion_tokens = getattr(u, "completion_tokens", None)
    except Exception:
        pass  # 统计失败绝不能影响主流程


_client = None        # 全局复用，避免每次调用都重建客户端 + 重读 230KB 证书库（Windows 偶发卡顿根因）
_client_lock = threading.Lock()

# ---------- Token 用量累加器（始终开启，供评测成本统计；与 AGENT_TRACE 开关无关）----------
# 并发评测时多个线程同时累加，必须用锁保护；DeepSeek 价格另见 eval/cost.py
_token_lock = threading.Lock()
_token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "by_model": {}}


def _get_client():
    """全局唯一的 OpenAI 客户端：线程安全懒加载（双重检查锁定）。

    只在第一次真实调用时创建，之后复用。加锁原因：
    `if _client is None` 属于 check-then-act，多线程并发时存在竞态，
    会建出多个客户端、让复用失去意义。双重检查 = 先无锁快路径判断，
    再加锁二次确认，兼顾性能与安全。
    """
    global _client
    if _client is None:                 # 快路径：已创建则无锁直接返回（热路径零开销）
        with _client_lock:
            if _client is None:         # 拿到锁后二次确认，避免并发重复创建
                _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com", timeout=30)
    return _client


def _real_chat(messages):
    client = _get_client()
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.3,
    )
    _record_usage(resp)
    return resp.choices[0].message.content.strip()


# ---------- 离线启发式（mock） ----------

def _extract_question(prompt):
    """从意图分类 prompt 中抠出用户原话，避免被指令文本干扰。"""
    m = re.search(r'用户说[:：]?\s*(.+)', prompt)
    q = m.group(1) if m else prompt
    return q.split("\n")[0].strip()


def _mock_intent(prompt):
    q = _extract_question(prompt)
    mc = re.search(r'([\u4e00-\u9fa5]{2,8}?)(?:的|天气|出行|建议|温度|气温|怎么样|如何)', q)
    city = mc.group(1) if mc else "北京"
    if any(k in q for k in ["建议", "穿", "出行", "带什么", "注意"]):
        prefs = []
        if "宝宝" in q: prefs.append("带宝宝")
        if "骑行" in q: prefs.append("骑行")
        if "通勤" in q: prefs.append("通勤")
        if "防晒" in q: prefs.append("防晒")
        if "老人" in q: prefs.append("陪老人")
        return {"action": "travel", "cities": [city], "preferences": prefs}
    if any(k in q for k in ["天气", "气温", "温度", "多少度", "下雨", "冷", "热", "怎么样", "如何"]):
        return {"action": "weather", "cities": [city]}
    return {"action": "chat"}


def _mock_answer(prompt):
    """根据 AdviceAgent 拼装的天气文本行，生成可执行的出行建议（离线版）。"""
    lines = [l for l in prompt.splitlines() if l.startswith("城市：")]
    if not lines:
        return "（离线模拟）已结合实时天气与知识库生成出行建议；联网后由大模型给出更自然表述。"
    out = []
    for l in lines:
        m = re.search(
            r'城市：([\u4e00-\u9fa5]+)[，,]\s*温度\s*([0-9.\-]+°?C?)[，,]\s*([\u4e00-\u9fa5]+)[，,]\s*风速\s*([0-9.]+\s*km/h)',
            l,
        )
        if not m:
            out.append(f"（{l}）建议出行前关注最新天气预报。")
            continue
        city, temp, cond, wind = m.group(1), m.group(2), m.group(3), m.group(4)
        advice = "建议根据天气适时增减衣物，关注最新预报。"
        t = temp.replace("°C", "").replace("-", "").replace(".", "")
        try:
            tv = float(temp.replace("°C", ""))
        except Exception:
            tv = None
        if "雨" in cond:
            advice = "有降雨，建议携带雨具、注意路面湿滑。"
        elif "雪" in cond:
            advice = "有降雪，注意保暖与道路结冰。"
        elif tv is not None and tv >= 33:
            advice = "高温天气，注意防暑补水、避免正午长时间户外。"
        elif tv is not None and tv <= 5:
            advice = "气温偏低，注意保暖头部与四肢。"
        out.append(f"【{city}】当前 {temp}，{cond}，风速 {wind}。{advice}")
    return "\n".join(out)


# ---------- 对外接口 ----------

@trace("LLM调用", kind="llm", capture_input=False)
def chat(messages):
    # 只记最后一条用户消息：system prompt 每次都一样，记进去纯占空间
    from tracing import current_span
    s = current_span()
    if s is not None:
        s.input_text = str(messages[-1]["content"])[:500]

    if USE_REAL_LLM:
        return _real_chat(messages)
    last = messages[-1]["content"]
    # 意图分类请求里含"action"，走意图解析；否则走回答生成
    if "action" in last and ("天气" in last or "建议" in last or "意图" in last or "城市" in last):
        return json.dumps(_mock_intent(last), ensure_ascii=False)
    return _mock_answer(last)


def complete(prompt, system=SYSTEM_PROMPT):
    return chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}])


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```json ... ``` 代码围栏
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.lower().startswith("json"):
                text = text[4:]
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {"action": "chat"}


def complete_json(prompt, system=SYSTEM_PROMPT):
    """返回解析后的 dict（意图分类用）。"""
    return _extract_json(complete(prompt, system))
