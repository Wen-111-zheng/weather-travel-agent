# -*- coding: utf-8 -*-
"""SQLite 存储：把每一步存进一个 .db 文件。

为什么用 SQLite：不用装任何服务，数据就是一个文件，而且能用 SQL 聚合查询
（后面做"平均耗时""失败率"这些统计时直接 GROUP BY 就行）。

路径可用环境变量 AGENT_TRACE_DB 改，默认存在项目根目录的 traces.db。
"""
import os
import sqlite3
import threading

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "traces.db",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id          TEXT NOT NULL,
    span_id           TEXT NOT NULL,
    parent_id         TEXT,
    name              TEXT NOT NULL,
    kind              TEXT NOT NULL,
    start_ts          REAL,
    end_ts            REAL,
    latency_ms        REAL,
    status            TEXT,
    input_text        TEXT,
    output_text       TEXT,
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    error             TEXT
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_name  ON spans(name);
"""


class SpanStorage:
    """Span 的 SQLite 读写。"""

    def __init__(self, db_path=None):
        self.db_path = db_path or os.getenv("AGENT_TRACE_DB", DEFAULT_DB)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)

    def insert(self, span):
        """写入一步。"""
        d = span.to_dict()
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO spans
                   (trace_id, span_id, parent_id, name, kind,
                    start_ts, end_ts, latency_ms, status,
                    input_text, output_text, model,
                    prompt_tokens, completion_tokens, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["trace_id"], d["span_id"], d["parent_id"], d["name"], d["kind"],
                    d["start_ts"], d["end_ts"], d["latency_ms"], d["status"],
                    d["input_text"], d["output_text"], d["model"],
                    d["prompt_tokens"], d["completion_tokens"], d["error"],
                ),
            )

    # ---------- 查询（阶段 3 做统计时会用到） ----------

    def fetch_trace(self, trace_id):
        """取出某一次问答的所有步骤，按时间排序。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM spans WHERE trace_id=? ORDER BY start_ts", (trace_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def list_traces(self, limit=20):
        """列出最近几次追踪的概要。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT trace_id,
                          MIN(start_ts) AS start_ts,
                          MAX(latency_ms) AS root_ms,
                          COUNT(*) AS n_spans,
                          SUM(prompt_tokens) AS p_tokens,
                          SUM(completion_tokens) AS c_tokens,
                          SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS n_error
                   FROM spans GROUP BY trace_id
                   ORDER BY start_ts DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def step_stats(self):
        """按步骤名统计：调用次数、平均耗时、失败次数（后面做聚合指标要用）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT name, kind,
                          COUNT(*) AS n,
                          ROUND(AVG(latency_ms),2) AS avg_ms,
                          ROUND(MAX(latency_ms),2) AS max_ms,
                          SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS n_error,
                          SUM(prompt_tokens) AS p_tokens,
                          SUM(completion_tokens) AS c_tokens
                   FROM spans WHERE kind != 'root'
                   GROUP BY name, kind ORDER BY avg_ms DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def clear(self):
        """清空所有数据（重跑评测前调用，避免旧数据干扰）。"""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM spans")
