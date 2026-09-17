# -*- coding: utf-8 -*-
"""Token 成本统计（阶段三 B）。

把一次评测跑下来的 token 用量换成"花了多少钱"。

价格以 DeepSeek 官方公开标准价为基准（单位：元 / 每 1M tokens）。
注意：价格会调整，正式汇报前请以 https://platform.deepseek.com 实时价格为准。
本模块把价格集中成常量，改价只动这里。

    from cost import compute_cost
    usage = get_token_usage()          # 来自 utils.llm
    cost = compute_cost(usage, n_cases=60)
    # cost["cost_total_cny"] 即本次评测总花费（人民币元）
"""
# ---------- 价格常量（元 / 1M tokens）----------
# 说明：我们未区分缓存命中/未命中，统一按 cache miss（输入较贵）估算，是"保守上界"。
PRICE_INPUT_PER_1M = 2.0      # 输入 token：¥2 / 1M
PRICE_OUTPUT_PER_1M = 8.0     # 输出 token：¥8 / 1M

PRICE_INPUT = PRICE_INPUT_PER_1M / 1_000_000
PRICE_OUTPUT = PRICE_OUTPUT_PER_1M / 1_000_000


def compute_cost(usage, n_cases=None):
    """把 token 用量换算成人民币成本。

    :param usage: utils.llm.get_token_usage() 返回的 dict
                  {prompt_tokens, completion_tokens, calls, by_model}
    :param n_cases: 评测集题数（可选）。给了就额外算"每题均价"。
    :return: 成本明细 dict
    """
    p = int(usage.get("prompt_tokens", 0) or 0)
    c = int(usage.get("completion_tokens", 0) or 0)
    calls = int(usage.get("calls", 0) or 0)
    total = p + c

    cost_input = p * PRICE_INPUT
    cost_output = c * PRICE_OUTPUT
    cost_total = cost_input + cost_output

    avg_per_case = (cost_total / n_cases) if (n_cases and n_cases > 0) else None

    return {
        "prompt_tokens": p,
        "completion_tokens": c,
        "total_tokens": total,
        "calls": calls,
        "cost_input_cny": round(cost_input, 6),
        "cost_output_cny": round(cost_output, 6),
        "cost_total_cny": round(cost_total, 6),
        "avg_cost_per_case_cny": round(avg_per_case, 6) if avg_per_case is not None else None,
        "price_input_per_1m": PRICE_INPUT_PER_1M,
        "price_output_per_1m": PRICE_OUTPUT_PER_1M,
    }


if __name__ == "__main__":
    # 离线自检：模拟一次用量，确认换算正确（不含网络/Key）
    sample = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000, "calls": 3, "by_model": {}}
    out = compute_cost(sample, n_cases=60)
    assert abs(out["cost_total_cny"] - (2.0 + 4.0)) < 1e-6, out
    assert abs(out["avg_cost_per_case_cny"] - (6.0 / 60)) < 1e-9, out
    print("COST_SELFTEST_OK", out)
