# -*- coding: utf-8 -*-
"""出行建议 Agent（PocketFlow 封装）：调用 core.advice。"""
from pocketflow import Node
from agents.core import advice


class AdviceAgent(Node):
    def prep(self, shared):
        return shared.get("weather_data", []), shared.get("preferences", [])

    def exec(self, data):
        wd, prefs = data
        return advice(wd, prefs)

    def post(self, shared, prep_res, exec_res):
        shared["answer"] = exec_res
        return "done"
