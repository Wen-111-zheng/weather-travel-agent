# -*- coding: utf-8 -*-
"""LangGraph 编排层：用 StateGraph 把 4 段 Agent 核心逻辑串成图。

与 PocketFlow 版（flow.py）实现完全相同的业务能力，仅编排范式不同：
- IntentAgent  -> (weather/travel) -> WeatherAgent -> AdviceAgent
- IntentAgent  -> (chat)           -> ChatAgent

LangGraph 范式要点：
- StateGraph(AgentState)：用 TypedDict 定义全局状态（≈ PocketFlow 的 shared store）
- 节点是普通函数，接收 state、返回 partial state 更新（≈ PocketFlow Node 的 post 写回 shared）
- add_conditional_edges + router 函数实现条件路由（≈ PocketFlow 的 action 字符串路由）
- 与 PocketFlow 共用 agents/core.py 的同一套逻辑、MCP/RAG/记忆，证明「核心能力与框架解耦」。
"""
from typing import TypedDict, List, Optional

from langgraph.graph import StateGraph, START, END

from agents.core import intent, weather, advice, chat
from memory.user_profile import record_query


class AgentState(TypedDict):
    question: str
    intent: dict                 # 意图识别结果
    cities: List[str]            # 抽取的城市
    preferences: List[str]       # 抽取的偏好标签
    weather_data: List[dict]     # 各地天气
    answer: str                  # 最终回答


# ---------- 节点（普通函数，调用 core 逻辑）----------
def intent_node(state: AgentState) -> dict:
    res = intent(state["question"])
    return {
        "intent": res,
        "cities": res.get("cities", []),
        "preferences": res.get("preferences", []),
    }


def weather_node(state: AgentState) -> dict:
    data = weather(state["cities"])
    # 写入长期记忆（与 PocketFlow 版行为一致）
    for c, w in zip(state["cities"], data):
        if not w.get("fallback"):
            record_query(c, state["preferences"])
    return {"weather_data": data}


def advice_node(state: AgentState) -> dict:
    return {"answer": advice(state["weather_data"], state["preferences"])}


def chat_node(state: AgentState) -> dict:
    return {"answer": chat(state["question"])}


# ---------- 条件路由（替代 PocketFlow 的 action 字符串）----------
def route_intent(state: AgentState) -> str:
    action = state.get("intent", {}).get("action", "chat")
    # weather / travel 都走「天气 -> 建议」任务分支
    if action in ("weather", "travel"):
        return "weather"
    return "chat"


def create_langgraph_app():
    """构建并编译 LangGraph 应用。"""
    g = StateGraph(AgentState)
    g.add_node("intent", intent_node)
    g.add_node("weather", weather_node)
    g.add_node("advice", advice_node)
    g.add_node("chat", chat_node)

    g.add_edge(START, "intent")
    g.add_conditional_edges(
        "intent", route_intent,
        {"weather": "weather", "chat": "chat"},
    )
    g.add_edge("weather", "advice")
    g.add_edge("advice", END)
    g.add_edge("chat", END)
    return g.compile()


def run(query: str) -> str:
    """端到端运行：给定用户问题，返回最终回答。"""
    app = create_langgraph_app()
    result = app.invoke({"question": query})
    return result.get("answer", "")


# 兼容 flow.py 的命名，便于 eval/main 切换框架
create_weather_travel_graph = create_langgraph_app
