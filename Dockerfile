FROM python:3.11-slim

WORKDIR /app

# 依赖先拷（利用 Docker 层缓存）：requirements 位于 weather-travel-agent/ 下
COPY weather-travel-agent/requirements.txt weather-travel-agent/requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt

# 源码与本地依赖 PocketFlow（二者是 01-Agent 下的同级目录，构建上下文见 docker-compose.yml 的 context: ..）
COPY weather-travel-agent/ /app
COPY PocketFlow/ /app/PocketFlow

ENV PYTHONPATH=/app:/app/PocketFlow
ENV PYTHONIOENCODING=utf-8

EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
