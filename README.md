# 多智能体天气出行助手（weather-travel-agent）

> 一个会查天气、还能结合你的偏好给出行建议的 AI Agent。
>
> 这不是一个「为了做而做」的项目，而是我学 Agent 时被真实问题一路逼着，从单 Agent 改到多 Agent 的产物。下面记的是我**自己折腾的全过程**——包括踩过的坑、对两个框架的吐槽、以及我亲手做过的几组对照实验。结论都是我自己跑出来的，不是抄教程。

---

## 一、我是怎么把这个项目做起来的（学习路径）

### 1. 起点：一个能查天气的单 Agent
最开始学 Agent 时，我做了一个最简单的版本：一个 Agent，直接调用 Open-Meteo 天气 API，输入城市名就返回温度。它跑通了「大模型思考 → 调用工具 → 拿到结果」这个最基本的循环，但所有逻辑都堆在同一个 Agent 里。

### 2. 卡住了：单 Agent 应付不了稍复杂的问题
当我试着问「北京和深圳天气怎么样，带宝宝出门穿什么」时，问题暴露了：
- 一个 Agent 要同时干「识别意图 + 查两个城市天气 + 生成穿衣建议」，prompt 越写越长、越容易出错；
- 想加个闲聊或出行建议功能，只能在原 Agent 里硬塞，越来越难维护。

这让我意识到一件事：**Agent 不是「越大越好」，而是「职责要分得清」**。

### 3. 学到「多 Agent 协作」：把任务拆开
我按"每个 Agent 只干一件事"的思路重构，拆成了四个：
- **IntentAgent**：只负责读懂用户想干嘛，抽到哪些城市、哪些偏好；
- **WeatherAgent**：只负责查天气（通过标准化的 MCP 工具）；
- **AdviceAgent**：只负责结合天气和知识库，给个性化出行 / 穿衣建议；
- **ChatAgent**：负责闲聊兜底，不当真任务时接住。

效果立竿见影：每个 Agent 的 prompt 变短、变专，改一个不影响其他。

### 4. 学到「工具标准化（MCP）」：别把工具写死在 Agent 里
原来天气调用是硬编码在 Agent 内部的。学到 MCP（Model Context Protocol）后，我把天气查询封装成一个**标准的 MCP Tool**——手写 JSON-RPC stdio 服务器（`mcp/weather_mcp_server.py`），不依赖任何第三方 SDK，Agent 通过 `tools/list` + `tools/call` 动态发现并调用。

收获是解耦：工具和 Agent 分开，以后换模型、加新工具，都不用动 Agent 本身。

### 5. 学到「RAG 知识库」：让 Agent 说话有依据
大模型本身不知道「带宝宝出门该注意什么」「某个城市几月多雨」这类领域知识。我建了一个出行 / 穿衣知识库，用 `BAAI/bge-m3` 向量检索 + 贝叶斯无关，纯 Python 余弦相似度做匹配（无 key 时自动回退关键词），让 AdviceAgent 先检索再生成。建议从"通用套话"变成了"有依据的建议"。

### 6. 学到「长期记忆」：让 Agent 记得我
好的助手不该每次都从头问。我用 `user_profile.json` 存用户画像（常问城市频次 + 偏好标签），Agent 跨轮次复用，不用反复问"你在哪个城市、有什么偏好"。

### 7. 学到「工程化与部署」：从「能跑」到「能演示给别人看」
- **容错**：天气 API 偶尔不稳，我给工具加了重试 / 超时 / 限流 / 兜底，保证链路不中断；
- **评测**：写了一份评测集量化效果，而不是凭感觉说"还行"；
- **部署**：最后用 FastAPI 封装 HTTP 服务、用 Dockerfile + docker-compose 打包，别人一条命令就能跑起来看效果。

写代码 → 部署 → 演示，这条线我自己完整跑通了。

---

## 二、最终架构

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
- **RAG 知识库**：出行 / 穿衣 / 城市气候知识，`BAAI/bge-m3`（SiliconFlow）向量检索 + 纯 Python 余弦；无 key 时关键词回退。
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

## 四、两套框架我都写了，也说说它们各自烂在哪

同一个多 Agent 逻辑，我分别用 **PocketFlow** 和 **LangGraph** 各实现了一遍（`flow.py` / `langgraph_flow.py`），用 `main.py --framework pocketflow|langgraph` 切换。这么做不是炫技，是想亲手验证「业务编排和框架解耦」这件事——同一套核心逻辑（`agents/core.py`）、同一套 MCP/RAG/记忆，换框架只是换"怎么串节点"。

