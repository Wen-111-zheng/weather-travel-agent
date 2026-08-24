# -*- coding: utf-8 -*-
"""真实天气工具：Open-Meteo（免费、无需 key、国内可直连）。

工程化要点（对应简历"工具调用稳定性"）：
- 重试（retries）：网络抖动自动重试，指数退避
- 超时（timeout）：避免单点阻塞
- 限流（min interval）：保护上游 API
- 兜底（fallback）：连续失败返回确定性占位，保证 Agent 不崩溃
"""
import os
import re
import json
import time
import urllib.request
import urllib.parse

WEATHER_CODE_MAP = {
    0: "晴", 1: "大致晴朗", 2: "局部多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "中雨",
    56: "冻毛雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴伴冰雹",
}

_last_call_ts = 0.0
_MIN_INTERVAL = 0.3  # 简单限流：两次调用至少间隔 0.3s


def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "weather-travel-agent/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_weather(city, retries=3, timeout=8):
    """查询城市实时天气；失败重试，最终兜底返回占位数据。"""
    global _last_call_ts
    for attempt in range(retries):
        try:
            # 限流
            wait = _MIN_INTERVAL - (time.time() - _last_call_ts)
            if wait > 0:
                time.sleep(wait)
            _last_call_ts = time.time()

            geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
                {"name": city, "count": 1, "language": "zh", "format": "json"}
            )
            geo = _get_json(geo_url, timeout)
            if not geo.get("results"):
                return {"city": city, "temp": "未知", "condition": "未知", "wind": "未知",
                        "error": f"找不到城市：{city}"}
            loc = geo["results"][0]
            lat, lon = loc["latitude"], loc["longitude"]
            fc_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            })
            fc = _get_json(fc_url, timeout)
            cur = fc["current"]
            code = cur.get("weather_code", 0)
            return {
                "city": city,
                "temp": f"{cur.get('temperature_2m')}°C",
                "condition": WEATHER_CODE_MAP.get(code, "未知"),
                "wind": f"{cur.get('wind_speed_10m')} km/h",
            }
        except Exception as e:
            if attempt == retries - 1:
                # 兜底：保证 Agent 链路不中断
                return {"city": city, "temp": "N/A", "condition": "查询超时(已兜底)",
                        "wind": "N/A", "error": str(e), "fallback": True}
            time.sleep(0.5 * (attempt + 1))  # 指数退避
    return {"city": city, "temp": "N/A", "condition": "未知", "wind": "N/A"}
