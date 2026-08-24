# -*- coding: utf-8 -*-
"""评测脚本：对多智能体天气助手跑评测集，输出量化指标。

支持两套编排框架（--framework）：
  - pocketflow （默认，与原版指标基线一致）
  - langgraph

指标：
- task_success_rate   任务成功率（返回有效回答、无工具兜底失败）
- avg_latency_s       平均端到端时延
- intent_accuracy     意图识别准确率
- weather_fallback_rate 天气工具兜底率（越高说明上游越不稳）
- retrieval_accuracy  RAG 检索命中率（检索结果是否覆盖预期知识标签）
- repeat_question_rate 重复提问率（长期记忆生效后的会话指标）
"""
import os
import sys
import json
import time
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "PocketFlow"))

from rag.knowledge_base import KnowledgeBase
from memory.user_profile import reset, record_query, repeat_rate

kb = KnowledgeBase()


def run_query(question, framework):
    """返回统一的 state dict：{question, answer, intent, cities, preferences, weather_data}。"""
    if framework == "langgraph":
        from langgraph_flow import create_langgraph_app
        app = create_langgraph_app()
        state = app.invoke({"question": question})
        state["question"] = question
        return state
    else:
        from flow import create_weather_travel_flow
        flow = create_weather_travel_flow()
        shared = {"question": question}
        flow.run(shared)
        return shared


def run_case(case, framework):
    t0 = time.time()
    st = run_query(case["question"], framework)
    dt = time.time() - t0
    answer = st.get("answer", "")
    intent = st.get("intent", {})
    pred_action = intent.get("action", "chat") if isinstance(intent, dict) else "chat"
    wd = st.get("weather_data", []) or []
    fallback = any(w.get("fallback") for w in wd)
    # 检索命中：直接对问题检索，检查是否覆盖预期标签
    docs = kb.retrieve(case["question"], k=3)
    hit_tags = {d["tag"] for d in docs}
    retrieval_hit = bool(set(case.get("expected_tags", [])) & hit_tags) if case.get("expected_tags") else None
    return {
        "question": case["question"],
        "latency_s": round(dt, 3),
        "pred_action": pred_action,
        "expected_action": case["expected_action"],
        "intent_ok": pred_action == case["expected_action"],
        "success": bool(answer) and "MCP调用失败" not in answer and "查询超时" not in answer,
        "fallback": fallback,
        "retrieval_hit": retrieval_hit,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--framework", choices=["pocketflow", "langgraph"], default="pocketflow")
    args = p.parse_args()
    framework = args.framework

    cases = json.load(open(os.path.join(os.path.dirname(__file__), "eval_set.json"), encoding="utf-8"))
    reset()  # 清空记忆，得到干净基线
    results = [run_case(c, framework) for c in cases]

    # 重复提问率演示：连续问同一城市 3 次（记忆生效前 vs 后）
    for _ in range(3):
        record_query("北京", ["带宝宝"])

    n = len(results)
    success = sum(r["success"] for r in results)
    intent_ok = sum(r["intent_ok"] for r in results)
    fallback = sum(r["fallback"] for r in results)
    retr = [r["retrieval_hit"] for r in results if r["retrieval_hit"] is not None]
    retr_hit = sum(1 for x in retr if x)
    avg_lat = sum(r["latency_s"] for r in results) / n
    # 任务路由准确率：weather/travel 均属"任务"分支（都走 天气→建议），
    # 真正的功能分界是 闲聊(chat) vs 任务(task)
    def is_task(a):
        return a in ("weather", "travel")
    route_ok = sum(1 for r in results if is_task(r["pred_action"]) == is_task(r["expected_action"]))

    metrics = {
        "framework": framework,
        "total_cases": n,
        "task_success_rate": round(success / n, 3),
        "intent_accuracy": round(intent_ok / n, 3),
        "task_routing_accuracy": round(route_ok / n, 3),
        "avg_latency_s": round(avg_lat, 3),
        "weather_fallback_rate": round(fallback / n, 3),
        "retrieval_accuracy": round(retr_hit / len(retr), 3) if retr else None,
        "repeat_question_rate": repeat_rate(),
    }

    print(f"=== 框架：{framework} ===")
    print("=== 逐条结果 ===")
    for r in results:
        print(f"[{'OK' if r['success'] else 'FAIL'}] {r['question']} | 意图 {r['pred_action']}(期望 {r['expected_action']})"
              f" | 时延 {r['latency_s']}s | 检索命中 {r['retrieval_hit']}")
    print("\n=== 量化指标 ===")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    # 写盘，供 README / 简历引用
    with open(os.path.join(os.path.dirname(__file__), f"metrics_{framework}.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
