# -*- coding: utf-8 -*-
"""Agent 全链路追踪（阶段 1：给 Agent 装"摄像头"）。

对外就四个东西，够用了：

    from tracing import start_trace, trace, span_ctx, print_last_trace

    @trace("意图识别")            # 1. 给函数加追踪
    def intent(q): ...

    with start_trace("一次问答"):  # 2. 一次问答包一层
        flow.run(shared)

    with span_ctx("RAG检索") as s: # 3. 手动记一段
        ...

    print_last_trace()             # 4. 打印耗时树形图

开关：设环境变量 AGENT_TRACE=1 才启用，默认关闭（不影响原有评测代码）。
数据库：默认项目根目录 traces.db，可用 AGENT_TRACE_DB 改路径。
"""
from .span import Span
from .collector import (
    Collector,
    get_collector,
    enabled,
    current_span,
    start_trace,
    span_ctx,
    trace,
)
from .storage import SpanStorage
from .report import render_waterfall, print_last_trace

__all__ = [
    "Span",
    "Collector",
    "SpanStorage",
    "get_collector",
    "enabled",
    "current_span",
    "start_trace",
    "span_ctx",
    "trace",
    "render_waterfall",
    "print_last_trace",
]
