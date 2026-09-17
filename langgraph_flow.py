# -*- coding: utf-8 -*-
"""LangGraph 编排层（阶段三 ③ 升级版）：Supervisor 协调 + Checkpoint 持久化。

相对旧版（线性管道 + 写死 route_intent）的升级点：
1. Supervisor（主管）节点：由 LLM 当"调度主管"，判断走「任务分支」(意图→天气→建议)
   还是「闲聊分支」(兜底)；无 DEEPSEEK_API_KEY 时自动退化为规则路由，离线/演示也能跑。
2. Checkpoint：compile(checkpointer=MemorySaver) 让图状态可跨轮持久，配合 /chat 的
   thread_id 实现真正的多轮对话——上一轮的城市/偏好能被本轮意图识别引用。
3. 多轮上下文：intent 节点会把「上一轮回答」并入意图识别，使"那适合带宝宝吗"这类追问
   能正确解析出城市（从上一轮回答里取），而不是因为没城市而走兜底。

复用 agents/core.py 同一套核心逻辑、MCP/RAG/记忆，框架无关（PocketFlow 路径完全不变）。
"""
from typing import TypedDict, List, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from agents.core import intent, weather, advice, chat
from memory.user_profile import record_query
from config import USE_REAL_LLM
from utils.llm import complete_json


class AgentState(TypedDict):
    question: str
    intent: dict                 # 意图识别结果
    cities: List[str]            # 抽取的城市
    preferences: List[str]       # 抽取的偏好标签
    weather_data: List[dict]     # 各地天气
    answer: str                  # 最终回答；checkpoint 跨轮保留，兼作"上一轮回答"载体
    next: str                    # supervisor 决策：task / chat


# ---------- Supervisor（主管）----------
_CHAT_KW = ["谢谢", "感谢", "拜拜", "再见", "在吗", "你好"]
_WEATHER_KW = ["天气", "气温", "温度", "穿衣", "出行", "适合", "带宝宝", "带老人",
               "城市", "下雨", "风", "冷", "热", "防晒", "骑行", "通勤", "对比", "穿什么"]


def _supervisor_decision(question: str, prior_answer: str) -> str:
    """LLM 当主管判断走 task（意图→天气→建议）还是 chat（闲聊兜底）。
    无真实 LLM 时退化为规则路由。"""
    # 明确闲聊词直接兜底，避免"谢谢"被当成任务又去查一遍天气
    if any(k in question for k in _CHAT_KW):
        return "chat"
    if USE_REAL_LLM:
        q = question
        if prior_answer:
            q = f"【上一轮回答】{prior_answer}\n【本轮问题】{q}"
        prompt = f"""你是天气出行助手的调度主管。判断用户这句话该交给"任务分支"(查天气+给出行建议)还是"闲聊分支"(兜底)。
用户说：{q}
只返回一行 JSON：{{"route":"task"}} 或 {{"route":"chat"}}。
- 含天气/气温/出行/穿衣/城市，或与上文城市相关的追问 -> task
- 纯闲聊/感谢/无关天气 -> chat"""
        try:
            r = complete_json(prompt)
            if r.get("route") in ("task", "chat"):
                return r["route"]
        except Exception:
            pass  # 落规则兜底
    # 规则兜底：天气关键词命中，或已有上文（多半是同一趟出行的追问）-> task
    if any(k in question for k in _WEATHER_KW) or prior_answer:
        return "task"
    return "chat"


def supervisor_node(state: AgentState) -> dict:
    prior = state.get("answer") or ""
    return {"next": _supervisor_decision(state["question"], prior)}


# ---------- 节点（调用 core 逻辑）----------
def intent_node(state: AgentState) -> dict:
    prior = state.get("answer") or ""
    q = state["question"]
    # 多轮：当前问题放最前（mock 意图识别按"用户说："后首行抽取），上一轮回答作上下文附后，
    # 使追问能解析出城市；真实 LLM 也能看到上下文。
    if prior:
        q = f"{q}\n【上一轮回答】{prior}"
    res = intent(q)
    cities = res.get("cities", []) or []
    prefs = res.get("preferences", []) or []
    # 多轮兜底：本轮没抽到城市/偏好，但上一轮有 -> 继承（追问常省略城市，如"那适合带宝宝吗"）
    if not cities and state.get("cities"):
        cities = state["cities"]
    if not prefs and state.get("preferences"):
        prefs = state["preferences"]
    return {"intent": res, "cities": cities, "preferences": prefs}


def weather_node(state: AgentState) -> dict:
    data = weather(state["cities"])
    for c, w in zip(state["cities"], data):
        if not w.get("fallback"):
            record_query(c, state["preferences"])
    return {"weather_data": data}


def advice_node(state: AgentState) -> dict:
    return {"answer": advice(state["weather_data"], state["preferences"])}


def chat_node(state: AgentState) -> dict:
    return {"answer": chat(state["question"])}


# ---------- 构图 ----------
def create_langgraph_app(checkpointer=None):
    """构建并编译 LangGraph 应用；checkpointer 非空时状态跨轮持久（按 thread_id 隔离）。"""
    g = StateGraph(AgentState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("intent", intent_node)
    g.add_node("weather", weather_node)
    g.add_node("advice", advice_node)
    g.add_node("chat", chat_node)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        lambda s: s["next"],           # 用 state.next 路由（由 supervisor 决策）
        {"task": "intent", "chat": "chat"},
    )
    g.add_edge("intent", "weather")
    g.add_edge("weather", "advice")
    g.add_edge("advice", END)
    g.add_edge("chat", END)
    return g.compile(checkpointer=checkpointer)


def run(query: str, thread_id: str = None, checkpointer=None) -> str:
    """端到端运行：给定用户问题，返回最终回答。
    thread_id 非空 + checkpointer 持久 -> 跨轮共享状态（多轮对话）。
    """
    app = create_langgraph_app(checkpointer or MemorySaver())
    cfg = {"configurable": {"thread_id": thread_id}} if thread_id else None
    if cfg:
        result = app.invoke({"question": query}, config=cfg)
    else:
        result = app.invoke({"question": query})
    return result.get("answer", "")


# 兼容 flow.py 的命名，便于 eval/main 切换框架
create_weather_travel_graph = create_langgraph_app
