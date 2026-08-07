# exa_agent_interview 知识库（Exa 搜索聚合）


## [1] LangChain 的 Agent 执行流程是怎样的？它和 Chain 有什么区别？ | AI 面试题 | AI Master

来源: https://www.ai-master.cc/interview/aieng-langchain-agent-001


LangChain 的 Agent 执行流程是怎样的？它和 Chain 有什么区别？ | AI 面试题 | AI Master

# LangChain 的 Agent 执行流程是怎样的？它和 Chain 有什么区别？

Agent 由 LLM 在运行时动态决定调用哪个工具，遵循「思考→选工具→执行→观察」的 ReAct 循环，由 AgentExecutor 驱动；Chain 则是预定义的固定流程。

常见出处：字节跳动 · 阿里巴巴 · 腾讯 · Microsoft

## 核心要点

- 能讲清 Agent 的本质：用 LLM 在运行时动态决定下一步调用哪个工具，而非提前编排好步骤
- 能背出 ReAct 循环：思考（Thought）→ 选工具与入参（Action）→ 执行工具 → 观察结果（ Observation）→ 回到思考，直到得出最终答案，整个循环由 AgentExecutor 驱动
- 能说清与 Chain 的区别：Chain 是预定义、确定性的固定流程（输入→步骤A→步骤B→输出），Agent 是运行时由模型决策的不确定流程
- 能点出 2026 的工程现状：复杂、多步、需要分支与状态的 Agent 推荐用 LangGraph 显式建图，旧的 AgentExecutor 适合简单单 Agent 场景

## 标准回答

### 一、Agent 是什么

Agent 是一个以 LLM 为决策核心的循环系统。它拿到用户目标后，不走固定脚本，而是每一步都让模型读取当前状态、判断「下一步该做什么」——是调用某个工具，还是已经可以给出最终答案。

### 二、ReAct 执行流程

主流 Agent 遵循 ReAct（Reasoning + Acting）范式，单步分为：

- Thought（思考）：模型推理当前要解决什么子问题。
- Action（行动）：模型输出要调用的工具名与结构化入参。
- Observation（观察）：执行工具，把返回结果喂回上下文。 这三步（Thought→Action→Observation）首尾相接构成一个循环，由 AgentExecutor 反复驱动：它负责解析模型输出、真正执行工具、把 Observation 拼回 prompt，并控制最大迭代次数、超时与异常处理，直到模型给出 Final Answer。

### 三、和 Chain 的区别

- Chain：开发者预先编排好的固定流程，步骤与顺序在编码时就确定，可重复、可预测，适合「提示→检索→改写→输出」这类确定性任务。
- Agent：流程在运行时由模型动态生成，调用几次工具、调用哪些、什么时候停，都不固定，灵活但更难预测和调试。 一句话：Chain 把控制流写死在代码里，Agent 把控制流交给 LLM。

### 四、2026 的选型现状

LangChain 早期的 `initialize_agent` / AgentExecutor 已不再是构建复杂 Agent 的首选。官方现在推荐用 LangGraph 把 Agent 建模成显式的状态图（节点 = 步骤，边 = 转移条件），天然支持分支、循环、人工介入（ human-in-the-loop）、持久化与多 Agent 协作。简单的单 Agent、单工具场景仍可用 AgentExecutor，但生产级复杂编排几乎都迁到了 LangGraph。

## 常见误区

⚠️ 常见踩坑

误区一：容易答偏的地方：把 Agent 当成「更高级的 Chain」而无脑替换——Agent 每步都要额外的 LLM 推理，延迟更高、成本更贵、行为更难预测，能用确定性 Chain 解决的固定流程就不该上 Agent；同时别再把 AgentExecutor 当成 2026 构建复杂 Agent 的标准答案，复杂编排应优先 LangGraph。

## 追问

追问 1：AgentExecutor 是怎么防止 Agent 陷入死循环的？

它内置了 max_iterations（最大迭代步数）和 max_execution_time（最大执行时长）两道闸：超过上限就强制停止并返回当前结果或报错。此外可设置 early_stopping_method 控制到限时是直接停还是再让模型生成一次收尾答案。生产中通常还会在工具层加幂等与重试上限，避免模型反复调用同一个失败工具。

