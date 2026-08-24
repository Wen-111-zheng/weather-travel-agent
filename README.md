# 多智能体天气出行助手（weather-travel-agent）

> 升级自「单 Agent 天气查询」项目。从 **1 个 Agent + 1 个工具 + 本地脚本（toy 级）** 演进为 **多 Agent 协作 + MCP 工具协议 + RAG 知识库 + 长期记忆 + 工程化容错 + 可部署** 的完整 Agent 系统，可直接写进「AI Agent 工程师」简历。

---

## 一、为什么升级（难度定位）

原天气 Agent 仅：单 Agent（ReAct 三节点）、单工具（Open-Meteo）、无 RAG / 无记忆 / 无 MCP / 无评测 / 无部署——属于面试官能一眼归类为 **"toy / demo 级"** 的项目。

对标 2026 年真实 Agent 工程师 JD（中科曙光 / 联想应届 / 出门问问 / 腾讯视频 / 立讯精密等），市场要求：**多 Agent 协作、Tool Use / MCP、长短期记忆、RAG 全链路、工程化（重试/容错/评测/CI-CD/部署）**。本项目逐项补齐。

## 二、架构

```
                          ┌─────────────────────────────────────┐
   用户问题 ──► IntentAgent│ 意图识别 + 城市/偏好抽取 (LLM)        │
                          └───────────┬───────────┬─────────────┘
                             weather / travel      │ chat
                                  │               ▼
                          ┌───────▼────────┐   ChatAgent (兜底闲聊)
                          │ WeatherAgent  │  (BatchNode 多城市并行)
                          │  via MCP 协议 │   调用 get_weather MCP Tool
                          │  取真实天气   │
                          └───────┬───────┘
                                  ▼
                          ┌───────────────┐  RAG 检索(知识库) + 长期记忆(用户画像)
                          │ AdviceAgent   │  → 生成个性化出行/穿衣建议
                          └───────────────┘
```

- **多 Agent 协作**：IntentAgent → WeatherAgent（多城市并行）→ AdviceAgent；ChatAgent 兜底。
- **MCP 工具协议**：天气查询封装为标准 MCP stdio Server（`mcp/weather_mcp_server.py`），Agent 通过 `tools/list` + `tools/call` 动态发现并调用，非硬编码。
- **RAG 知识库**：出行/穿衣/城市气候知识，`BAAI/bge-m3`（SiliconFlow）向量检索 + 纯 Python 余弦；无 key 时关键词回退。
- **长期记忆**：用户画像（常问城市频次 + 偏好标签）JSON 持久化，跨轮次复用，避免重复询问偏好。
- **工程化容错**：天气工具含 重试 / 超时 / 限流 / 兜底，链路不中断。
- **可部署**：FastAPI 封装 HTTP 服务 + Dockerfile + docker-compose。

## 三、量化评测（eval/metrics.json，真实 DeepSeek + 真实 Open-Meteo 跑出）

| 指标 | 数值 | 说明 |
|---|---|---|
| 任务成功率 | **100%** | 10 条用例均返回有效回答 |
| 任务路由准确率 | **100%** | 闲聊 vs 任务 完美分离 |
| 意图识别准确率 | 90% | 1 例天气/出行边界句（两路径功能等价，均走 天气→建议） |
| RAG 检索命中率 | **100%** | 检索结果覆盖预期知识标签 |
| 天气工具兜底率 | **0%** | 真实 API 稳定，无需兜底 |
| 平均端到端时延 | ~7.0s | 真实大模型 + MCP 子进程调用 |

> 复现：`PYTHONPATH=<PocketFlow目录> python eval/run_eval.py`（需 `DEEPSEEK_API_KEY`；无 key 自动回退启发式，仍可跑通演示）。

## 四、运行方式

```bash
# 1) 命令行（需把 PocketFlow 源码目录加入 PYTHONPATH）
export PYTHONPATH=/path/to/PocketFlow
export DEEPSEEK_API_KEY=sk-xxx        # 可选；无则回退启发式
python main.py "北京和深圳天气怎么样，带宝宝出门"

# 2) HTTP 服务
pip install -r requirements.txt
uvicorn api.app:app --host 0.0.0.0 --port 8000
# POST /chat  {"question":"北京天气怎么样，带宝宝"}

# 3) Docker
docker compose up --build
```

## 五、文件结构

```
weather-travel-agent/
├── config.py                 # LLM 模式（真实/启发式回退）
├── utils/
│   ├── llm.py               # LLM 适配层（DeepSeek + 离线兜底）
│   └── weather_client.py    # 真实天气工具（重试/超时/限流/兜底）
├── memory/user_profile.py    # 长期记忆（用户画像双轨存储）
├── rag/
│   ├── corpus.py            # 知识库语料
│   └── knowledge_base.py    # RAG 检索（bge-m3向量 / 关键词回退）
├── mcp/
│   ├── weather_mcp_server.py# MCP stdio 服务器（get_weather Tool）
│   └── mcp_client.py        # MCP 客户端（子进程 stdio JSON-RPC）
├── agents/                  # IntentAgent / WeatherAgent / AdviceAgent / ChatAgent
├── flow.py                  # 多 Agent 编排（PocketFlow Flow）
├── main.py                  # CLI 入口
├── eval/                    # 评测集 + 评测脚本 + metrics.json
├── api/app.py               # FastAPI 服务
├── Dockerfile / docker-compose.yml
└── requirements.txt
```

## 六、简历可写的标准化描述（STAR）

> **多智能体天气出行助手**（Python / PocketFlow / MCP / RAG）
> - **背景**：原单 Agent 天气查询项目过于简单（toy 级），为对标 Agent 工程师岗位要求，重构为多智能体系统。
> - **职责**：基于 PocketFlow 设计 Intent→Weather→Advice 多 Agent 编排；将天气查询封装为**标准 MCP Tool**（手写 JSON-RPC stdio 服务器，无需第三方 SDK）；接入 **RAG 知识库**（bge-m3 向量检索 + 纯 Python 余弦）与**长期记忆**（用户画像），生成个性化出行建议。
> - **难点/优化**：工具调用加入重试/超时/限流/兜底保证链路不中断；用评测集量化效果。
> - **结果**：任务成功率 100%、RAG 检索命中 100%、天气工具兜底率 0%；支持 FastAPI + Docker 部署。

## 七、与旧版对比（升级点一览）

| 维度 | 旧版（toy） | 升级版 |
|---|---|---|
| Agent 数量 | 1 | 4（意图/天气/建议/闲聊） |
| 工具接入 | 硬编码调用 | 标准 MCP 协议 |
| RAG | 无 | 有（向量 + 余弦） |
| 记忆 | 无 | 长期记忆（用户画像） |
| 工程化 | 无 | 重试/超时/限流/兜底 |
| 评测 | 无 | 量化指标体系 |
| 部署 | 本地脚本 | FastAPI + Docker |
