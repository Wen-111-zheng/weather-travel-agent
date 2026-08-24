FROM python:3.11-slim

WORKDIR /app

# 复制依赖与源码
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# PocketFlow 作为本地依赖一起 COPY（与 weather-travel-agent 同级）
# 构建上下文需包含 ../PocketFlow，见 docker-compose.yml 的 build context
ENV PYTHONPATH=/app:/app/PocketFlow
ENV PYTHONIOENCODING=utf-8

EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