追问 2：ReAct 和 Function Calling（工具调用）是什么关系？

ReAct 是一种「思考-行动」交替的推理范式，最早靠纯文本约定 Thought/Action 格式、再用正则解析。 Function Calling 是模型原生支持的结构化工具调用能力，模型直接输出 JSON 形式的工具名与参数，无需脆弱的文本解析。2026 的实践是用 Function Calling 作为底层执行机制，ReAct 作为上层的循环编排思路，二者互补而非互斥。

追问 3：为什么 LangGraph 比 AgentExecutor 更适合复杂 Agent？

AgentExecutor 把控制流隐藏在一个固定的 while 循环里，分支、回退、并行、人工审批都很难表达。LangGraph 把流程显式建成有向图：节点是计算步骤，边是带条件的状态转移，可以画出循环和分叉，支持检查点持久化（崩溃可恢复）、中断后等人工输入再继续、以及多个 Agent 作为子图协作。可控性、可观测性和可恢复性都远强于黑盒的 AgentExecutor。

## 🔗 相似问题

同一考点的不同问法，换着练更稳

- 中级 AI 工程化
- 如何在 LangChain 中实现 Function Calling 与自定义 Tool？
- 高级 AI 工程化
- LangChain 与 LangGraph 有什么区别？LangGraph 的编排原理是什么？
- 中级 AI Agent
- 什么是 ReAct 模式？它如何解决 Agent 的推理与行动问题？
- 中级 AI 工程化
- LangChain 的 Callback 回调机制是什么？有什么用？
- 初级 AI 工程化
- LangChain 的 Chain 是什么？有哪些常见类型？
- 中级 AI 工程化
- LangChain 的 LCEL 表达式语言是什么？有什么优势？

## 延伸学习

按主题分类的相关资源，便于系统复习


## [2] 从ReAct到Multi-Agent：LangGraph如何实现智能体间的无缝协作？从ReAct到Multi-Agent - 掘金

来源: https://juejin.cn/post/7571972751528411172


从ReAct到Multi-Agent：LangGraph如何实现智能体间的无缝协作？从ReAct到Multi-Agent - 掘金

# 从ReAct到Multi-Agent：LangGraph如何实现智能体间的无缝协作？

2025-11-13 251 阅读8分钟

## 从ReAct到Multi-Agent：LangGraph如何实现智能体间的无缝协作？

## 为什么要“多智能体”？

- 智能体（Agent）是什么 本质是一个能感知环境、基于策略行动以实现目标的“自主体”。在 LangChain/LangGraph 中，哪怕最简单的对话循环也可视为一个智能体。

- 具备感知（输入）、决策（策略/推理）、行动（工具/调用）、学习（记忆/更新）能力。
- 形式上可以是软件角色、机器人、业务微服务、甚至一个“LLM + 工具”组合。

- 为什么会走向多智能体（Multi-agent） 单体智能体在复杂问题上会遭遇三类瓶颈：

- 工具过载：工具太多导致“调用哪个”的决策困难。
- 上下文负担：长对话导致推理退化。
- 领域专精冲突：规划、检索、计算、执行等专业能力难以在单一提示词里兼顾。 解决方法是“模块化 + 专精化”：将系统拆分为多个职责单一的小智能体，组合成中/大型系统。

- 多智能体的核心收益

- 模块化：开发、测试、维护成本更低。
- 专精化：专家智能体的鲁棒性更强。
- 可控性：通信/交接路径与策略可显式定义，而不是完全交给 LLM 即兴发挥。

## 五种典型架构

