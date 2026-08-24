# -*- coding: utf-8 -*-
"""天气获取 Agent（PocketFlow 封装）：调用 core.weather，并在 post 写入长期记忆。"""
from pocketflow import BatchNode
from agents.core import weather
from memory.user_profile import record_query


class WeatherAgent(BatchNode):
    def prep(self, shared):
        self.prefs = shared.get("preferences", [])
        return shared.get("cities", [])

    def exec(self, city):
        return weather([city])[0]

    def post(self, shared, prep_res, exec_res_list):
        shared["weather_data"] = exec_res_list
        # 写入长期记忆（城市频次 + 偏好），仅记录成功返回
        for i, city in enumerate(shared.get("cities", [])):
            wd = exec_res_list[i] if i < len(exec_res_list) else {}
            if not wd.get("fallback"):
                record_query(city, self.prefs)
        return "advice"
