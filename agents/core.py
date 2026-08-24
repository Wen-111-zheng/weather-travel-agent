# -*- coding: utf-8 -*-
"""Agent 核心逻辑（框架无关）。

把 意图识别 / 天气获取 / 出行建议 / 闲聊 四段逻辑抽成纯函数，
供 PocketFlow 与 LangGraph 两套编排框架共用，保证「单一事实来源」：
同一套 Agent 能力，可分别用不同图编排范式落地。
"""
import re

from utils.llm import complete, complete_json
from mcp.mcp_client import MCPWeatherClient
from rag.knowledge_base import KnowledgeBase
from memory.user_profile import get_profile

kb = KnowledgeBase()


# ---------- 1. 意图识别 ----------
def intent(question):
    """判断意图（weather / travel / chat）并抽取城市与偏好标签。"""
    prompt = f"""用户说：{question}
请判断意图并抽取信息，仅返回一行 JSON（不要其他文字）：
- 问天气或气温：{{"action":"weather","cities":["城市"]}}
- 问出行/穿衣/带什么建议：{{"action":"travel","cities":["城市"],"preferences":["偏好标签"]}}
- 闲聊：{{"action":"chat"}}
可识别多个城市（如"对比北京和上海"）。偏好标签从"带宝宝/骑行/通勤/防晒/过敏/陪老人"等提取。
示例：用户说"北京和上海明天天气怎么样，带宝宝" -> {{"action":"weather","cities":["北京","上海"],"preferences":["带宝宝"]}}"""
    return complete_json(prompt)


# ---------- 2. 天气获取（MCP 工具 + 长期记忆写入）----------
def weather(cities):
    """通过标准 MCP 协议调用 get_weather 工具，返回各城市天气（纯查询，不写记忆）。
    长期记忆写入由编排层（PocketFlow 节点 / LangGraph 节点）负责，保证两套框架行为一致。
    """
    if not cities:
        return []
    client = MCPWeatherClient()
    try:
        data = [client.get_weather(c) for c in cities]
    finally:
        client.close()
    return data


# ---------- 3. 出行建议（RAG 检索增强 + 记忆驱动个性化）----------
def advice(weather_data, preferences=None):
    """综合 实时天气 + RAG 知识库 + 长期记忆(用户偏好) 生成个性化建议。"""
    preferences = preferences or []
    weather_text = "\n".join([
        f"城市：{w.get('city')}，温度 {w.get('temp')}，{w.get('condition')}，风速 {w.get('wind')}"
        for w in weather_data
    ])
    # RAG 检索：把天气情况 + 偏好拼成查询
    query = weather_text + " " + " ".join(preferences)
    docs = kb.retrieve(query, k=3)
    knowledge = "\n".join([f"- {d['text']}" for d in docs])
    profile = get_profile()
    merged_prefs = list(dict.fromkeys(preferences + profile.get("preferences", [])))
    mem = "、".join(merged_prefs) if merged_prefs else "无"

    prompt = f"""根据以下信息，生成简洁、可执行的出行/穿衣建议（中文，分城市说明）：
【天气数据】
{weather_text}
【知识库参考】
{knowledge}
【用户偏好与历史】
{mem}
要求：
1. 结合天气与知识库给出具体建议；
2. 若有降雨/高温/寒冷/大风请明确提醒；
3. 若用户有偏好（如带宝宝、骑行、通勤、防晒）请针对性建议；
4. 不要编造天气数据，基于天气数据作答。"""
    return complete(prompt)


# ---------- 4. 闲聊兜底 ----------
def chat(question):
    """非天气/出行类问题的兜底回答。"""
    return complete(question + "\n（你是天气出行助手，若用户想问天气请提示可以查询城市天气）")
