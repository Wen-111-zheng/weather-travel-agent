# -*- coding: utf-8 -*-
"""闲聊 Agent（PocketFlow 封装）：调用 core.chat。"""
from pocketflow import Node
from agents.core import chat


class ChatAgent(Node):
    def prep(self, shared):
        return shared["question"]

    def exec(self, question):
        return chat(question)

    def post(self, shared, prep_res, exec_res):
        shared["answer"] = exec_res
        return "done"