- 网络（Fully-connected Network） 任意智能体都可与其他智能体通信。灵活但易“泛滥”，适合探索性、弱流程约束场景。
- 监督者（Supervisor） 引入一个“调度/路由”智能体，由它决定调用哪个专家。结构清晰，利于审计与限流。
- 监督者（工具调用变体） 把专家抽象为“工具”，监督者是 ReAct 智能体，通过工具调用来路由。利于快速落地。
- 层级（Hierarchical） 多个团队各自有监督者，顶层再由总监督者统筹。适合大规模系统或多产品线场景。
- 自定义工作流（Deterministic/Dynamic Mix） 部分边是固定顺序，部分由 LLM 通过`Command`动态路由。工程中较常见的折中方案。

如果你不确定选哪种架构，先用“监督者（工具调用）”起步，随后按复杂性迭代。

## Handoffs & Command

- 交接概念 智能体执行完当前职责后，决定“结束/继续/转交给他人”。交接的关键是显式描述：

- 目标智能体：`goto`
- 携带负载（状态更新）：`update`
- 图域（在哪个图生效）：`graph`，常见为当前图或`Command.PARENT`（从子图跳回父图）

- 最小 Command 模式

- 智能体节点函数返回`Command`，用于控制下一步路由；否则返回状态更新结束当前轮次。
- 在工具调用场景中，务必插入配对的“工具结果消息”，以满足多数 LLM 提供商的协议约束（每个`ai_msg`的工具调用，必须跟一个`tool`消息）。

- 常见交接手法

- 直接在智能体节点里决策，返回`Command`。
- 把交接包装成一个“工具”，由 LLM 以工具调用的方式触发交接（显著提升统一性）。
- 子图内要交接到父图的其他智能体时，设置`graph=Command.PARENT`。

## 智能体通信与状态设计

- 统一 state（共享消息） 图中的每一步都接收并产出`state`，通常包含`messages`。共享完整“草稿”（推理过程）能提升整体推理能力，但要提防上下文爆炸。
- 异构 state（私有草稿 + 共享摘要） 各智能体维护自己格式的内部状态，借助输入/输出转换与父图 state 对接。

- 优点：清晰边界、可做“信息最小化共享”。
- 技巧：交接时只共享“上一条 AI 回复 + 工具回执”，而非全部草稿。

- 工具调用与负载 监督者作为 ReAct 节点时，工具的参数就是负载。LangGraph 支持将父图 state 注入到工具（例如`InjectedState`），实现“带记忆的交接”。

## 三种Handoff模式对比与最小代码片段

#### 1. 直接 Command 交接（节点内路由）

- 适用：两个或少数几个智能体的网络架构，逻辑简单、路由清晰。
- 关键点：当`ai_msg.tool_calls`非空，插入工具结果消息，再`goto`下一个智能体。

```
from typing_extensions import Literalfrom langgraph.types import Commandfrom langgraph.graph import MessagesStatefrom langchain_core.tools import tool@tooldef transfer_to_multiplication_expert():    """向乘法智能体寻求帮助（只用于表明交接意图）"""    returndef addition_expert(state: MessagesState) -> Command[Literal["multiplication_expert", "__end__"]]:    system_prompt = "你是加法专家。若需乘法，请先完成加法，再交接。"    messages = [{"role": "system", "content": system_prompt}] + state["messages"]    ai_msg = model.bind_tools([transfer_to_multiplication_expert]).invoke(messages)    if ai_msg.tool_calls:        tool_call_id = ai_msg.tool_calls[-1]["id"]        tool_msg = {"role": "tool", "content": "成功交接", "tool_call_id": tool_call_id}        return Command(goto="multiplication_expert", update={"messages": [ai_msg, tool_msg]})    return {"messages": [ai_msg]}

```

- 常见坑

- 遗漏工具结果消息：导致提供商报错或上下文不同步。
- 无限交接：加步数上限或终止条件。

- 建议引入步数预算：

```
MAX_STEPS = 8def guard_and_return(cmd_or_update, state):    steps = state.get("steps", 0) + 1    if steps > MAX_STEPS:        return {"messages": [{"role": "assistant", "content": "超出步数预算，结束。"}]}    if isinstance(cmd_or_update, Command):        cmd_or_update.update = {**cmd_or_update.update, "steps": steps}        return cmd_or_update    return {"messages": cmd_or_update["messages"], "steps": steps}

```

