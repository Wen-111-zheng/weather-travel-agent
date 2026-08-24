# -*- coding: utf-8 -*-
"""RAG 检索模块。

- 有 SILICONFLOW_API_KEY：用 BAAI/bge-m3 中文 embedding 转向量 + 纯 Python 余弦相似度检索（无需 numpy/faiss）
- 无 Key：回退到中文关键词重叠打分（仍跑通 RAG 链路，便于离线演示）

检索准确率在评测中量化（见 eval/run_eval.py）。
"""
import os
import re
from config import SILICONFLOW_API_KEY, USE_REAL_EMBEDDING
from rag.corpus import DOCUMENTS


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _tokens(text):
    """中文二元分词（bigram）。
    中文无空格，直接用 {2,} 会整句当一个 token；改为对连续中文做滑动 2-gram，
    既能与语料词匹配，又能捕捉子串重叠，检索更稳。
    """
    toks = set()
    for run in re.findall(r'[\u4e00-\u9fa5]+', text):
        if len(run) == 1:
            toks.add(run)
        for i in range(len(run) - 1):
            toks.add(run[i:i + 2])
    return toks


class KnowledgeBase:
    def __init__(self):
        self.docs = DOCUMENTS
        self.emb = None
        if USE_REAL_EMBEDDING:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=SILICONFLOW_API_KEY, base_url="https://api.siliconflow.cn/v1")
                self.emb = [self._embed(d["text"]) for d in self.docs]
            except Exception:
                self.emb = None  # 回退关键词

    def _embed(self, text):
        r = self.client.embeddings.create(model="BAAI/bge-m3", input=text)
        return list(r.data[0].embedding)

    def retrieve(self, query, k=3):
        if self.emb:
            q = self._embed(query)
            scored = [(self._cosine(q, e), i) for i, e in enumerate(self.emb)]
            scored.sort(reverse=True)
            return [self.docs[i] for _, i in scored[:k]]
        # 关键词回退
        qk = _tokens(query)
        scored = []
        for i, d in enumerate(self.docs):
            overlap = len(qk & _tokens(d["text"]))
            scored.append((overlap, i))
        scored.sort(reverse=True)
        top = [self.docs[i] for _, i in scored[:k] if _ > 0]
        return top or self.docs[:k]
