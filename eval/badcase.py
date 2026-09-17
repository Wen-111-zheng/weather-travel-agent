# -*- coding: utf-8 -*-
"""Bad Case 自动归类（阶段三 A）。

对 LLM-as-Judge 判为不通过（pass=False）的样本，再用 DeepSeek 归到 6 种失败模式之一。
作用：把"有多少题答错了"进一步回答成"错在哪一类、为什么错"——
这是评测体系从"打分"走向"可诊断"的关键一环。

6 种失败模式：
- rag_underuse       检索到知识库片段但回答没用上/用得浅（说不全、泛泛而谈）
- no_clarify         问题模糊或缺关键信息（如"明天""天气"），没反问澄清就硬答
- intent_misroute    意图路由错误（该查天气的走了闲聊、该给建议的只查天气）
- fact_hallucination 事实错误或编造，与真实天气数据不符
- incomplete         答案不完整，漏了关键点（但没到编造程度）
- out_of_scope       超出助手能力范围（订机票、30 天逐小时预报等）

复用 utils.llm.complete_json；USE_REAL_LLM=False（mock / 无 Key）时返回 None，不崩。
"""
from config import USE_REAL_LLM
from utils.llm import complete_json

# 6 种失败模式（顺序即文档顺序）
FAILURE_MODES = [
    "rag_underuse",
    "no_clarify",
    "intent_misroute",
    "fact_hallucination",
    "incomplete",
    "out_of_scope",
]

_CLASSIFY_SYSTEM = """你是天气出行助手的错题分析师。给定【用户问题】【助手回答】【阅卷理由】，
判断这条回答失败的根本原因，只能从以下 6 个标签中选 1 个：
- rag_underuse       检索到知识库内容但回答没用上或用得浅
- no_clarify         问题模糊或缺关键信息，助手没有反问澄清就硬答
- intent_misroute    意图判断错误，走错了处理分支
- fact_hallucination 事实错误或编造，与真实天气数据不符
- incomplete         答案不完整，漏了关键点
- out_of_scope       超出助手能力范围
只输出 JSON，不要其他文字。格式：
{"failure_mode": "标签", "why": "一句话说明原因"}"""


def classify(question, answer, reason=""):
    """把一条失败样本归到 6 类失败模式。

    返回 {"failure_mode": str, "why": str}；降级(mock)或异常时返回 None，绝不中断评测。
    """
    if not USE_REAL_LLM:
        return None
    user = (f"【用户问题】{question}\n【助手回答】{answer}\n"
            f"【阅卷理由】{reason or '（无）'}")
    try:
        r = complete_json(user, system=_CLASSIFY_SYSTEM)
        mode = str(r.get("failure_mode", "")).strip()
        if mode not in FAILURE_MODES:
            mode = "other"
        return {"failure_mode": mode, "why": str(r.get("why", ""))}
    except Exception:
        return None