#### 2. 交接工具（handoff tool）

- 适用：每个智能体是一个“子图”，通过工具将控制权交还父图并路由到目标智能体。
- 关键点：在工具中返回`Command(goto=..., graph=Command.PARENT, update=...)`。

```
from typing import Annotatedfrom langchain_core.tools.base import InjectedToolCallIdfrom langgraph.prebuilt import InjectedStatefrom langchain_core.tools import toolfrom langgraph.types import Commanddef make_handoff_tool(*, agent_name: str):    tool_name = f"transfer_to_{agent_name}"    @tool(tool_name)    def handoff_to_agent(        state: Annotated[dict, InjectedState],        tool_call_id: Annotated[str, InjectedToolCallId],    ):        tool_message = {            "role": "tool",            "content": f"成功交接到 {agent_name}",            "name": tool_name,            "tool_call_id": tool_call_id,        }


## [3] 2026年的 ReAct Agent架构解析：原生 Tool Calling 与 LangGraph 状态机-阿里云开发者社区

来源: https://developer.aliyun.com/article/1731087


2026年的 ReAct Agent架构解析：原生 Tool Calling 与 LangGraph 状态机-阿里云开发者社区

# 2026年的 ReAct Agent架构解析：原生 Tool Calling 与 LangGraph 状态机

简介： 本文介绍2026年演进版ReAct架构下的Research Brief Agent：摒弃脆弱的字符串解析（如"Thought:/Action:"），采用原生结构化工具调用（JSON Schema）、消息账本式State管理、自动引用提取与Postgres持久化，实现可复现、可审计、带真实URL引用的自动化研究简报生成。

ReAct（Reason + Act）架构要解决的问题是开放式研究里最经典的问题。本文要做的是一个 Research Brief Agent：会上网搜索、抓取真实 URL、压缩证据，最终产出一份带真实引用的结构化简报。重点不在于功能，而在于 正确写法——不再依赖那种脆弱的 "Thought: / Action:" 字符串解析。

## 早期 ReAct 留下的问题

ReAct 论文最初证明了，让 LLM 在动手之前先把推理写出来，效果会明显更好。

那时候的实现可以说就是 prompt hack。给模型一段这样的提示：

```
You have access to tools. You must use this format: Thought: [your thought], Action: [tool_name], Action Input: [tool_input].

```

模型吐回一段字符串，Python 用正则去抠工具名和参数，工具运行的结果再以

```
Observation: [result]

```

的形式拼回 prompt 里。

demo 阶段勉强能跑到了生产环境就问题成堆。模型对格式的幻觉源源不断：一会儿漏掉

```
Action Input:

```

前缀，一会儿调用一个根本不存在的工具，正则当场就崩。

## 2026 年的 ReAct：原生工具调用

这套写法早就被淘汰了，但Reason、Act、Observe 这三段核心节奏依然成立，只是执行模型完全换了一种思路。

现在的工具使用系统不再做字符串解析，而是原生的、结构化的 API tool calling。schema 校验由 LLM 提供方负责——OpenAI、Anthropic、Google 都是如此——严格性放在他们那一侧。

新的 ReAct 循环大致是这样：

1. Reason：LLM 看一遍会话历史，判断还缺什么信息。
2. Act：LLM 发出一段严格的 JSON tool call payload，例如`{"name": "search_web", "arguments": {"query": "react agent failures"}}`。
3. Observe：LangGraph 运行时执行工具，把带有结果的`ToolMessage`追加回 state。

循环一直跑到 LLM 觉得证据足够，然后输出一段普通的文本回复，而不是再发一个 tool call。

## Research Brief Agent：State 与 Schema

动手开始写。第一件事是定义 state schema。

确定性 workflow 里的 state 通常是一组离散字段——

```
raw_diff

```

、

```
has_critical_findings

```

之类。但开放式 ReAct 循环里，state 主要表现为一份 append-only 的消息账本。

只有消息还不够。引用也要追踪：不光要让 LLM 写出一段总结，还得拿到一份能在 UI 里渲染的具体引用列表。

```
 from typing import Annotated, TypedDict  
