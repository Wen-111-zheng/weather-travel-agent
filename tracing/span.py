# -*- coding: utf-8 -*-
"""Span：链路追踪里的"一个步骤"。

用快递打比方理解这三个概念：
- trace_id ：一次问答的唯一编号（快递单号，整场考试只有一个）
- Span     ：其中一个步骤（快递轨迹里的一站，一道题的答题过程）
- parent_id：上一步是谁（用来排出先后顺序，形成层级）

一个 Span 记录的就三件事：这步叫什么、花了多久、输入输出是什么。
"""
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

# 输入输出最长保留多少字（防止把数据库塞爆）
MAX_TEXT = int(os.getenv("AGENT_TRACE_MAX_TEXT", "500"))


def _cut(text):
    """过长的文本做截断。"""
    if text is None:
        return None
    s = text if isinstance(text, str) else str(text)
    return s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + f"...(共{len(s)}字)"


@dataclass
class Span:
    """链路中的一个步骤。"""

    trace_id: str
    span_id: str
    name: str
    kind: str = "agent"       # agent(agent步骤) / llm(大模型调用) / tool(工具调用) / root(整次问答)
    parent_id: Optional[str] = None
    start_ts: float = field(default_factory=time.time)
    end_ts: Optional[float] = None
    latency_ms: Optional[float] = None
    status: str = "ok"        # ok / error
    input_text: Optional[str] = None
    output_text: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    error: Optional[str] = None

    @property
    def tokens(self):
        """本次调用的总 token 数（没有则为 0）。"""
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)

    def finish(self, output=None, error=None, **kw):
        """结束这一步，自动算耗时。"""
        self.end_ts = time.time()
        self.latency_ms = round((self.end_ts - self.start_ts) * 1000, 2)
        if output is not None:
            self.output_text = _cut(output)
        if error:
            self.status = "error"
            self.error = _cut(error)
        for k, v in kw.items():
            if v is not None and hasattr(self, k):
                setattr(self, k, v)
        return self

    def to_dict(self):
        return asdict(self)
