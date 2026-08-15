# LangChain 1.x 工具（Tools）使用指南（2025+ 版本）

> 版本说明：本文档描述 **LangChain 1.x**（2025 年发布的 1.0 系列）的推荐用法。
> 旧版（v0.3 及更早）的 `AgentExecutor`、`create_react_agent`、手写 ReAct 循环
> 在 1.x 中已不是主推方式，1.x 用 `create_agent` 一站式组装 agent。

## 一、定义工具（1.x 仍然推荐 @tool）

用 `@tool` 装饰一个带类型注解和 docstring 的函数即可：

```python
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """查询某个城市的天气。"""
    return f"{city} 的天气是晴天"
```

docstring 会被模型用来理解工具的用途，务必写清楚参数含义。

## 二、推荐方式：create_agent 一键组装（1.x 主推）

`langchain.agents.create_agent` 把 LLM、工具、system prompt 编成一张
agent 执行图，模型决定调用工具 → 工具节点（ToolNode）自动执行 →
`ToolMessage` 自动回喂模型 → 直到模型输出最终答案，整个循环无需手写：

```python
from langchain.agents import create_agent

agent = create_agent(
    model=llm,                    # 任意 BaseChatModel
    tools=[get_weather, search],  # 工具列表
    system_prompt="你是天气助手。",
)

# 调用：传入消息列表，agent 自动跑完整工具循环
result = agent.invoke({"messages": [("user", "北京今天天气怎么样？")]})
```

需要控制执行状态时，可以自定义 `state_schema`（例如只承载 messages 的
TypedDict）；`create_agent` 默认状态即消息列表。

## 三、中间件 AgentMiddleware：迭代上限与错误回喂

1.x 用 `AgentMiddleware` 扩展 agent 执行链，常用钩子：

- `before_model(state, runtime)`：每次调用模型前执行（如迭代计数）
- `wrap_model_call(request, handler)`：包一层模型调用（如超限短路）
- `wrap_tool_call(request, handler)`：包一层工具执行（如把异常转成
  `ToolMessage("Error: ...")` 回喂给模型，而不是中断循环）

```python
from langchain.agents.middleware import AgentMiddleware

agent = create_agent(..., middleware=[MyMaxIterationsMiddleware(10)])
```

## 四、流式输出

1.x 编译后的 agent 支持 `stream()`：

```python
for mode, payload in agent.stream(
    {"messages": [...]},
    stream_mode=["messages", "updates"],
):
    if mode == "messages":
        msg, meta = payload   # token 级事件，可转发给前端
    else:
        # "updates" 节点级事件：{"model": {...}} / {"tools": {...}}
        ...
```

## 五、bind_tools 还能用吗？

可以。`model.bind_tools([...])` 是底层机制（让模型能输出 tool_calls），
`@tool` 定义的工具也能 `tool.invoke({...})` 直接调用做测试；但 1.x 的
**推荐姿势是 `create_agent`**——绑定、循环、工具执行、消息回喂都由平台
处理，业务代码不需要手动管理 ToolMessage 循环。

## 六、与旧版的差异速查

| 能力 | 旧版 v0.3- | 1.x（当前） |
| --- | --- | --- |
| 组装 agent | create_react_agent / AgentExecutor | `create_agent` |
| 工具执行 | 手写循环或 AgentExecutor | 内置 ToolNode，自动执行 |
| 扩展点 | 回调/自定义 Agent | `AgentMiddleware` 钩子 |
| 流式 | .stream() | .stream(stream_mode=[...])，事件更细 |

> 若看到资料里还在手写"模型返回 tool_calls → 手动 invoke → 拼 ToolMessage →
> 再喂回模型"的四步循环，那是旧版教学，1.x 已用 `create_agent` 自动化。
