# -*- coding: utf-8 -*-
"""命令行入口：运行多智能体天气出行助手。

支持两套编排框架（--framework）：
  - langgraph  （默认）基于 LangGraph StateGraph 编排
  - pocketflow  基于 PocketFlow Flow 编排
两者复用同一套 agents/core.py 核心逻辑、MCP 工具、RAG 与长期记忆。
"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "PocketFlow"))

from config import llm_mode


def main():
    p = argparse.ArgumentParser(description="多智能体天气出行助手")
    p.add_argument("query", nargs="?", default=None,
                   help="要咨询的天气/出行问题；留空则进入交互式提问")
    p.add_argument("--framework", choices=["pocketflow", "langgraph"], default="langgraph")
    args = p.parse_args()

    # 交互式：未传 query 时先问一句，再把用户输入接入后续流程
    if not args.query:
        args.query = input("请问要咨询什么天气（城市/出行建议）？ ").strip()
    if not args.query:
        args.query = "北京和深圳天气怎么样，适合穿什么"

    print(f"[LLM 模式] {llm_mode()} | [框架] {args.framework}")

    if args.framework == "langgraph":
        from langgraph_flow import run as lg_run
        answer = lg_run(args.query)
    else:
        from flow import create_weather_travel_flow
        flow = create_weather_travel_flow()
        shared = {"question": args.query}
        flow.run(shared)
        answer = shared.get("answer")

    print("回答：")
    print(answer)

    # 跑完本轮后清掉"带宝宝/带老人"等临时上下文偏好，避免污染下一轮
    # （稳定偏好如"通勤/防晒"会保留）
    from memory.user_profile import clear_temporary_preferences
    res = clear_temporary_preferences()
    if res["cleared"]:
        print(f"\n[记忆清理] 已清掉本轮临时偏好：{res['cleared']}（不影响稳定偏好）")


if __name__ == "__main__":
    main()
