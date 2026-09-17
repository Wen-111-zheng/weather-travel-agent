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
  - 当前实现（以及一个我亲手踩过的坑）：偏好分两类——**临时上下文偏好**（带宝宝 / 带老人 / 陪老人 等）跑完本轮自动从 JSON 里清掉，稳定偏好（通勤 / 防晒 等）保留、跨轮复用。这件事我真实踩过坑、debug 过，完整经过写在第十节「踩坑实录」。

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
# 1) 命令行（PocketFlow 已自动加入 sys.path，无需手动设 PYTHONPATH）
export DEEPSEEK_API_KEY=sk-xxx        # 可选；无则回退启发式
# 方式 A：直接传问题（默认框架是 langgraph）
python main.py "北京和深圳天气怎么样，带宝宝出门"
# 想走 PocketFlow 编排（依赖更少、录制 demo 推荐，需显式指定）：
python main.py "北京和深圳天气怎么样，带宝宝出门" --framework pocketflow
# 方式 B：不传问题，进入交互式提问（先问"请问要咨询什么天气？"再回答）
python main.py
# 跑完一次后，临时偏好（带宝宝/带老人/陪老人）会自动从记忆中清掉，
# 不会污染下一轮"我一个人出门"的提示词（稳定偏好如通勤/防晒会保留）。

# 2) HTTP 服务（依赖见 requirements-api.txt：fastapi / uvicorn / langgraph）
pip install -r requirements-api.txt
uvicorn api.app:app --host 0.0.0.0 --port 8000
# LangGraph 分支：编译时挂 MemorySaver 检查点（按 thread_id 隔离），并发安全；记忆读写已加线程锁
# POST /chat  {"question":"北京天气怎么样，带宝宝", "framework":"pocketflow"}   # framework 可省，默认 langgraph
#   -> {"answer":"...", "intent":{...}, "cities":[...], "preferences":[...], "framework":"pocketflow"}
# 多轮对话：带上 thread_id，同一 thread_id 跨轮共享状态（上一轮城市/偏好被引用）；不带则每次新建隔离会话
#   POST /chat  {"question":"北京天气怎么样，带宝宝", "framework":"langgraph", "thread_id":"A"}
#   POST /chat  {"question":"那适合带宝宝吗",         "framework":"langgraph", "thread_id":"A"}   # 接上轮北京
# GET  /health -> {"status":"ok"}