from langchain_core.messages import BaseMessage  
from langgraph.graph.message import add_messages  
import operator  

class ResearchState(TypedDict):  
    topic: str  

    # 会话的核心账本
    messages: Annotated[list[BaseMessage], add_messages]  

    # 在循环过程中累积起来的证据库
    citations: Annotated[list[dict[str, str]], operator.add]  
    seen_urls: Annotated[list[str], operator.add]  

    # 防止无限循环的控制变量
    step_count: int  
    max_steps: int  
    stagnant_turns: int  

     final_brief: str

```

注意 reducer 的作用，

```
add_messages

```

让新消息追加而不是覆盖，

```
operator.add

```

给 citations 和 URL 列表做的是同样的事。在循环里维护历史，靠的就是这两件小工具。

## Search 与 Fetch

把图连起来之前得先有工具，一个常见错误是给 agent 一个返回完整原始 HTML 的工具——第一轮循环还没结束，上下文窗口就已经被冲爆。

下面两个普通的 HTTP 工具就够了：

```
search_web

```

找候选链接，

```
fetch_url

```

拉真正的正文。

```
 import json  
import urllib.request  
import urllib.parse  
from langchain_core.tools import tool  
import re  
import html  

def _http_get(url: str, timeout: int = 12) -> str:  
    with httpx.Client(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as client:  
        response = client.get(url)  
        response.raise_for_status()  
        return response.text  

@tool  
def search_web(query: str, max_results: int = 5) -> str:  
    """Search the web via DuckDuckGo Instant Answer API. Returns JSON list."""  
    try:  
        params = urllib.parse.urlencode({"q": query, "format": "json"})  
        payload = _http_get(f"https://api.duckduckgo.com/?{params}")  
        data = json.loads(payload)  

        # ...（提取 URL 与 snippet 的解析逻辑）...
        # 简洁起见，假设这里返回的 JSON 字符串结构为：
        # [{"url": "...", "title": "...", "snippet": "..."}]

        return json.dumps(results[:max_results])  
    except Exception as exc:  
        return json.dumps([{"url": "", "title": "error", "snippet": str(exc)}])  

@tool  
def fetch_url(url: str) -> str:  
    """Fetch and compress a URL into JSON: {url,title,snippet}."""  
    try:  
        raw_html = _http_get(url)  

        # 剥掉 script、style 与 HTML 标签，留下纯文本
        no_script = re.sub(r"<script[^>]*>.*?</script>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)  
        no_style = re.sub(r"<style[^>]*>.*?</style>", " ", no_script, flags=re.IGNORECASE | re.DOTALL)  
        text = re.sub(r"<[^>]+>", " ", no_style)  
        clean_text = html.unescape(re.sub(r"\s+"


## [4] 如何从零开始创建ReAct 代理（函数式API） - LangChain 文档

来源: https://github.langchain.ac.cn/langgraphjs/how-tos/react-agent-from-scratch-functional/


如何从零开始创建 ReAct 代理（函数式 API） - LangChain 教程

跳到内容

# 如何从头开始创建 ReAct 代理（函数式 API）¶

先决条件

本指南假定您熟悉以下内容

本指南演示了如何使用 LangGraph函数式 API实现 ReAct 代理。

ReAct 代理是一个工具调用代理，其操作如下：

1. 向聊天模型发出查询；
2. 如果模型没有生成工具调用，我们返回模型的响应。
3. 如果模型生成了工具调用，我们使用可用工具执行工具调用，将它们作为工具消息附加到我们的消息列表中，然后重复此过程。

## 设置¶

注意

本指南需要`@langchain/langgraph>=0.2.42`。

首先，安装本示例所需的依赖项

```
npm install @langchain/langgraph @langchain/openai @langchain/core zod

```

接下来，我们需要设置OpenAI（我们将使用的LLM）的API密钥

```
process.env.OPENAI_API_KEY = "YOUR_API_KEY";

```

为 LangGraph 开发设置 LangSmith

注册 LangSmith 以快速发现问题并提高 LangGraph 项目的性能。LangSmith 允许您使用跟踪数据来调试、测试和监控使用 LangGraph 构建的 LLM 应用程序 — 在此处了解更多入门信息

## 创建 ReAct 代理¶

现在您已经安装了所需的包并设置了环境变量，我们可以创建我们的代理了。

### 定义模型和工具¶

我们首先定义将用于示例的工具和模型。这里我们将使用一个简单的占位工具，它获取某个地点的天气描述。

本示例将使用 OpenAI聊天模型，但任何支持工具调用的模型都足够。

```
import { ChatOpenAI } from "@langchain/openai";
import { tool } from "@langchain/core/tools";
import { z } from "zod";

const model = new ChatOpenAI({
  model: "gpt-4o-mini",
});

const getWeather = tool(async ({ location }) => {
  const lowercaseLocation = location.toLowerCase();
  if (lowercaseLocation.includes("sf") || lowercaseLocation.includes("san francisco")) {
    return "It's sunny!";
  } else if (lowercaseLocation.includes("boston")) {
    return "It's rainy!";
  } else {
    return `I am not sure what the weather is in ${location}`;
  }
}, {
  name: "getWeather",
  schema: z.object({
    location: z.string().describe("location to get the weather for"),
  }),
  description: "Call to get the weather from a specific location."
});

const tools = [getWeather];

```

### 定义任务¶

1. 调用模型：我们希望使用消息列表查询我们的聊天模型。
2. 调用工具：如果我们的模型生成了工具调用，我们希望执行它们。

```
import {
  type BaseMessageLike,
  AIMessage,
  ToolMessage,
} from "@langchain/core/messages";
import { type ToolCall } from "@langchain/core/messages/tool";
import { task } from "@langchain/langgraph";

const toolsByName = Object.fromEntries(tools.map((tool) => [tool.name, tool]));

const callModel = task("callModel", async (messages: BaseMessageLike[]) => {
  const response = await model.bindTools(tools).invoke(messages);
  return response;
});

const callTool = task(
  "callTool",
  async (toolCall: ToolCall): Promise<AIMessage> => {
    const tool = toolsByName[toolCall.name];
    const observation = await tool.invoke(toolCall.args);
    return new ToolMessage({ content: observation, tool_call_id: toolCall.id });
    // Can also pass toolCall directly into the tool to return a ToolMessage
    // return tool.invoke(toolCall);
  });

```

### 定义入口点¶

我们的入口点将处理这两个任务的编排。如上所述，当我们的`callModel`任务生成工具调用时，`callTool`任务将为每个工具调用生成响应。我们将所有消息附加到一个消息列表中。

```
import { entrypoint, addMessages } from "@langchain/langgraph";

const agent = entrypoint(
  "agent",
  async (messages: BaseMessageLike[]) => {
    let currentMessages = messages;
    let llmResponse = await callModel(currentMessages);
    while (true) {
      if (!llmResponse.tool_calls?.length) {
        break;
      }

      // Execute tools
      const toolResults = await Promise.all(
        llmResponse.tool_calls.map((toolCall) => {
          return callTool(toolCall);
        })
      );

      // Append to message list
      currentMessages = addMessages(currentMessages, [llmResponse, ...toolResults]);

      // Call model again
      llmResponse = await callModel(currentMessages);
    }

    return llmResponse;
  }
);

```

## 用法¶

要使用我们的代理，我们使用消息列表调用它。根据我们的实现，这些可以是 LangChain消息对象或 OpenAI 风格的对象

```
import { BaseMessage, isAIMessage } from "@langchain/core/messages";

const prettyPrintMessage = (message: BaseMessage) => {
  console.log("=".repeat(30), `${message.getType()} message`, "=".repeat(30));
  console.log(message.content);
  if (isAIMessage(message) && message.tool_calls?.length) {
    console.log(JSON.stringify(message.tool_calls, null, 2));
  }
}

// Usage example
const userMessage = { role: "user", content: "What's the weather in san francisco?" };
console.log(userMessage);

const stream = await agent.stream([userMessage]);

for awai
