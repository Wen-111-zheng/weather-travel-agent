# -*- coding: utf-8 -*-
"""阶段 1 演示：跑一次问答，打印"时间都花在哪"的树形图。

用法（Windows）：
    python tracing_demo.py

脚本会自动开启追踪开关，跑完直接打印耗时分布，并把数据存进 traces.db。
如果只想看某句特定问题，改下面的 QUESTION 即可。
"""
import os
import sys

# 自动开启追踪（不想看追踪时把这行删掉，就恢复成原来的行为）
os.environ.setdefault("AGENT_TRACE", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "PocketFlow"))

from tracing import start_trace, print_last_trace, get_collector  # noqa: E402
from flow import create_weather_travel_flow                        # noqa: E402

QUESTION = "深圳明天适合带宝宝去户外吗"


def main():
    print(f"问题：{QUESTION}\n")

    shared = {"question": QUESTION}
    with start_trace("一次问答") as root:
        flow = create_weather_travel_flow()
        flow.run(shared)
        if root is not None:
            root.input_text = QUESTION
            root.output_text = str(shared.get("answer", ""))[:300]

    print("回答：")
    print(shared.get("answer", "(未生成答案)"))

    # 树形耗时图：一眼看出慢在哪一步
    print_last_trace()

    # 数据已落库，顺便看聚合统计
    print("\n===== 各步骤统计（已存进 traces.db，可用 SQL 查）=====")
    rows = get_collector().storage.step_stats()
    if not rows:
        print("（无数据）")
    for r in rows:
        print(
            f"  {r['name']:<22} 调用 {r['n']:>2} 次   平均 {r['avg_ms']:>8.2f} ms   "
            f"最大 {r['max_ms']:>8.2f} ms   失败 {r['n_error']}"
        )


if __name__ == "__main__":
    main()
