# -*- coding: utf-8 -*-
"""多智能体编排：用 PocketFlow 的 Flow 把 4 个 Agent 连成图。
IntentAgent ->(weather/travel)-> WeatherAgent -> AdviceAgent
IntentAgent ->(chat)-> ChatAgent
"""
from pocketflow import Flow
from agents.intent_agent import IntentAgent
from agents.weather_agent import WeatherAgent
from agents.advice_agent import AdviceAgent
from agents.chat_agent import ChatAgent


def create_weather_travel_flow():
    intent = IntentAgent()
    weather = WeatherAgent()
    advice = AdviceAgent()
    chat = ChatAgent()

    intent - "weather" >> weather
    intent - "travel" >> weather
    intent - "chat" >> chat
    weather - "advice" >> advice

    return Flow(start=intent)