但两个框架我都用真刀真枪写过，它们的毛病我也都踩过：

**PocketFlow 烂在哪**
- 状态流转靠节点 `post()` 写回一个共享 store，节点之间"谁改了什么"不够透明，调试时经常要手动打印 store 才看得清链路；
- action 路由是字符串硬编码，多 Agent 分支一多，路由逻辑容易散落在各节点里，可读性下降；
- 没有内置的 checkpointer / 可视化，复杂 flow 的"运行状态"得自己想办法看。

**LangGraph 烂在哪**
- 概念密度高（StateGraph / TypedDict / conditional_edges / reducer），简单任务也要先搭一套图，上手 overhead 偏大；
- 全局 TypedDict 状态在 Agent 多、字段多时，类型收敛和维护成本上来；
- 对"只想快速试一个想法"的场景，仪式感有点重。

**我的结论**：两个框架都能落地同一个 Agent，区别在"心智负担放在哪"——PocketFlow 轻但在大图里容易乱，LangGraph 重但调试和状态管理更稳。选哪个，看任务复杂度，不看流行度。

## 五、我亲手做过的实验与结论（上下文工程）

光"接上 RAG / 记忆"不够，我更想知道：**它们到底对 Agent 表现有多大影响**。我设计了几个对照，结论都来自我自己跑出来的现象：

- **假设 1**：RAG 比"把知识写进 prompt"更能给出有依据的建议。
  - 实验：关掉 RAG，AdviceAgent 退化为通用套话；打开 RAG，它先检索知识库再生成，输出能追到具体知识标签（评测集 RAG 命中率 100%）。
  - 结论：对"领域知识型回答"，RAG 的增益 > 单纯堆 prompt 长度。这也是我没把知识硬编码进 prompt 的原因。

- **假设 2**：长期记忆能减少"重复问偏好"的尴尬，但要克制。
  - 实验：`user_profile.json` 存常问城市 + 偏好标签，跨轮复用。
  - 结论：记忆该存"稳定偏好"，不该存"一次性上下文"——存多了反而污染下一轮。这是我自己踩过的坑。

- **假设 3**：prompt 结构（意图抽取 vs 直接生成）影响路由准确率。
  - 实验：把"意图识别"独立成 IntentAgent 后，闲聊/任务路由准确率到 100%；之前混在一个 Agent 里时，边界句经常跑偏。
  - 结论：把"判断"和"执行"拆开，比在同一个 prompt 里既要判断又要干活更稳。

> 这些结论不来自教程，来自我自己跑出来的现象。我不认为它们是"行业标准答案"，只是我在这个项目里实测出的判断。

## 六、我对「multi-agent 到底能做成什么」的判断

折腾完这个项目，我自己的看法（还在被新项目挑战）：

- **多 Agent 不是银弹**：对"查天气+给建议"这种中等复杂度任务，拆 4 个 Agent 收益明显；但对更简单的单轮问答，单 Agent + 好 prompt 反而更快更省。
- **真正值钱的是"接口标准化"**：MCP 让工具和 Agent 解耦后，换模型、加工具都不用动 Agent——这才是多 Agent 能规模化的关键，而不是"Agent 数量"。
- **Agent 的瓶颈常在"不确定性"**：天气有真实 API 兜底，但很多真实业务没有，幻觉和兜底策略才是落地难点。

## 七、运行方式

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

## 八、文件结构

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
├── langgraph_flow.py        # 多 Agent 编排（LangGraph StateGraph）
├── api/app.py               # FastAPI 服务
├── Dockerfile / docker-compose.yml
├── eval/                    # 评测集 + 评测脚本 + metrics.json
├── main.py                  # CLI 入口
└── requirements.txt
```

## 九、我还在折腾的

这是个我业余持续在改的项目，不为简历、就是想知道"再往前一步会卡在哪"：
- 想把 MCP 工具扩到更多数据源，看多工具下路由会不会乱；
- 想试 AutoGen / Dify / Coze 这类框架做对照，验证我对"框架各有烂处"的判断是不是普适；
- 想把评测集做成可回归的 CI，每次改代码都能看到指标有没有掉。

Agent 这条线我还在往前走。
