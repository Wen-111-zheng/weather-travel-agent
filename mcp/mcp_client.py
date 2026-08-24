# -*- coding: utf-8 -*-
"""极简 MCP 客户端：以子进程方式拉起 weather_mcp_server，通过 stdio JSON-RPC 调用 get_weather。

证明 Agent 不是硬编码调用工具，而是遵循 MCP 协议动态发现并调用工具（tools/list + tools/call）。
"""
import os
import sys
import json
import subprocess

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_mcp_server.py")
PY = sys.executable


class MCPWeatherClient:
    def __init__(self):
        self.proc = subprocess.Popen(
            [PY, SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "weather-travel-agent", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})

    def _recv(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if "id" in msg:
                return msg

    def _rpc(self, method, params):
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        return self._recv()

    def _notify(self, method, params):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()

    def list_tools(self):
        resp = self._rpc("tools/list", {})
        return resp.get("result", {}).get("tools", []) if resp else []

    def get_weather(self, city):
        resp = self._rpc("tools/call", {"name": "get_weather", "arguments": {"city": city}})
        if resp and "result" in resp:
            text = resp["result"]["content"][0]["text"]
            return json.loads(text)
        return {"city": city, "temp": "N/A", "condition": "MCP调用失败", "wind": "N/A"}

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
