# -*- coding: utf-8 -*-
"""FastAPI 服务：把多智能体天气助手封装为 HTTP 接口，支持生产环境部署。

端点：
  POST /chat  {"question": "北京天气怎么样，带宝宝"} -> {"answer": "...", "intent": {...}}
  GET  /health
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "PocketFlow"))

from fastapi import FastAPI
from pydantic import BaseModel
from flow import create_weather_travel_flow

app = FastAPI(title="Weather-Travel Multi-Agent API", version="1.0")

# 单例 Flow（生产可改为每请求新建以保证线程安全）
flow = create_weather_travel_flow()


class ChatReq(BaseModel):
    question: str


@app.post("/chat")
def chat(req: ChatReq):
    shared = {"question": req.question}
    flow.run(shared)
    return {"answer": shared.get("answer"), "intent": shared.get("intent")}


@app.get("/health")
def health():
    return {"status": "ok"}
