# 验货 Agent 技术栈选型方案

> 版本：v1.0 ｜ 日期：2026-07-13
> 配套文档：AGENT_UPGRADE_ROADMAP.md
> 核心原则：**最大复用现有架构，最小引入新依赖，保持可控与可调试**

---

## 一、结论先行

**采用「openai SDK 原生 function calling + 手写轻量 agent loop」，不引入 LangChain/LangGraph 等重框架。**

理由：项目规模适中、团队精简、已在计费/次数控制中需要精确的 token 管理。手写循环最可控、最透明、最好调试。

---

## 二、分层技术栈

| 层级 | 选型 | 说明 | 新增成本 |
|------|------|------|---------|
| 模型层 | qwen-vl-plus（视觉）+ qwen-max（推理/工具调用） | 看图与推理分工；工具调用走 qwen-max | 复用+微调 |
| Agent 核心 | openai SDK `tools` 参数 + 自写 agent loop | 不用 LangChain | 复用 SDK |
| 工具执行层 | Python 函数 + JSON Schema + 工具注册表 | AQL引擎、历史检索等封装为工具 | 复用逻辑 |
| 数据层 | Supabase (PostgreSQL) | 已有 | 复用 |
| 记忆/向量检索（阶段三） | Supabase pgvector 扩展 | 不引入独立向量库（Pinecone/Chroma等） | 开启扩展 |
| 前端 | Streamlit（`st.chat_message` 承载多轮） | 阶段一改造为对话式 | 复用 |
| 部署 | Streamlit Cloud | 已有 | 复用 |

---

## 三、关键决策：为什么不用 LangChain / LangGraph

### 不用的理由
1. **qwen 原生支持 function calling**，手写 agent loop 仅需 30-50 行，无需框架
2. LangChain 抽象层厚、版本频繁变动、报错栈深，小团队是负担
3. token 消耗不透明，与现有计费/次数限制需求冲突
4. 手写循环可直接观察每一步真实 messages，出错秒定位
5. 现有代码已用 openai SDK 调 qwen（dashscope compatible mode），无缝衔接

### 何时才值得引入 LangGraph
- 工具数量 > 8-10 个
- 需要复杂多分支状态机 / 并行子任务编排 / 循环回退逻辑
- 当前阶段二仅 5 个工具，远未到此复杂度

---

## 四、Agent 主循环参考实现

```python
TOOL_REGISTRY = {
    "query_aql_plan": query_aql_plan,
    "search_defect_history": search_defect_history,
    # ...
}

def run_agent(messages, tools, max_steps=5):
    """手写 agent loop：模型请求工具→执行→回填→再推理，直到出报告或触顶"""
    for _ in range(max_steps):
        resp = client.chat.completions.create(
            model="qwen-max",
            messages=messages,
            tools=tools,
            temperature=0.3,
        )
        msg = resp.choices[0].message
        messages.append(msg)
        if not msg.tool_calls:              # AI 决定产出最终结论
            return msg.content
        for call in msg.tool_calls:         # AI 请求调用工具
            fn = TOOL_REGISTRY.get(call.function.name)
            if not fn:
                result = {"error": "unknown tool"}
            else:
                try:
                    result = fn(**json.loads(call.function.arguments))
                except Exception as e:
                    result = {"error": str(e)}
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
    # 兜底：超过步数强制出结论
    return _force_conclusion(messages)
```

---

## 五、工具 Schema 定义规范

每个工具 = Python 函数 + JSON Schema 描述。示例：

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_aql_plan",
            "description": "根据订单数量和AQL值查询ANSI Z1.4真实抽样方案(样本量/Ac/Re)",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_quantity": {"type": "integer", "description": "订单总数量"},
                    "aql_value": {"type": "string", "description": "如 'AQL 2.5'"},
                },
                "required": ["order_quantity", "aql_value"],
            },
        },
    },
    # search_defect_history / lookup_standard / ...
]
```

规范要点：
- description 写清楚"何时该调用"，让模型判断准确
- parameters 严格约束类型，配合 Python 侧校验
- 工具执行必须有 try/except 兜底，失败返回结构化 error 而非抛异常

---

## 六、模型分工策略

| 任务 | 模型 | 原因 |
|------|------|------|
| 看图识别缺陷 | qwen-vl-plus | 多模态视觉能力 |
| 工具调用 / 推理决策 | qwen-max | 文本推理与 function calling 更强 |
| （可选降本）简单判定 | qwen-plus | 成本优化 |

注意：视觉与工具调用可能需两次不同模型调用，或用支持多模态+工具的统一模型。需实测 qwen-vl 系列的 function calling 支持度，若不足则采用"vl 看图 → max 决策"两段式。

---

## 七、向量检索方案（阶段三）

**用 Supabase pgvector，不引入独立向量数据库。**

- Supabase 底层是 Postgres，`create extension vector` 即可开启
- 缺陷描述 embedding 存同一库，与业务数据同事务、同备份
- 避免多一套基础设施（Pinecone/Chroma/Weaviate）的运维和成本
- embedding 模型：qwen text-embedding 系列 或 开源 bge 系列

---

## 八、依赖清单变化

| 依赖 | 现状 | 升级后 | 备注 |
|------|------|--------|------|
| openai | 已有 | 保留 | agent loop 复用 |
| streamlit | 已有 | 保留 | 多轮用 chat 组件 |
| supabase | 已有 | 保留 | + pgvector（阶段三）|
| LangChain | 无 | **不引入** | 明确不用 |
| 向量库 | 无 | **不引入** | 用 pgvector 替代 |

**结论：阶段一、二几乎零新依赖，纯逻辑改造。阶段三仅开启 pgvector 扩展。**

---

## 九、风险与规避

| 风险 | 规避 |
|------|------|
| qwen function calling 稳定性不足 | 加重试 + 结构化输出兜底 + 降级为无工具模式 |
| 多轮/多工具导致延迟高 | 限制 max_steps(3-5)；关键工具并行调用 |
| token 成本上升 | 手写循环精确计数；控制历史 messages 长度 |
| 视觉模型工具调用支持弱 | "vl看图 → max决策"两段式架构 |

---

## 十、总结

- **阶段一/二**：纯 Python 逻辑改造，零新增基础设施，复用 openai SDK + Supabase
- **阶段三**：仅在现有 Supabase 上开 pgvector
- **明确不用**：LangChain、LangGraph、独立向量数据库
- **核心价值**：可控、透明、易调试、成本清晰——契合 MVP 阶段与精简团队
