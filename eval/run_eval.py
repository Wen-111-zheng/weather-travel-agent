# -*- coding: utf-8 -*-
"""评测脚本：对多智能体天气助手跑评测集，输出量化指标。

支持两套编排框架（--framework）：
  - pocketflow （默认，与原版指标基线一致）
  - langgraph

并发跑题：--workers N（默认 4，设 1 退回串行）；结果顺序与评测集一致

指标：
- task_success_rate   任务成功率（返回有效回答、无工具兜底失败）
- avg_latency_s       平均端到端时延
- intent_accuracy     意图识别准确率
- weather_fallback_rate 天气工具兜底率（越高说明上游越不稳）
- retrieval_accuracy  RAG 检索命中率（检索结果是否覆盖预期知识标签）
- repeat_question_rate 重复提问率（长期记忆生效后的会话指标）
- avg_judge_score    LLM-as-Judge 五维均分（相关性/事实/完整/安全/简洁），无 Key 时为 null
- pass_rate          阅卷判"可用"的比例
- by_case_type       按 6 类场景拆分的短板分布（综合五维均分）
- failure_modes      Bad Case 自动归类（6 种失败模式分布 + 每类代表案例；逐条明细另存 badcases_{framework}.json）
- token_usage        阶段三 B：本轮全部真实 LLM 调用的 token 用量（无 Key / 离线时为 0）
- cost_cny           阶段三 B：折合人民币成本（输入/输出/合计/每题均价；价格基准见 eval/cost.py）
"""
import os
import sys
import json
import time
import argparse
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "PocketFlow"))

