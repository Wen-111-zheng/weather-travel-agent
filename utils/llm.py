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
from openai import OpenAI

from config import DEEPSEEK_API_KEY, USE_REAL_LLM

SYSTEM_PROMPT = "你是一个专业的天气与出行助手，回答简洁、可执行（actionable），使用中文。"


def _real_chat(messages):
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.3,
    )
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

def chat(messages):
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
