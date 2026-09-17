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


def _rrf(rank, k=60):
    """Reciprocal Rank Fusion 分数：rank 从 0 起，用于融合多路召回的排名。"""
    return 1.0 / (rank + 1 + k)


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
        """混合召回 + RRF 融合重排（阶段三 ①-A）。

        - 有 embedding：embedding 余弦 top-N 与 关键词 bigram 重叠 top-N 各召回一批候选，
          用 RRF 融合两路排名后取 top-k（即重排）。
        - 无 embedding（离线 mock）：仅关键词一路，退化为关键词重叠重排，仍跑通。
        返回 list[doc]，接口与旧版完全一致，调用方（advice / 评测）无需改动。
        """
        n_cand = max(k * 3, k + 2)  # 先扩召回，再重排截断，给重排留出余量
        fused = {}  # idx -> 融合分

        # 路1：embedding 语义召回
        if self.emb:
            q = self._embed(query)
            sims = sorted(
                ((self._cosine(q, e), i) for i, e in enumerate(self.emb)),
                reverse=True,
            )
            for rank, (_, i) in enumerate(sims[:n_cand]):
                fused[i] = fused.get(i, 0.0) + _rrf(rank)

        # 路2：关键词 bigram 召回（始终生效；无 Key 时即主路）
        qk = _tokens(query)
        if qk:
            kw = []
            for i, d in enumerate(self.docs):
                ov = len(qk & _tokens(d["text"]))
                if ov > 0:
                    kw.append((ov, i))
            kw.sort(reverse=True)
            for rank, (_, i) in enumerate(kw[:n_cand]):
                fused[i] = fused.get(i, 0.0) + _rrf(rank)

        if not fused:
            # 完全无重叠：退化返回前 k 条，保证至少有上下文
            return self.docs[:k]

        ranked = sorted(fused.items(), key=lambda kv: -kv[1])
        return [self.docs[i] for i, _ in ranked[:k]]
