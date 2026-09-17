# -*- coding: utf-8 -*-
"""采集器：负责记录每一个步骤，并自动串成父子链条。

用法有三种：

1. 给函数加装饰器（最省事，一行搞定）：
       @trace("意图识别")
       def intent(question): ...

2. 手动包一段代码（想在中间记点额外信息时用）：
       with span_ctx("天气查询", kind="tool") as s:
           s.input_text = city
           ...

3. 开启一次完整追踪（一次问答一个编号）：
       with start_trace("用户提问") as root:
           flow.run(shared)

父子关系是自动的：谁在里面调用，谁就是谁的子步骤。
"""
import os
import time
import uuid
import functools
import contextvars
from contextlib import contextmanager

from .span import Span, _cut

# 当前正在执行的步骤（用 contextvars 保证多线程/协程下互不干扰）
_current_span = contextvars.ContextVar("tracing_current_span", default=None)
# 当前的追踪编号
_current_trace = contextvars.ContextVar("tracing_trace_id", default=None)


def enabled():
    """追踪开关。设环境变量 AGENT_TRACE=1 才启用，默认关闭不影响原有代码。"""
    return os.getenv("AGENT_TRACE", "0") == "1"


def _new_id():
    return uuid.uuid4().hex[:16]


def current_span():
    return _current_span.get()


class Collector:
    """收集所有步骤，并写入 SQLite。"""

    def __init__(self, db_path=None):
        self.db_path = db_path
        self._storage = None
        self.spans = []          # 内存里也留一份，方便当场打印报告

    @property
    def storage(self):
        if self._storage is None:
            from .storage import SpanStorage
            self._storage = SpanStorage(self.db_path)
        return self._storage

    def record(self, span):
        """记录一步。存储失败绝不能影响主流程，所以吞掉异常。"""
        self.spans.append(span)
        try:
            self.storage.insert(span)
        except Exception:
            pass

    def last_trace(self):
        """返回最近一次追踪的所有步骤。"""
        if not self.spans:
            return []
        tid = self.spans[0].trace_id
        for s in reversed(self.spans):
            if s.kind == "root":
                tid = s.trace_id
                break
        return [s for s in self.spans if s.trace_id == tid]


_collector = None


def get_collector(db_path=None):
    global _collector
    if _collector is None:
        _collector = Collector(db_path)
    return _collector


# ---------- 1. 开启一次追踪 ----------

@contextmanager
def start_trace(name="query", trace_id=None, db_path=None):
    """开启一次追踪：一次问答包一层，生成一个 trace_id。"""
    if not enabled():
        yield None
        return

    tid = trace_id or _new_id()
    root = Span(trace_id=tid, span_id=_new_id(), name=name, kind="root")

    tok_t = _current_trace.set(tid)
    tok_s = _current_span.set(root)
    try:
        yield root
    except Exception as e:
        root.finish(error=str(e))
        raise
    finally:
        if root.end_ts is None:
            root.finish()
        _current_span.reset(tok_s)
        _current_trace.reset(tok_t)
        get_collector(db_path).record(root)


# ---------- 2. 函数装饰器 ----------

def trace(name=None, kind="agent", capture_input=True, capture_output=True):
    """给函数加追踪。

    @trace("意图识别")
    def intent(question): ...

    :param name: 这一步显示的名字，默认用函数名
    :param kind: agent / llm / tool，用来在报告里区分颜色
    :param capture_input: 是否记录函数入参
    :param capture_output: 是否记录返回值
    """
    def deco(fn):
        label = name or fn.__name__
        # 类方法的 __qualname__ 形如 "MCPWeatherClient.get_weather"，
        # 带点号说明是方法，取输入时要跳过第一个参数 self
        is_method = "." in getattr(fn, "__qualname__", "")

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not enabled():
                return fn(*args, **kwargs)   # 关闭时零开销，原样调用

            parent = _current_span.get()
            tid = _current_trace.get() or (parent.trace_id if parent else _new_id())
            span = Span(
                trace_id=tid,
                span_id=_new_id(),
                name=label,
                kind=kind,
                parent_id=parent.span_id if parent else None,
            )
            if capture_input:
                # 类方法第一个参数是 self，要跳过（qualname 形如 "类名.方法名"）
                src = args[1:] if (is_method and args) else args
                if src:
                    span.input_text = _cut(src[0])
                elif kwargs:
                    span.input_text = _cut(next(iter(kwargs.values())))

            tok = _current_span.set(span)
            try:
                out = fn(*args, **kwargs)
                span.finish(output=out if capture_output else None)
                return out
            except Exception as e:
                span.finish(error=str(e))
                raise
            finally:
                _current_span.reset(tok)
                get_collector().record(span)

        return wrapper
    return deco


# ---------- 3. 手动包一段代码 ----------

@contextmanager
def span_ctx(name, kind="agent", input_text=None, **kw):
    """手动记录一段代码的耗时。

    with span_ctx("天气查询", kind="tool", input_text="北京") as s:
        data = client.get_weather("北京")
        s.output_text = str(data)
    """
    if not enabled():
        yield None
        return

    parent = _current_span.get()
    tid = _current_trace.get() or (parent.trace_id if parent else _new_id())
    span = Span(
        trace_id=tid,
        span_id=_new_id(),
        name=name,
        kind=kind,
        parent_id=parent.span_id if parent else None,
        input_text=_cut(input_text),
        **kw,
    )
    tok = _current_span.set(span)
    try:
        yield span
    except Exception as e:
        span.finish(error=str(e))
        raise
    finally:
        if span.end_ts is None:
            span.finish()
        _current_span.reset(tok)
        get_collector().record(span)