from rag.knowledge_base import KnowledgeBase
from memory.user_profile import reset, record_query, repeat_rate
from collections import defaultdict
from judge import judge          # 阶段二：LLM-as-Judge 阅卷
from badcase import classify     # 阶段三 A：Bad Case 自动归类
from utils.llm import reset_token_usage, get_token_usage   # 阶段三 B：Token 用量累加器
from cost import compute_cost                              # 阶段三 B：用量换算成人民币

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
    j = judge(case["question"], answer, weather_data=wd, docs=docs)
    judge_score = None
    if j:
        judge_score = {k: j[k] for k in ("relevance", "factuality", "completeness", "safety", "conciseness", "pass", "reason")}
    return {
        "question": case["question"],
        "latency_s": round(dt, 3),
        "pred_action": pred_action,
        "expected_action": case["expected_action"],
        "intent_ok": pred_action == case["expected_action"],
        "success": bool(answer) and "MCP调用失败" not in answer and "查询超时" not in answer,
        "fallback": fallback,
        "retrieval_hit": retrieval_hit,
        "judge": judge_score,
        "case_type": case.get("case_type"),
        "answer": answer,   # 阶段三 A：供 Bad Case 归类使用（不写盘到 metrics）
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--framework", choices=["pocketflow", "langgraph"], default="pocketflow")
    p.add_argument("--workers", type=int, default=4,
                   help="并发评测线程数（默认 4）；设为 1 退回串行。结果顺序与评测集一致")
    args = p.parse_args()
    framework = args.framework

    cases = json.load(open(os.path.join(os.path.dirname(__file__), "eval_set.json"), encoding="utf-8"))
    reset()  # 清空记忆，得到干净基线
    reset_token_usage()  # 阶段三 B：清空 token 计数器，只统计本轮评测
    # 并发跑题：ThreadPoolExecutor.map 保持输入顺序，故 results 与 cases 顺序一致。
    # 各 run_case 内部自建 app/flow 实例、MCP 子进程用完即关、全局 client 走线程安全懒加载，
    # 因此并发安全；设 --workers 1 退回串行，便于对比/排障。
    t_eval_start = time.time()
    if args.workers <= 1:
        results = [run_case(c, framework) for c in cases]
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(lambda c: run_case(c, framework), cases))
    wall_s = time.time() - t_eval_start   # 阶段三 D：总墙钟耗时（并发后远小于各题时延之和）

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

    jscores = [r["judge"] for r in results if r.get("judge")]
    dims = ["relevance", "factuality", "completeness", "safety", "conciseness"]
    if jscores:
        avg_judge = {d: round(sum(j[d] for j in jscores) / len(jscores), 3) for d in dims}
        pass_rate = round(sum(1 for j in jscores if j["pass"]) / len(jscores), 3)
        by_type = defaultdict(list)
        for r in results:
            if r.get("judge"):
                by_type[r["case_type"]].append(r["judge"])
        by_case_type = {
            ct: round(sum(sum(j[d] for d in dims) for j in js) / (len(js) * len(dims)), 3)
            for ct, js in by_type.items()
        }
    else:
        avg_judge = None
        pass_rate = None
        by_case_type = None

    # 阶段三 A：Bad Case 自动归类（只对 judge 判不通过的样本，再问一次"错在哪一类"）
    badcases = []
    for r in results:
        j = r.get("judge")
        if j and not j.get("pass"):
            c = classify(r["question"], r.get("answer", ""), j.get("reason", ""))
            if c:
                badcases.append({
                    "question": r["question"],
                    "case_type": r.get("case_type"),
                    "failure_mode": c["failure_mode"],
                    "why": c["why"],
                })
    failure_modes = None
    if badcases:
        dist = defaultdict(int)
        for b in badcases:
            dist[b["failure_mode"]] += 1
        examples = {}
        for b in badcases:
            examples.setdefault(b["failure_mode"], {"question": b["question"], "why": b["why"]})
        failure_modes = {
            "total_failed": len(badcases),
            "distribution": dict(sorted(dist.items(), key=lambda kv: -kv[1])),
            "examples": examples,
        }
        # 逐条明细单独写盘，避免主 metrics 被撑长
        with open(os.path.join(os.path.dirname(__file__), f"badcases_{framework}.json"), "w", encoding="utf-8") as f:
            json.dump(badcases, f, ensure_ascii=False, indent=2)

    # 阶段三 B：Token 成本统计（本轮全部真实 LLM 调用：回答 + judge + badcase 归类）
    token_usage = get_token_usage()
    cost = compute_cost(token_usage, n_cases=n)

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
        "avg_judge_score": avg_judge,
        "pass_rate": pass_rate,
        "by_case_type": by_case_type,
        "failure_modes": failure_modes,
        # 阶段三 B：Token 成本（无 Key / 离线时为 0）
        "token_usage": token_usage,
        "cost_cny": cost,
        # 阶段三 D：并发配置与总墙钟耗时（用于对比 --workers 1 的串行耗时）
        "concurrency_workers": args.workers,
        "wall_time_s": round(wall_s, 3),
    }

    print(f"=== 框架：{framework} ===")
    print("=== 逐条结果 ===")
    for r in results:
        j = r.get("judge")
        jinfo = (f" | judge={j['relevance']}/{j['factuality']}/{j['completeness']}/{j['safety']}/{j['conciseness']}"
                 f"(pass={j['pass']})") if j else " | judge=N/A"
        print(f"[{'OK' if r['success'] else 'FAIL'}] {r['question']} | 意图 {r['pred_action']}(期望 {r['expected_action']})"
              f" | 时延 {r['latency_s']}s | 检索命中 {r['retrieval_hit']}{jinfo}")
    print("\n=== 量化指标 ===")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if failure_modes:
        print("\n=== Bad Case 失败模式分布 ===")
        for m, cnt in failure_modes["distribution"].items():
            ex = failure_modes["examples"][m]
            print(f"  {m}: {cnt} 条  | 示例「{ex['question']}」→ {ex['why']}")
    # 阶段三 B：Token 成本打印
    print("\n=== Token 成本（阶段三 B）===")
    print(f"  真实 LLM 调用次数：{cost['calls']} 次")
    print(f"  输入 token：{cost['prompt_tokens']}  输出 token：{cost['completion_tokens']}  合计：{cost['total_tokens']}")
    print(f"  折合人民币：¥{cost['cost_total_cny']}（输入 ¥{cost['cost_input_cny']} + 输出 ¥{cost['cost_output_cny']}）")
    if cost["avg_cost_per_case_cny"] is not None:
        print(f"  每题均价：¥{cost['avg_cost_per_case_cny']}（按 {n} 题分摊）")
    print(f"  （价格基准：输入 ¥{cost['price_input_per_1m']}/1M、输出 ¥{cost['price_output_per_1m']}/1M token，以平台实时价为准）")
    print(f"=== 并发（阶段三 D）：线程数 {args.workers}，总墙钟耗时 {wall_s:.2f}s（--workers 1 退回串行可对比耗时）===")
    # 写盘，供 README / 简历引用
    with open(os.path.join(os.path.dirname(__file__), f"metrics_{framework}.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
