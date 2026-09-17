# -*- coding: utf-8 -*-
"""多轮对话评测（阶段三 C）：基于"长期记忆"的多轮会话评估。

背景（已读代码确认）：当前 agent 是单轮架构——run_query 每次新建 flow/app，不传历史。
但记忆模块（memory/user_profile.py，磁盘文件 user_profile.json）跨轮持久化：
每轮天气查询后 record_query 写入城市频次/偏好/历史，advice() 又通过 get_profile()
把历史偏好合并进下一轮建议。所以现有架构下的"多轮" = 一轮接一轮地问、共享同一份记忆。

本脚本评三件事：
- turn_pass_rate      每轮答案经 LLM-as-Judge 阅卷的可用率
- avg_repeat_rate    会话内重复提问率（记忆在记录"重复问同城市"的程度；越高说明重复越多、记忆捕获越好）
- avg_preference_recall  偏好跨轮复用率（T1 说了某偏好，T2 不重提，答案仍出现该偏好 → 验证 get_profile 个性化链路）

成本（阶段三 B 复用）：跑前 reset_token_usage()，跑后 get_token_usage() + compute_cost()。

注意：记忆是全局单文件 user_profile.json，会话间必须串行 + reset()，不能并发（D 的并发在 C 不适用）。
"""
import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "PocketFlow"))

from memory.user_profile import reset, repeat_rate
from judge import judge
from run_eval import run_query                      # 复用单轮评测的查询入口
from utils.llm import reset_token_usage, get_token_usage
from cost import compute_cost

JUDGE_DIMS = ("relevance", "factuality", "completeness", "safety", "conciseness")


def run_session(session, framework):
    """跑一个会话（顺序多轮，共享记忆），返回该会话评测结果。"""
    reset()  # 清空记忆，得到干净会话基线（记忆是全局单文件，必须串行 + reset）
    turns = []
    for t in session["turns"]:
        st = run_query(t["question"], framework)
        answer = st.get("answer", "")
        j = judge(t["question"], answer)  # weather_data/docs 默认 None，与单轮评测同口径
        judge_score = None
        if j:
            judge_score = {k: j[k] for k in JUDGE_DIMS + ("pass", "reason")}
        turns.append({
            "question": t["question"],
            "answer": answer,
            "expected_pref": t.get("expected_pref"),
            "judge": judge_score,
        })

    rr = repeat_rate()
    # 偏好跨轮复用：检查带 expected_pref 的轮次，答案是否含其中任一关键词
    pref_turns = [t for t in turns if t.get("expected_pref")]
    pref_recall = None
    if pref_turns:
        hit = sum(1 for t in pref_turns if any(p in t["answer"] for p in t["expected_pref"]))
        pref_recall = round(hit / len(pref_turns), 3)
    return {
        "session_id": session.get("session_id"),
        "scenario": session.get("scenario"),
        "turns": turns,
        "repeat_rate": rr,
        "preference_recall": pref_recall,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--framework", choices=["pocketflow", "langgraph"], default="pocketflow")
    args = p.parse_args()
    framework = args.framework

    path = os.path.join(os.path.dirname(__file__), "multi_turn_set.json")
    sessions = json.load(open(path, encoding="utf-8"))

    reset_token_usage()  # 阶段三 B：清空 token 计数，只统计本轮多轮评测
    results = [run_session(s, framework) for s in sessions]

    # 聚合指标
    n_turns = sum(len(r["turns"]) for r in results)
    n_pass = sum(1 for r in results for t in r["turns"] if t["judge"] and t["judge"].get("pass"))
    turn_pass_rate = round(n_pass / n_turns, 3) if n_turns else None
    rrs = [r["repeat_rate"] for r in results]
    avg_repeat_rate = round(sum(rrs) / len(rrs), 3) if rrs else None
    prs = [r["preference_recall"] for r in results if r["preference_recall"] is not None]
    avg_pref_recall = round(sum(prs) / len(prs), 3) if prs else None

    token_usage = get_token_usage()
    cost = compute_cost(token_usage, n_cases=n_turns)  # 每轮均价（按轮次算）

    metrics = {
        "framework": framework,
        "mode": "multi_turn",
        "total_sessions": len(results),
        "total_turns": n_turns,
        "turn_pass_rate": turn_pass_rate,
        "avg_repeat_rate": avg_repeat_rate,
        "avg_preference_recall": avg_pref_recall,
        # 阶段三 B：Token 成本（无 Key / 离线时为 0）
        "token_usage": token_usage,
        "cost_cny": cost,
        "sessions": results,
    }

    # ---------- 打印 ----------
    print(f"=== 多轮对话评测：{framework} ===")
    print(f"会话数：{len(results)}  总轮次：{n_turns}")
    print(f"轮级可用率 turn_pass_rate：{turn_pass_rate}")
    print(f"平均重复提问率 avg_repeat_rate：{avg_repeat_rate}")
    print(f"平均偏好跨轮复用率 avg_preference_recall：{avg_pref_recall}")
    print(f"Token 成本（阶段三 B）：调用 {cost['calls']} 次，合计 ¥{cost['cost_total_cny']}，"
          f"每轮均价 ¥{cost['avg_cost_per_case_cny']}")
    print("\n=== 各会话明细 ===")
    for r in results:
        print(f"[会话 {r['session_id']}] {r['scenario']}")
        print(f"   repeat_rate={r['repeat_rate']}  preference_recall={r['preference_recall']}")
        for t in r["turns"]:
            jpass = t["judge"]["pass"] if t["judge"] else "N/A"
            pref_mark = f"  [预期偏好 {t['expected_pref']}]" if t.get("expected_pref") else ""
            print(f"   - ({jpass}) {t['question']}{pref_mark}  → {t['answer'][:30]}...")

    out = os.path.join(os.path.dirname(__file__), f"metrics_multiturn_{framework}.json")
    json.dump(metrics, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n已写出 {out}")


if __name__ == "__main__":
    main()
