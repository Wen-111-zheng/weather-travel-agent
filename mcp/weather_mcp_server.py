# -*- coding: utf-8 -*-
"""MCP 标准 stdio 服务器：把真实天气查询暴露为 MCP Tool（get_weather）。

- 遵循 MCP（Model Context Protocol）JSON-RPC 规范（2024-11-05）
- 可被任意 MCP 客户端接入（Claude Desktop / Cursor / 自研 Agent）
- 本文件不依赖第三方 MCP SDK，手写最小实现，便于理解与审计

协议要点：
  initialize -> tools/list -> tools/call
  通过 stdin 逐行读 JSON-RPC 请求，stdout 逐行写 JSON-RPC 响应
"""
import os
import sys
import json

# 让服务器能 import utils.weather_client
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.weather_client import get_weather

TOOLS = [{
    "name": "get_weather",
    "description": "查询指定城市的实时天气（温度 / 天气状况 / 风速），基于 Open-Meteo，免费无需 key。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名，如 北京"}
        },
        "required": ["city"],
    },
}]


def handle(req):
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "weather-mcp-server", "version": "1.0"},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = req.get("params", {}).get("name")
        args = req.get("params", {}).get("arguments", {})
        if name == "get_weather":
            data = get_weather(args.get("city", ""))
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]
            }}
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown tool"}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        if "id" not in req:  # 通知类（如 notifications/initialized）忽略
            continue
        resp = handle(req)
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
