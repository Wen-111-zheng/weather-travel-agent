# -*- coding: utf-8 -*-
"""长期记忆：用户画像（双轨存储）。
- 轨1 统计：常问城市频次（用于"重复提问率"指标与个性化）
- 轨2 偏好：从对话中抽取的偏好标签（带宝宝/骑行/通勤/防晒...），跨轮次复用

作用：
1. 个性化：记住用户偏好，后续无需重复询问
2. 量化：可计算"重复提问率"（同一会话重复问同城市的占比），越低说明记忆生效
"""
import os
import json
from collections import Counter

# 临时上下文偏好：仅当前这一轮出行有效（带宝宝/带老人/陪老人等）。
# 与"稳定偏好"(如通勤、骑行、防晒)区分开，跑完本轮自动从记忆里清掉，
# 避免污染下一轮"我一个人出门"的提示词。
TEMPORARY_PREFERENCE_TAGS = {
    "带宝宝", "带小孩", "带孩子", "带婴幼儿", "带婴儿", "和宝宝",
    "带老人", "陪老人", "和老人", "扶老人", "老人",
}

MEMORY_PATH = os.path.join(os.path.dirname(__file__), "user_profile.json")


def _load():
    if os.path.exists(MEMORY_PATH):
        try:
            return json.load(open(MEMORY_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"cities": {}, "preferences": [], "history": []}


def _save(d):
    json.dump(d, open(MEMORY_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def record_query(city, preferences=None):
    """记录一次查询，更新城市频次与偏好标签。"""
    d = _load()
    d["cities"][city] = d["cities"].get(city, 0) + 1
    if preferences:
        for p in preferences:
            if p not in d["preferences"]:
                d["preferences"].append(p)
    d["history"].append(city)
    if len(d["history"]) > 30:
        d["history"] = d["history"][-30:]
    _save(d)
    return d


def get_profile():
    return _load()


def repeat_rate():
    """同一会话内重复问同一城市的占比（越低越好，记忆生效的标志）。"""
    d = _load()
    h = d["history"]
    if not h:
        return 0.0
    cnt = Counter(h)
    repeats = sum(v - 1 for v in cnt.values() if v > 1)
    return round(repeats / len(h), 3)


def reset():
    if os.path.exists(MEMORY_PATH):
        os.remove(MEMORY_PATH)


def clear_temporary_preferences():
    """清掉临时上下文偏好（带宝宝/带老人/陪老人等）。

    设计原因：这些是"这一趟出行的临时上下文"（这次带宝宝出门），
    不是稳定的用户画像（我经常通勤）。若不清掉，会被
    agents/core.py 第 59 行无脑合并到下一轮 prompt 里，导致
    "我一个人出门"却给"带宝宝"建议。
    稳定偏好（如"通勤"/"防晒"/"骑行"）会保留。
    """
    d = _load()
    before = d.get("preferences", [])
    after = [p for p in before if p not in TEMPORARY_PREFERENCE_TAGS]
    cleared = [p for p in before if p in TEMPORARY_PREFERENCE_TAGS]
    if after != before:
        d["preferences"] = after
        _save(d)
    return {"cleared": cleared, "kept": after}