# 3) Docker（构建上下文为 01-Agent 上级目录，自动包含 PocketFlow 与本项目）
docker compose up --build
# 容器内 uvicorn 监听 8000，宿主映射 8000:8000；启动时通过环境变量注入两个 Key：
#   DEEPSEEK_API_KEY / SILICONFLOW_API_KEY（在 01-Agent 目录的 .env 或 shell 中提供）
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
├── api/app.py               # FastAPI 服务（/chat 富返回 + /health）
├── Dockerfile / docker-compose.yml / .dockerignore
├── eval/                    # 评测集 + 评测脚本（run_eval / judge / cost / badcase / multi_turn_eval）+ 结果 JSON
├── tracing/                 # 调用链追踪模块（span / collector / storage / report）
├── tracing_demo.py          # 追踪演示脚本
├── docs/                    # 排错实录等过程文档
├── main.py                  # CLI 入口
├── requirements.txt         # 核心依赖（openai / requests）
└── requirements-api.txt     # 可选：HTTP 服务依赖（fastapi / uvicorn / langgraph）
```

## 九、我还在折腾的

这是个我业余持续在改的项目，不为简历、就是想知道"再往前一步会卡在哪"：
- 想把 MCP 工具扩到更多数据源，看多工具下路由会不会乱；
- 想试 AutoGen / Dify / Coze 这类框架做对照，验证我对"框架各有烂处"的判断是不是普适；
- 想把评测集做成可回归的 CI，每次改代码都能看到指标有没有掉。

Agent 这条线我还在往前走。

---

## 十、开发 Agent 时我踩过的坑（踩坑实录）

> 这一节专门记「我亲手踩过、debug 过、修好的坑」。不是教程里的标准答案，是我在做这个项目时真实撞上的。

### 坑 1：长期记忆「记性太好」，反而污染了下一轮

**现象**：我第一次问「深圳天气，我带宝宝出门」，AdviceAgent 给了带宝宝的穿衣建议；紧接着第二次问「广州天气，我一个人出门」——结果它**还是塞了一堆带宝宝建议**。我明明说了「一个人」。

**排查**：我先去翻记忆文件 `memory/user_profile.json`，发现里面躺着 `preferences: ["带宝宝"]`。顺着代码往上查：
- `agents/core.py` 第 59 行把「本轮偏好 + 历史偏好」无脑合并（`merged_prefs = preferences + profile["preferences"]`），再塞进提示词；
- `memory/user_profile.py` 的 `record_query()` 把意图识别抽到的**所有**偏好不分青红皂白全写进了 JSON——包括「带宝宝」这种「这一趟才有的临时上下文」。

**根因**：我把「一次性上下文」（这次带宝宝出门）和「稳定画像」（我常年通勤）混为一谈，都当永久记忆存了。

**修法**：在 `memory/user_profile.py` 里加了 `TEMPORARY_PREFERENCE_TAGS` 标签集合（带宝宝 / 带小孩 / 带老人 / 陪老人 / 扶老人 / 和老人 / 和宝宝 / 老人 等），以及 `clear_temporary_preferences()`——**每跑完一轮，就把这些临时标签从记忆里清掉**，稳定偏好（通勤 / 防晒 / 骑行）保留。`main.py` 在打印完回答后自动调用它，有清掉时还会打印一行 `[记忆清理] 已清掉本轮临时偏好：['带宝宝']...` 提示你。

**我学到的事**：记忆不是「记得越多越好」。Agent 的长期记忆要克制，只存真正稳定的那部分，否则它会变成「越帮越忙」的污染源。

### 坑 2：默认框架选错，demo 现场卡死

**现象**：一开始 `python main.py` 直接跑（默认是 LangGraph 框架），偶尔会卡在 `[LLM 模式] deepseek | [框架] langgraph` 之后半天不出结果。

**排查**：`utils/weather_client.py` 有 8 秒超时，天气接口不会卡；卡点只在 DeepSeek 调用处。而默认 LangGraph 分支内部有 `run_with_retry` 循环，API 偶发慢/丢包时会反复重试，表现就是「看着像卡死」。

**修法 / 建议**：录 demo 一律用 `--framework pocketflow`——依赖更少、响应链路短一半、不触发 LangGraph 的内部重试循环。如果 pocketflow 也偶发卡，那是 DeepSeek 那边的网络问题，多试几次就好，跟代码无关。这也顺带印证了我第四节那句「两个框架都能落地同一个 Agent，区别在心智负担放在哪」。

### 坑 3（更多实战排错见文档）

上面两坑是「记忆污染」和「默认框架卡死」。我在亲手测试多智能体功能时还连续撞上几个更偏工程的坑，已经单独整理进 **`docs/排错实录.md`**，面试或复盘时能直接拿来用，主要包括：

- **PowerShell 双编码坑**：`Invoke-RestMethod` 把 UTF-8 响应按 CP1252 解码成脏数据（`åå¬`）；内联中文 `curl -d '{...}'` 按 GBK 发出 → FastAPI 解析失败 `422`。修法是 payload 写 UTF-8 无 BOM 文件 + `curl -d "@p.json"`。
- **真实 LLM 被代理掐**：开着 `DEEPSEEK_API_KEY` + FlClash 代理时，真实调用被劫持返空 → 走闲聊分支、`cities=None`。修法是评测时关掉代理直连。
- **QuickEdit 冻结服务**：控制台点选日志文字 → stdout 写入阻塞 → 事件循环冻住 → 所有请求（含 `/health`）挂起。修法是取消 QuickEdit + 测试窗口与服务窗口分离。
- **MCP stdio 无超时**：原 `readline()` 无限阻塞，天气子进程卡住时整个请求挂死。修法是后台线程泵 stdout + 20s 超时（见下一节 fix 与 `mcp/mcp_client.py`）。

---

_（踩坑会持续往这里加；下一个想写的是「MCP stdio 子进程启动失败如何定位」。）_

---

## 十一、阶段三 ③：从「线性管道」升级到「Supervisor 协调 + Checkpoint 多轮」（已落地）

前面几节是一个能跑、能演示的单 Agent→多 Agent 系统。这一节记的是我把**编排层**再往前推一步：让多个 Agent 不是「写死串成一条线」，而是由一个「主管(Supervisor)」来协调，并且让对话**有记忆、能多轮**。

### 为什么要做
- 旧的 LangGraph 编排是固定管道：`intent → weather → advice`（或 `intent → chat`），分支用一行写死的 `route_intent` 规则判断。它能工作，但「谁来决定下一步」是硬编码的，谈不上真正的「多智能体协作」。
- 每来一个请求就新建一个 app 实例，请求结束状态即丢，**没有跨轮记忆**，所以「北京天气怎么样」之后问「那适合带宝宝吗」，助手根本不知道「那」指的是北京。

### 我怎么做的
- **Supervisor 节点**：新增一个 LLM 当「调度主管」的节点，它看用户这句话（以及上一轮回答）判断走「任务分支」(意图→天气→建议) 还是「闲聊分支」兜底。没有真实 LLM Key 时自动退化为规则路由（含「谢谢/你好」等闲聊词直接兜底，避免又被拿去查一遍天气），保证离线/演示照样能跑。
- **Checkpoint（检查点）**：编译 LangGraph 时挂上 `MemorySaver`，图的状态（城市、偏好、上一轮回答）按 `thread_id` 持久化。这样 LangGraph 才能跨请求「恢复」状态，而不是每次从零开始。
- **多轮上下文**：意图识别节点会把「上一轮回答」作为上下文并入（当前问题放最前，避免本地启发式误抽），并且本轮没抽到城市/偏好时，自动继承上一轮的——所以「那适合带宝宝吗」能正确接着北京答，而不是因为没城市走兜底。
- **接口升级**：`/chat` 增加可选 `thread_id`；同一个 `thread_id` 跨轮共享状态，不同 `thread_id` 互不串档；不带 `thread_id` 则每次新建隔离会话（向后兼容，单轮表现不变）。`main.py` 的 langgraph 路径也改成多轮交互循环。

### 验证（我跑出来的）
- 同一 `thread_id` 下：第一轮「北京天气怎么样，带宝宝」→ 第二轮「那适合带宝宝吗」，助手正确接上北京并给天气+建议；
- 不同 `thread_id` 互不干扰（北京会话 vs 上海会话各自独立）；
- PocketFlow 编排路径**一行没动**，单轮评测照常通过——进一步印证「核心能力与框架解耦」这件事；
- **评测落地（Checkpoint 验收关）**：`eval/multi_turn_eval.py` 已把 `thread_id` 焊进评测链路——langgraph 路径复用同一 `MemorySaver` + app 实例、按 `thread_id` 隔离，跨轮状态**真正持久**（之前每次新建 app 会丢状态）；数据集扩到 **20 会话 / 63 轮**，覆盖偏好继承 / 跨城市 / 闲聊插入 / 纠错 / 长多轮等场景，量化 `turn_pass_rate` / `avg_preference_recall` / `avg_repeat_rate`。本机真实 DeepSeek 跑分见 `metrics_multiturn_{framework}.json`。

> 局限：本地启发式（无 DeepSeek Key）的意图识别只认「建议/穿/出行」等触发词，不会抽「带宝宝」这类偏好；注入 `DEEPSEEK_API_KEY` 后真实大模型会正常抽取。多轮「城市」继承在两种模式下都生效。

---

## 十二、阶段三后面我又落地的三件事（RAG 混合检索 / 评测体系 / 调用链追踪）

第十节、十一节记的是「编排层」往前推的那一步。这一节记的是同一阶段里我顺手做扎实的另外三块：**让检索更准、让效果可量化、让链路可观测**。

### 1. RAG 混合检索（embedding + 关键词 + RRF 融合重排）

之前知识库检索只用 `bge-m3` 向量余弦。我把它升级成**混合检索**：

- **向量召回**：`BAAI/bge-m3` 句向量余弦，抓语义相近；
- **关键词召回**：对 query 做 bigram 切分，和知识条目做词面匹配，补向量召回「字面精准但语义飘」的漏；
- **RRF 融合重排**：两套结果按排名倒数加权融合（`score = Σ 1/(k+rank)`），再取 Top-N 喂给 AdviceAgent。

**我跑出来的结论**：纯向量在「带宝宝 / 防晒」这类短偏好词上容易飘，纯关键词又抓不到「宝宝出门要注意什么」的语义；混合之后检索命中更稳，建议也更贴知识库原文。无 `SILICONFLOW_API_KEY` 时自动退化成纯关键词回退，演示照样能跑。

### 2. 评测体系升级（LLM-as-Judge 五维 / 多轮 / 并发 / 成本 / BadCase）

把第三节那张「我自测的表」从「单轮启发式对不对」升级成可回归的工程化评测（`eval/`）：

- **LLM-as-Judge 五维**：用真实 DeepSeek 当裁判，对每条用例从「任务完成 / 路由准确 / 意图抽取 / 建议相关性 / 安全性」五个维度打分，不再是「看着还行」；
- **多轮对话评测（真·thread_id 验收关）**：`multi_turn_eval.py` + `multi_turn_set.json`（**20 会话 / 63 轮**）验证「带 thread_id 跨轮继承城市/偏好」确实生效；评测链路对 langgraph 复用同一 `MemorySaver` + app 实例、按 `thread_id` 隔离，Checkpoint 真正跨轮持久（pocketflow 走磁盘记忆对照）。量化 `turn_pass_rate` / `avg_preference_recall` / `avg_repeat_rate`，本机真实 DeepSeek 跑分见 `metrics_multiturn_{framework}.json`。
- **并发提速 + 线程安全**：`ThreadPoolExecutor` 并发跑用例，记忆读写加锁，60 题量级从串行十几分钟压到几分钟；
- **Token 成本折算**：`cost.py` 统计每轮 prompt/completion token 与折算金额，优化 prompt 时能看见「省了多少钱」；
- **BadCase 归因**：`badcase.py` 把失败用例按 6 类归因（路由错 / 意图漏 / 检索偏 / 建议偏 / 格式坏 / 超时），输出 `badcases_*.json` 方便定点修。

> 复现：`python eval/run_eval.py`（单轮）、`python eval/multi_turn_eval.py`（多轮），需 `DEEPSEEK_API_KEY`；无 key 自动回退启发式，仍可跑通。

### 3. 调用链追踪（tracing 模块 + traces.db）

为了知道「一次回答到底慢在哪、花了多少 token」，我写了个轻量追踪模块（`tracing/`）：

- **span**：给「意图识别 / 天气调用 / 知识检索 / 建议生成」每一步打点，记录起止时间、token、状态；
- **collector**：在 Agent 执行时收集 span；
- **storage**：落本地 `traces.db`（SQLite），可跨次查询；
- **report**：按 trace 汇总每步时延与 token，定位瓶颈。

`tracing_demo.py` 是一条可直接跑的演示。这东西不直接进主链路，是「观测层」——但它让我在优化时能拿数据说话，而不是猜。

> 这些能力都是我在这次阶段三里亲手加、亲手跑通的。它们和「编排」是两条线：编排决定「怎么串」，检索/评测/追踪决定「串出来好不好、怎么证明、怎么看」。
