# -*- coding: utf-8 -*-
"""命令行报告：把追踪数据画成树形耗时图。

效果类似这样（一眼看出时间花在哪）：

    意图识别       [████                    ]  0.42s  (12.6%)
      └ LLM调用    [███                     ]  0.40s
    天气查询       [████████████            ]  1.20s  (36.0%)
      └ MCP工具    [███████████             ]  1.15s
    出行建议       [██████████████          ]  1.40s  (42.0%)
      ├ RAG检索    [██                      ]  0.31s
      └ LLM调用    [█████████               ]  1.05s
"""
from .span import Span

BAR_CHAR = "█"      # 条形图字符（若终端乱码，改成 "#" 即可）
BAR_WIDTH = 24


def _dw(s):
    """显示宽度：中文算 2 个字符宽，英文算 1 个（不然对不齐）。"""
    return sum(2 if ord(c) > 127 else 1 for c in str(s))


def _pad(s, width):
    """按显示宽度补空格，保证中文英文混排也能对齐。"""
    s = str(s)
    return s + " " * max(0, width - _dw(s))


def _truncate(s, width):
    """按显示宽度截断，超出用 … 结尾（名字太长会把条形图顶歪）。"""
    s = str(s)
    if _dw(s) <= width:
        return s
    out, cur = "", 0
    for c in s:
        w = 2 if ord(c) > 127 else 1
        if cur + w > width - 1:
            break
        out += c
        cur += w
    return out + "…"


def _fmt_ms(ms):
    """耗时格式化：小于 10 毫秒就用毫秒显示，否则显示秒（不然 1.12ms 会显示成 0.00s）。"""
    if ms < 10:
        return f"{ms:.1f}ms"
    return f"{ms/1000:.2f}s"


def _as_dicts(spans):
    return [s if isinstance(s, dict) else s.to_dict() for s in spans]


def _build_tree(items):
    """根据 parent_id 把平铺的列表变成树。返回 (根节点, {父id: [子节点]})。"""
    children = {}
    by_id = {}
    for it in items:
        by_id[it["span_id"]] = it
        pid = it.get("parent_id")
        children.setdefault(pid, []).append(it)
    for lst in children.values():
        lst.sort(key=lambda x: x["start_ts"])

    roots = [i for i in items if not i.get("parent_id")] or \
            [i for i in items if i.get("kind") == "root"]
    root = roots[0] if roots else None
    return root, children


def render_waterfall(spans, title="一次问答的耗时分布", show_tokens=True):
    """打印树形耗时图。"""
    items = _as_dicts(spans)
    if not items:
        print("（没有追踪数据，先设 AGENT_TRACE=1 跑一次）")
        return

    root, children = _build_tree(items)
    total = root["latency_ms"] if root else sum(
        i["latency_ms"] or 0 for i in items if not i.get("parent_id")
    )
    max_ms = max((i["latency_ms"] or 0) for i in items) or 1

    p_tok = sum(i.get("prompt_tokens") or 0 for i in items)
    c_tok = sum(i.get("completion_tokens") or 0 for i in items)

    print(f"\n===== {title} =====")
    head = f"总耗时 {total/1000:.2f}s" if total else ""
    if show_tokens and (p_tok or c_tok):
        head += f"   总 token {p_tok + c_tok}（输入 {p_tok} / 输出 {c_tok}）"
    if root and root.get("trace_id"):
        head += f"   trace: {root['trace_id']}"
    print(head)
    print("-" * 62)

    # 算出树的最大深度：层级浅的行多补空格，让所有条形图左端严格对齐
    def _tree_depth(node, d=0):
        kids = children.get(node["span_id"], [])
        if not kids:
            return d
        return max(_tree_depth(k, d + 1) for k in kids)

    max_depth = _tree_depth(root) if root else 1

    def walk(node, prefix, is_last, depth):
        if node is None:
            return
        ms = node["latency_ms"] or 0
        n = max(1, int(round(ms / max_ms * BAR_WIDTH)))
        bar = BAR_CHAR * n
        pct = f"{(ms / total * 100):5.1f}%" if total else "     "
        err = "  ❌" if node.get("status") == "error" else ""

        name = node["name"]
        if node.get("kind") == "llm" and node.get("model"):
            name += f"·{node['model']}"
        name = _truncate(name, 22)

        tok = ""
        if show_tokens and (node.get("prompt_tokens") or node.get("completion_tokens")):
            tok = f"  [{node.get('prompt_tokens') or 0}+{node.get('completion_tokens') or 0}tk]"

        connector = "" if depth == 0 else ("└ " if is_last else "├ ")
        # 层级越浅补越多空格，抵消缩进差异，让条形图从同一列开始
        pad_width = 24 + (max_depth - depth) * 3
        line = (f"{prefix}{connector}{_pad(name, pad_width)}"
                f"[{_pad(bar, BAR_WIDTH)}] {_fmt_ms(ms):>8} {pct}{tok}{err}")
        print(line)

        if node.get("error"):
            print(f"{prefix}   └ 错误：{node['error'][:60]}")

        kids = children.get(node["span_id"], [])
        child_prefix = prefix + ("   " if depth == 0 else ("   " if is_last else "│  "))
        for i, k in enumerate(kids):
            walk(k, child_prefix, i == len(kids) - 1, depth + 1)

    if root:
        walk(root, "", True, 0)
    else:
        for i in items:
            if not i.get("parent_id"):
                walk(i, "", True, 0)
    print("-" * 62)


def print_last_trace():
    """打印内存里最近一次追踪（跑完一次问答后直接调用）。"""
    from .collector import get_collector
    render_waterfall(get_collector().last_trace())
