# -*- coding: utf-8 -*-
"""
app_pro/agent_loop.py - 手写 Agent 主循环

基于 openai SDK 原生 function calling + 手写 loop。
不引入 LangChain/LangGraph 等重框架（详见 AGENT_TECH_STACK.md）。

核心逻辑：
1. 接收对话历史 messages（包含 system prompt + 工具调用结果）
2. 注入产品上下文（档案、历史、标准）作为先验知识
3. 模型请求工具 -> 执行 -> 回填 tool result -> 再推理
4. 收敛出最终报告或触达 max_steps 强制出结论

模型分工（可配置）：
- 视觉分析：qwen-vl-plus（调用方负责传图片 base64）
- 工具调用/推理：qwen-max（默认）或 qwen-plus（降本）
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Literal

import openai
import httpx

from core.aql import judge_three_layer, compute_three_layer_acre

logger = logging.getLogger(__name__)


# ============================================================================
# 默认 System Prompt（必须在 AgentConfig 之前定义）
# ============================================================================

_DEFAULT_SYSTEM_PROMPT = (
    "你是一位拥有15年经验的外贸验货专家，精通ISO 2859-1/2抽样标准、"
    "AQL质量标准（AQL 0.65/1.0/1.5/2.5/4.0/6.5），熟悉电子产品、纺织品、"
    "机械配件、玩具等各类产品的国际质量标准（ISO、ASTM、GB、EN等）。\n\n"
    "你的任务是：收到产品图片和基本信息后，像真正的验货员一样工作——"
    "**先问清楚关键信息，再看图分析，最后给出专业结论**。\n\n"
    "【工作流程】\n"
    "1. 如果缺少订单数量、验货标准、工厂名称等关键信息，先主动追问用户，不要凭猜测出报告。\n"
    "2. 如果图片模糊或角度不够，主动要求补拍特定角度。\n"
    "3. 在出最终报告前，可以调用工具查询标准、历史记录、产品档案来辅助判断。\n"
    "4. 综合所有信息，按输出格式给出结论。\n\n"
    "【AQL 三层抽样标准】\n"
    "- 致命缺陷（AQL 0.65）：安全风险、违法、危及生命 -- 任何数量均不合格（Ac=0）\n"
    "- 主要缺陷（AQL 2.5）：功能失效、影响使用、关键尺寸偏差 -- 参照抽样表 Ac/Re\n"
    "- 次要缺陷（AQL 4.0）：外观瑕疵、不影响功能、包装问题 -- 参照抽样表 Ac/Re\n\n"
    "【输出格式】（最终结论时使用 JSON）\n"
    '{\n'
    '  "conclusion": "合格/不合格/有条件接受",\n'
    '  "three_layer_result": {\n'
    '    "critical": {"passed": true/false, "aql": "AQL X.X", "defect_count": 数字},\n'
    '    "major": {"passed": true/false, "aql": "AQL X.X", "defect_count": 数字},\n'
    '    "minor": {"passed": true/false, "aql": "AQL X.X", "defect_count": 数字}\n'
    "  },\n"
    '  "defects": [\n'
    '    {\n'
    '      "type": "划痕/变形/色差/功能异常/包装破损等",\n'
    '      "quantity": 数字,\n'
    '      "severity": "致命/主要/次要",\n'
    '      "description": "详细描述（50字以内）",\n'
    '      "image": "图1/图2/图3"\n'
    "    }\n"
    "  ],\n"
    '  "recommendation": "处理建议（100字以内）",\n'
    '  "confidence": 0.0-1.0\n'
    "}\n\n"
    "【注意】\n"
    "- quantity 必须是整数，禁止'若干'、'多个'\n"
    "- 如果信息严重不足，先追问，不要瞎判\n"
    "- 工具调用结果仅供参考，最终以你的专业判断为准\n"
    "- 保持对话友好、专业，有礼有据\n\n"
    "【图片处理规则】\n"
    "- 如果用户上传了图片，系统会自动先用 qwen-vl-plus 做视觉分析，把缺陷结果插入到对话中（以 [图片分析结果] 开头）。\n"
    "- 一旦看到 [图片分析结果] 消息，**严禁**再问'请分享图片'或'我没看到图片'——图片已被系统读取。\n"
    "- 直接基于该结果继续追问或出报告即可。"
)


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class AgentConfig:
    """Agent 运行配置。"""

    qwen_key: str | None = None
    deepseek_key: str | None = None
    openai_key: str | None = None
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout_seconds: int = 60
    vision_model: str = "qwen-vl-plus"
    reasoning_model: str = "qwen-max"
    max_steps: int = 6
    max_vision_steps: int = 3
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT


@dataclass
class AgentContext:
    """一次验货的完整上下文（记忆沉淀用）。"""

    product_name: str = ""
    factory_name: str = ""
    inspection_standard: str = ""
    order_quantity: int = 0
    aql_critical: str = "AQL 0.65"
    aql_major: str = "AQL 2.5"
    aql_minor: str = "AQL 4.0"
    acre: dict | None = None
    product_profile: dict | None = None
    defect_history: list = field(default_factory=list)
    standard_info: dict | None = None
    image_bytes_list: list = field(default_factory=list)

    def build_prior_context(self) -> str:
        parts = []
        if self.product_profile and not self.product_profile.get("error"):
            p = self.product_profile
            parts.append(
                "[产品档案]"
                + f"{p.get('product_name', '')}（{p.get('factory_name', '')}）"
                + f"历史验货 {p.get('inspection_count', 0)} 次，"
                + f"通过率 {p.get('pass_rate', 0)}%，趋势：{p.get('quality_trend', '未知')}"
                + (
                    "。典型缺陷：" + ", ".join(p.get("typical_defects", [])[:3])
                    if p.get("typical_defects")
                    else ""
                )
            )
        if self.defect_history and not self.defect_history[0].get("error"):
            parts.append(
                "[历史缺陷]"
                + "；".join(
                    f"第{i+1}次：{r.get('conclusion', '?')}，缺陷 {len(r.get('defects', []))} 项"
                    for i, r in enumerate(self.defect_history[:3])
                )
            )
        if self.standard_info and not self.standard_info.get("error"):
            s = self.standard_info
            checks = "；".join(s.get("key_checks", [])[:3])
            parts.append(
                f"[适用标准] {s.get('standard', '')}，参考：{s.get('reference', '')}，关键检查：{checks}"
            )
        if not parts:
            return ""
        return "[先验知识]\n" + "\n".join(parts) + "\n\n"


# ============================================================================
# Agent 主循环
# ============================================================================


def run_agent(
    messages: list[dict],
    config: AgentConfig,
    context: AgentContext,
    tools_schema: list[dict],
    tool_registry: dict[str, callable],
) -> tuple[Literal["report"], dict] | tuple[Literal["ask"], str] | tuple[Literal["error"], str]:
    """
    Agent 主循环。

    返回:
        ("report", result_dict)  -- 最终报告
        ("ask", question_str)    -- AI 需要追问
        ("error", error_str)     -- 运行异常
    """
    # ===== 新增：图片预分析（关键修复）=====
    # 原因：Agent 主循环使用的是 qwen-max 文本模型，无法直接看图。
    # 需要先用 qwen-vl-plus 做视觉分析，把缺陷数据注入上下文。
    if context.image_bytes_list:
        print(f"[VISION] 检测到 {len(context.image_bytes_list)} 张图片，启动视觉分析...")
        try:
            ok, conclusion_or_error, defects, image_labels = analyze_images_vision(
                config, context
            )
            print(f"[VISION] ok={ok}, conclusion={conclusion_or_error[:50]}, defects={len(defects)}")
        except Exception as e:
            print(f"[VISION] 视觉分析异常: {e}")
            ok, conclusion_or_error, defects, image_labels = False, f"视觉分析异常: {e}", [], []

        if ok:
            # 把视觉分析结果注入消息和上下文
            vision_msg = (
                "[图片分析结果]\n"
                f"- 初步结论：{conclusion_or_error}\n"
                f"- 发现缺陷：{len(defects)} 项\n"
            )
            for i, d in enumerate(defects[:10], 1):
                vision_msg += (
                    f"  {i}. {d.get('image', image_labels[min(i-1, len(image_labels)-1)] if image_labels else '图')}"
                    f" {d.get('type', '未知')} × {d.get('quantity', 0)}件"
                    f"（{d.get('severity', '次要')}）{d.get('description', '')}\n"
                )
            # 追加一条 user 消息告知 Agent 视觉分析已完成
            messages.append({
                "role": "user",
                "content": vision_msg + "\n请基于以上图片分析结果，调用工具查询必要的标准/历史/档案后，给出最终结论。"
            })
        else:
            # 视觉分析失败也要继续（保留旧逻辑）
            messages.append({
                "role": "user",
                "content": f"[图片分析失败] {conclusion_or_error}\n请基于已知信息推理。"
            })
            print(f"[VISION] 视觉分析失败: {conclusion_or_error}")

    # 构建 system prompt（含先验知识）
    system_content = context.build_prior_context() + config.system_prompt
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = system_content
    else:
        messages.insert(0, {"role": "system", "content": system_content})

    # 初始化客户端
    try:
        client = _build_client(config)
    except Exception as e:
        return "error", f"AI 客户端初始化失败: {e}"

    # 主循环
    for step in range(config.max_steps):
        try:
            response = client.chat.completions.create(
                model=config.reasoning_model,
                messages=messages,
                tools=tools_schema,
                tool_choice="auto",
                max_tokens=1500,
                temperature=0.3,
            )
        except openai.APITimeoutError:
            return "error", f"API 调用超时（{config.timeout_seconds}秒）"
        except openai.APIConnectionError:
            return "error", "网络连接失败，请检查网络后重试"
        except openai.RateLimitError:
            return "error", "API 频率超限，请稍后重试"
        except openai.AuthenticationError:
            return "error", "API Key 认证失败，请检查密钥配置"
        except Exception as e:
            return "error", f"AI 请求失败: {str(e)}"

        assistant_msg = response.choices[0].message
        messages.append(assistant_msg.model_dump(exclude_none=True))

        # 无工具调用 → 检查是否出结论
        if not assistant_msg.tool_calls:
            content = (assistant_msg.content or "").strip()
            if not content:
                continue
            try:
                result = _extract_final_report(content)
                return "report", result
            except Exception:
                return "ask", content

        # 执行工具调用
        for call in assistant_msg.tool_calls:
            fn_name = call.function.name
            fn = tool_registry.get(fn_name)

            if fn is None:
                tool_result = {"error": f"未知工具: {fn_name}"}
            else:
                try:
                    args = json.loads(call.function.arguments or "{}")
                    # 自动注入 context 已知信息
                    if fn_name == "query_aql_plan":
                        args.setdefault("order_quantity", context.order_quantity or args.get("order_quantity"))
                    elif fn_name == "search_defect_history":
                        args.setdefault("product_name", context.product_name)
                        args.setdefault("factory_name", context.factory_name)
                    elif fn_name == "get_product_profile":
                        args.setdefault("product_name", context.product_name)
                        args.setdefault("factory_name", context.factory_name)

                    raw_result = fn(**args)
                    tool_result = raw_result if isinstance(raw_result, dict) else {"result": raw_result}
                    _deposit_to_context(fn_name, tool_result, context)
                except Exception as e:
                    tool_result = {"error": f"工具执行失败: {str(e)}"}

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False, indent=2),
                }
            )

    return "error", f"Agent 在 {config.max_steps} 步内未收敛，请缩短任务范围或重试"


def _build_client(config: AgentConfig) -> openai.OpenAI:
    key = config.qwen_key or config.deepseek_key or config.openai_key
    if not key:
        raise ValueError("未提供任何 API Key")
    kwargs = {"api_key": key, "timeout": httpx.Timeout(config.timeout_seconds, connect=10.0)}
    if config.qwen_key:
        kwargs["base_url"] = config.base_url
    return openai.OpenAI(**kwargs)


def _deposit_to_context(fn_name: str, result: dict, context: AgentContext) -> None:
    if result.get("error"):
        return
    if fn_name == "get_product_profile":
        context.product_profile = result
    elif fn_name == "search_defect_history":
        context.defect_history = result.get("records", [])
    elif fn_name == "lookup_standard":
        context.standard_info = result
    elif fn_name == "query_aql_plan":
        if context.order_quantity and context.aql_critical:
            try:
                context.acre = compute_three_layer_acre(
                    context.order_quantity,
                    context.aql_critical,
                    context.aql_major,
                    context.aql_minor,
                )
            except Exception:
                pass


def _extract_final_report(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    import re
    for pat in [r"```json\s*\n?(.*?)\n?\s*```", r"```\s*\n?(.*?)\n?\s*```"]:
        m = re.search(pat, content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass
    m = re.search(r"\{[\s\S]*\}", content)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    raise ValueError("无法从 AI 响应中提取结构化报告")


# ============================================================================
# 视觉分析（独立函数，供 app 调用）
# ============================================================================


def analyze_images_vision(
    config: AgentConfig,
    context: AgentContext,
    prior_conclusion: str | None = None,
) -> tuple[bool, str, list[dict], list[str]]:
    """
    调用 qwen-vl-plus 分析已上传图片。

    返回: (success, conclusion_or_error, defects_list, image_labels)
    """
    if not context.image_bytes_list:
        return False, "请先上传产品图片", [], []

    try:
        client = _build_client(config)
    except Exception as e:
        return False, f"AI 客户端初始化失败: {e}", [], []

    aql_hint = ""
    if context.acre:
        try:
            from core.aql import format_acre_hint
            aql_hint = format_acre_hint(context.acre)
        except Exception:
            pass

    text_parts = [
        "你是一位专业的验货质检员，请仔细查看图片识别缺陷。",
        f"产品名称：{context.product_name or '未指定'}",
    ]
    if prior_conclusion:
        text_parts.append(f"\n【上轮分析】：{prior_conclusion}")
    if context.inspection_standard:
        text_parts.append(f"验货标准：{context.inspection_standard}")
    if aql_hint:
        text_parts.append(f"\n{aql_hint}")

    text_parts.append(
        "\n请识别图片中可见的产品问题（划痕、损伤、变形、色差、功能异常、包装破损等），"
        "并严格按以下 JSON 格式输出，不要多余说明：\n"
        '{\n'
        '  "conclusion": "合格/不合格/有条件接受",\n'
        '  "defects": [\n'
        '    {"type": "缺陷类型", "quantity": 数字, "severity": "致命/主要/次要", "description": "描述", "image": "图1"}\n'
        '  ]\n'
        '}'
    )

    user_content = [
        {"type": "text", "text": "\n".join(text_parts)},
    ]
    for img_bytes in context.image_bytes_list[:6]:
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        img_url = f"data:image/jpeg;base64,{img_b64}"
        user_content.append({"type": "image_url", "image_url": {"url": img_url}})

    try:
        response = client.chat.completions.create(
            model=config.vision_model,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=1000,
            temperature=0.3,
        )
    except Exception as e:
        return False, f"视觉分析失败: {str(e)}", [], []

    raw = response.choices[0].message.content or ""
    defects = []
    try:
        result = json.loads(raw)
        defects = result.get("defects", [])
        conclusion = result.get("conclusion", "")
    except json.JSONDecodeError:
        conclusion = raw

    image_labels = [f"图{i+1}" for i in range(len(context.image_bytes_list[:6]))]
    return True, conclusion, defects, image_labels
