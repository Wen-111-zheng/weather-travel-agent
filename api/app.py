# -*- coding: utf-8 -*-
"""FastAPI 服务：把多智能体天气出行助手封装为 HTTP 接口，支持生产环境部署。

端点：
  POST /chat  {"question": "北京天气怎么样，带宝宝", "framework": "pocketflow"|"langgraph", "thread_id": "可选会话ID"}
        -> {"answer": "...", "intent": {...}, "cities": [...], "preferences": [...], "framework": "..."}
  GET  /health -> {"status": "ok"}

阶段三 ② 加固要点：
- PocketFlow 路径：每请求新建 Flow（内部无全局状态，可安全重建），杜绝并发串档；
- 支持 framework 参数（默认 pocketflow：依赖更少、与评测基线一致）；
- 跑完调 clear_temporary_preferences()，避免"带宝宝/带老人"等临时偏好漏给下一轮；
- 统一 state dict 返回，与 eval/run_eval.py 的 run_query 对齐。

阶段三 ③ 升级（langgraph 分支）：
- Supervisor 协调：由 LLM 主管决定走「任务分支」(意图→天气→建议) 还是「闲聊分支」；
- Checkpoint：编译时挂 MemorySaver，状态可跨轮持久；/chat 支持可选 thread_id，
  同一 thread_id 跨轮共享状态（上一轮城市/偏好被本轮引用），不同 thread_id 互不串档；
- LangGraph 用「模块级单例 app + 线程安全 MemorySaver」替代"每请求新建"，
  因为只有持有同一 checkpointer 的实例才能跨轮恢复状态（MemorySaver 线程安全，并发靠 thread_id 隔离）。
"""
import os
import sys
import uuid
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "PocketFlow"))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Weather-Travel Multi-Agent API", version="1.2")


class ChatReq(BaseModel):
    question: str
    framework: str = "pocketflow"  # 默认 pocketflow：依赖更少、与评测基线一致
    thread_id: Optional[str] = None  # 多轮对话：同一 thread_id 跨轮共享状态；为空则每次新建隔离会话


# 阶段三 ③：LangGraph 编译时挂 MemorySaver 检查点，状态跨轮持久（按 thread_id 隔离）。
# 模块级单例 + 线程安全的 MemorySaver：并发请求靠 thread_id 隔离，不会串档。
_LG_APP = None


def _get_langgraph_app():
    """懒初始化 LangGraph 单例（带 MemorySaver 检查点）。"""
    global _LG_APP
    if _LG_APP is None:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph_flow import create_langgraph_app
        _LG_APP = create_langgraph_app(MemorySaver())
    return _LG_APP


def _run(question: str, framework: str, thread_id: str = None) -> dict:
    """按框架跑一轮，返回统一 state dict（与 run_eval.py 的 run_query 等价）。"""
    if framework == "langgraph":
        app = _get_langgraph_app()
        # 不带 thread_id -> 每次生成隔离会话，行为等同旧版单轮；带 -> 跨轮共享状态
        tid = thread_id or f"anon-{uuid.uuid4().hex}"
        cfg = {"configurable": {"thread_id": tid}}
        return app.invoke({"question": question}, config=cfg)
    # 默认 pocketflow：每请求新建 Flow，避免并发串档（flow 内部无全局状态，可安全重建）
    from flow import create_weather_travel_flow
    shared = {"question": question}
    create_weather_travel_flow().run(shared)
    return shared


@app.post("/chat")
def chat(req: ChatReq):
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="question 不能为空")
    if req.framework not in ("pocketflow", "langgraph"):
        raise HTTPException(status_code=400, detail="framework 仅支持 pocketflow / langgraph")
    try:
        st = _run(q, req.framework, req.thread_id)
    except Exception as e:  # 不让内部异常裸奔，统一转为 500
        raise HTTPException(status_code=500, detail=f"agent 运行失败: {e}")
    # 跑完清掉"带宝宝/带老人"等临时上下文偏好，避免污染下一轮（与 main.py 一致）
    from memory.user_profile import clear_temporary_preferences
    clear_temporary_preferences()
    return {
        "answer": st.get("answer", ""),
        "intent": st.get("intent"),
        "cities": st.get("cities"),
        "preferences": st.get("preferences"),
        "framework": req.framework,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
