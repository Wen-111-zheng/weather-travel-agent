# -*- coding: utf-8 -*-
"""极简 MCP 客户端：以子进程方式拉起 weather_mcp_server，通过 stdio JSON-RPC 调用 get_weather。

证明 Agent 不是硬编码调用工具，而是遵循 MCP 协议动态发现并调用工具（tools/list + tools/call）。

稳定性修复（2026-09-17）：
- 原实现 `_recv()` 直接 `stdout.readline()` 无限阻塞——天气子进程一旦失联（网络抖动/子进程异常），
  整个上层 HTTP 请求会被永久挂起（实测挂 7 分钟无响应）。
- 现改为「后台线程泵 stdout -> 队列 + 带超时的 queue.get」：每次等子进程回话最多 TIMEOUT 秒，
  超时返回 None -> get_weather 走「MCP调用失败」兜底，上层请求正常返回，绝不无限挂起。
"""
import os
import sys
import json
import queue
import time
import threading
import subprocess

try:
    from tracing import trace
except ImportError:
    # 追踪模块不可用（比如从别的目录直接跑）时，用空装饰器兜底，
    # 保证工具调用本身照常工作，绝不因为"装摄像头"把功能搞挂。
    def trace(*args, **kwargs):
        def deco(fn):
            return fn
        return deco

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_mcp_server.py")
PY = sys.executable


class MCPWeatherClient:
    # 每次等子进程回话的超时（秒）：正常查询秒级完成，20s 足够宽裕；
    # 异常时快速兜底，避免上层请求长时间等待甚至永久挂起。
    TIMEOUT = 20.0

    def __init__(self):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"   # 让子进程(天气服务器)以 UTF-8 输出
        self.proc = subprocess.Popen(
            [PY, SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",                # 客户端管道以 UTF-8 解码
            errors="replace",
            bufsize=1,
            env=env,
        )
        # 后台线程把子进程 stdout 持续泵进队列；主流程用带超时的 queue.get 等待响应，
        # 替代原先 readline() 的无限阻塞。
        self._lines = queue.Queue()
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "weather-travel-agent", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})

    def _pump_stdout(self):
        """后台线程：持续把子进程 stdout 的行塞进队列；流结束（子进程退出）塞 None 作终止标记。"""
        try:
            for line in self.proc.stdout:
                self._lines.put(line)
        except Exception:
            pass
        finally:
            self._lines.put(None)

    def _recv(self):
        """取下一条带 id 的 JSON-RPC 响应；整体受 TIMEOUT 约束，超时/流结束返回 None，绝不无限阻塞。"""
        deadline = time.time() + self.TIMEOUT
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                return None
            if line is None:
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
        try:
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
        except Exception:
            return None  # 子进程已死/管道断：等价于超时，走兜底
        return self._recv()

    def _notify(self, method, params):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()

    def list_tools(self):
        resp = self._rpc("tools/list", {})
        return resp.get("result", {}).get("tools", []) if resp else []

    @trace("MCP工具·get_weather", kind="tool")
    def get_weather(self, city):
        resp = self._rpc("tools/call", {"name": "get_weather", "arguments": {"city": city}})
        if resp and "result" in resp:
            text = resp["result"]["content"][0]["text"]
            return json.loads(text)
        # 子进程超时/失联（_recv 返回 None）也走这里：快速兜底，绝不让上层请求挂死。
        # 带 fallback 标记，编排层不会把失败数据写入长期记忆。
        return {"city": city, "temp": "N/A", "condition": "MCP调用失败", "wind": "N/A",
                "fallback": True}

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
