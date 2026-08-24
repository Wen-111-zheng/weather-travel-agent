# -*- coding: utf-8 -*-
"""意图识别 Agent（PocketFlow 封装）：调用 core.intent。"""
from pocketflow import Node
from agents.core import intent


class IntentAgent(Node):
    def prep(self, shared):
        return shared["question"]

    def exec(self, question):
        return intent(question)

    def post(self, shared, prep_res, exec_res):
        shared["intent"] = exec_res
        shared["cities"] = exec_res.get("cities", [])
        shared["preferences"] = exec_res.get("preferences", [])
        return exec_res.get("action", "chat")
