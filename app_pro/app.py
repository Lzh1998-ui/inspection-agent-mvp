# -*- coding: utf-8 -*-
"""
app_pro/app.py - 付费 Agent 专业版入口

与 app_free（根目录 app.py）共享 core/ 内核，独立部署、品牌、UI。

特色：
- 对话优先（st.chat_message 承载多轮）
- 智能模式（Agent 多轮推理 + 工具调用）| 快速模式（单轮，备用）
- 工具调用过程可视化（AI 查了什么，一目了然）
- 专业品牌感（与免费版拉开差距）

部署方式：
  在 Streamlit Cloud 新建一个 App，指定仓库 + 路径 app_pro/
  （Streamlit Cloud 支持子目录作为独立 App 部署）
"""

import json
import logging
import os
import re
import time
from datetime import datetime

# ===== Streamlit（必须在所有 import 之后第一行）=====
import streamlit as st

# ===== 页面配置（必须最前）=====
st.set_page_config(
    page_title="验货AI Agent Pro - 专业版",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ===== 共享内核 core（支持子目录部署）=====
import sys
from pathlib import Path
# 将父目录加入路径，使 core/ 可被导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.aql import judge_three_layer, compute_three_layer_acre, format_acre_hint
from core.pdf import generate_inspection_pdf, check_font_available, get_font_warning_message
from core.ai import build_ai_client

# ===== 独立模块 =====
from app_pro.agent_loop import AgentConfig, AgentContext, run_agent, analyze_images_vision
from app_pro.tools import TOOLS_SCHEMA, TOOL_REGISTRY

# ===== 日志（调试用）=====
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ============================================================================
# 页面样式
# ============================================================================

st.html(
    """
<style>
    /* 品牌色 */
    :root {
        --brand: #1B4FD8;
        --brand-light: #EEF2FF;
        --surface: #F8FAFC;
        --text: #1E293B;
        --muted: #64748B;
        --success: #16A34A;
        --warning: #D97706;
        --error: #DC2626;
    }
    /* 聊天消息气泡 */
    .stChatMessage { border-radius: 12px !important; }
    /* 工具调用卡片 */
    .tool-card {
        background: var(--brand-light);
        border-left: 3px solid var(--brand);
        border-radius: 8px;
        padding: 0.6rem 1rem;
        font-size: 0.85rem;
        margin: 0.3rem 0;
        color: var(--text);
    }
    /* Agent 思考区 */
    .agent-think {
        background: #FFFBEB;
        border: 1px solid #FDE68A;
        border-radius: 8px;
        padding: 0.6rem 1rem;
        font-size: 0.82rem;
        color: #92400E;
        margin: 0.3rem 0;
    }
    /* 侧边栏 */
    section[data-testid="stSidebar"] { background: #F1F5F9 !important; }
</style>
"""
)

# ============================================================================
# 认证（复用 auth_helper）
# ============================================================================

# 把 auth_helper 路径加入以便导入
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from auth_helper import show_auth_ui, show_user_info
except ImportError:
    # 独立部署时可能没有 auth_helper，降级为无登录
    def show_auth_ui():
        pass

    def show_user_info():
        pass


# ============================================================================
# 工具函数
# ============================================================================


def init_session_state():
    """初始化所有 session_state 变量。"""
    defaults = {
        "agent_messages": [],  # Agent 对话历史（list of dict: role/content）
        "tool_calls": [],  # 工具调用记录（list of dict）
        "agent_context": None,  # AgentContext 实例
        "agent_config": None,  # AgentConfig 实例
        "uploaded_files": [],
        "image_bytes_list": [],
        "product_name": "",
        "factory_name": "",
        "order_quantity": 0,
        "aql_critical": "AQL 0.65",
        "aql_major": "AQL 2.5",
        "aql_minor": "AQL 4.0",
        "inspection_standard": "",
        "agent_finished": False,
        "final_report": None,
        "mode": "intelligent",  # "intelligent" | "fast"
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def get_api_key() -> str | None:
    """从 secrets 读取 AI 密钥（支持 qwen / deepseek / openai）。"""
    try:
        return (
            st.secrets.get("qwen", {}).get("api_key")
            or st.secrets.get("deepseek", {}).get("api_key")
            or st.secrets.get("openai", {}).get("api_key")
        )
    except Exception:
        return None


def extract_defects_from_report(report: dict) -> list[dict]:
    """安全提取 defects 列表。"""
    defects = report.get("defects", [])
    if not isinstance(defects, list):
        return []
    return [
        {
            "type": d.get("type", "未知"),
            "quantity": int(d.get("quantity", 0)),
            "severity": d.get("severity", "次要"),
            "description": d.get("description", ""),
            "image": d.get("image", ""),
        }
        for d in defects
        if isinstance(d, dict)
    ]


# ============================================================================
# 侧边栏
# ============================================================================


def render_sidebar():
    """渲染侧边栏：产品参数 + 模式切换 + 使用说明。"""
    with st.sidebar:
        st.markdown("## 🔍 验货AI Agent Pro")
        st.markdown("**专业版 · 多轮推理 · 工具调用**")

        st.divider()

        # 模式切换
        mode = st.radio(
            "运行模式",
            ["🤖 智能模式", "⚡ 快速模式"],
            index=0 if st.session_state.mode == "intelligent" else 1,
            captions=[
                "Agent 多轮推理，工具调用，查历史/标准/档案",
                "单轮 AI 分析，无工具（备用）",
            ],
        )
        st.session_state.mode = "intelligent" if "智能" in mode else "fast"

        st.divider()

        # 产品参数
        st.markdown("### 📋 验货参数")
        st.session_state.product_name = st.text_input(
            "产品名称", value=st.session_state.product_name, placeholder="如：打火机、T恤"
        )
        st.session_state.factory_name = st.text_input(
            "工厂/供应商（选填）",
            value=st.session_state.factory_name,
            placeholder="如：深圳XX工贸",
        )
        st.session_state.order_quantity = st.number_input(
            "订单数量", min_value=1, value=max(st.session_state.order_quantity or 200, 1), step=10
        )
        st.session_state.inspection_standard = st.text_input(
            "验货标准（选填）",
            value=st.session_state.inspection_standard,
            placeholder="如：AQL 1.0，主要/次要缺陷",
        )

        st.markdown("**AQL 标准（可自定义）**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.session_state.aql_critical = st.selectbox(
                "致命", ["AQL 0.65", "AQL 1.0"], index=0
            )
        with c2:
            st.session_state.aql_major = st.selectbox("主要", ["AQL 1.5", "AQL 2.5"], index=1)
        with c3:
            st.session_state.aql_minor = st.selectbox("次要", ["AQL 4.0"], index=0)

        st.divider()

        # 使用说明
        with st.expander("ℹ️ 使用说明", expanded=False):
            st.markdown(
                """
            **智能模式工作流程：**
            1. 填写产品参数（可先填产品名，缺信息时 Agent 会追问）
            2. 上传产品图片
            3. Agent 会主动查历史记录、验货标准、产品档案
            4. 如信息不足，Agent 会追问（补图/补充参数）
            5. 确认后出最终报告，支持导出 PDF

            **可上传 JPG/PNG，单张 ≤ 5MB，建议至少3张不同角度。
            """
            )

        st.divider()
        show_user_info()


# ============================================================================
# 主聊天界面
# ============================================================================


def render_chat():
    """渲染 Agent 对话区。"""
    st.markdown("## 💬 智能验货对话")
    st.caption("Agent 会主动追问、查标准、参考历史，给出专业结论。")

    # 展示对话历史
    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 工具调用记录
    for tc in st.session_state.tool_calls:
        with st.chat_message("assistant"):
            st.markdown(
                f"<div class='tool-card'>🔧 调用工具：**{tc['name']}**"
                f"<br>📥 参数：<code>{tc['args']}</code>"
                f"<br>📤 结果：<code>{str(tc['result'])[:200]}</code>"
                f"</div>",
                unsafe_allow_html=True,
            )


def handle_user_input(user_input: str):
    """处理用户文本输入，追加到对话历史并触发 Agent 推理。"""
    st.session_state.agent_messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 初始化 Agent 配置
    api_key = get_api_key()
    if not api_key:
        _reply("⚠️ 未配置 AI API Key，请在 Streamlit Cloud Secrets 中配置 qwen/deepseek/openai 的 api_key。")
        return

    config = AgentConfig(
        qwen_key=api_key,
        timeout_seconds=60,
        max_steps=6,
    )

    # 初始化 / 更新 AgentContext
    ctx = st.session_state.agent_context or AgentContext()
    ctx.product_name = st.session_state.product_name
    ctx.factory_name = st.session_state.factory_name
    ctx.order_quantity = st.session_state.order_quantity
    ctx.inspection_standard = st.session_state.inspection_standard
    ctx.aql_critical = st.session_state.aql_critical
    ctx.aql_major = st.session_state.aql_major
    ctx.aql_minor = st.session_state.aql_minor
    st.session_state.agent_context = ctx

    # 构建 messages（含历史）
    messages = list(st.session_state.agent_messages)

    # 注入图片（如果用户发了图片）
    if st.session_state.image_bytes_list:
        _inject_images_to_messages(messages, ctx)

    # 追加用户最新输入
    messages.append({"role": "user", "content": user_input})

    # 运行 Agent
    with st.chat_message("assistant"):
        # === 先进行视觉分析（可见状态）===
        vision_done = False
        if st.session_state.image_bytes_list:
            ctx.image_bytes_list = st.session_state.image_bytes_list
            with st.status("🔍 正在分析图片（qwen-vl-plus）...", expanded=True) as vstatus:
                from app_pro.agent_loop import analyze_images_vision
                vok, vresult, vdefects, vlabels = analyze_images_vision(config, ctx)
                if vok:
                    vstatus.update(
                        label=f"✅ 图片分析完成：{vresult}（发现 {len(vdefects)} 项缺陷）",
                        state="complete",
                    )
                    vision_done = True
                    # 把视觉分析结果插入 messages
                    vision_summary = (
                        f"[视觉分析已完成]\n"
                        f"初步结论：{vresult}\n"
                        f"缺陷数量：{len(vdefects)} 项\n"
                    )
                    for i, d in enumerate(vdefects[:10], 1):
                        vision_summary += (
                            f"  {i}. {d.get('type', '未知')} × {d.get('quantity', 0)}件"
                            f"（{d.get('severity', '次要')}）{d.get('description', '')}\n"
                        )
                    vision_summary += "\n以上是 qwen-vl-plus 识别结果，请不要再问'请分享图片'。\n"
                    messages.append({"role": "user", "content": vision_summary})

                    # 在 UI 上直接展示缺陷清单
                    if vdefects:
                        st.markdown("**🔍 视觉识别到的缺陷：**")
                        for d in vdefects[:10]:
                            sev_icon = {"致命": "🔴", "主要": "🟡", "次要": "🟢"}.get(d.get("severity", "次要"), "⚪")
                            st.markdown(
                                f"- {sev_icon} **{d.get('type', '未知')}** × {d.get('quantity', 0)}件"
                                f" — {d.get('description', '')}"
                            )
                else:
                    vstatus.update(label=f"❌ 图片分析失败：{vresult}", state="error")
                    st.error(f"视觉分析错误：{vresult}")

        with st.spinner("Agent 推理中..."):
            status, result = run_agent(
                messages=messages,
                config=config,
                context=ctx,
                tools_schema=TOOLS_SCHEMA,
                tool_registry=TOOL_REGISTRY,
            )

        if status == "ask":
            st.session_state.agent_messages.append({"role": "assistant", "content": result})
            st.rerun()
        elif status == "report":
            st.session_state.final_report = result
            st.session_state.agent_finished = True
            _render_final_report(result)
        else:  # error
            st.session_state.agent_messages.append({"role": "assistant", "content": f"❌ {result}"})
            st.rerun()


def _inject_images_to_messages(messages: list[dict], ctx: AgentContext):
    """把已上传图片注入到最近一条 user 消息的 content 中。"""
    import base64

    if not ctx.image_bytes_list or not messages:
        return

    last_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break

    if last_user_idx is None:
        return

    msg = messages[last_user_idx]
    content = msg.get("content", "")
    if isinstance(content, str):
        new_content = [{"type": "text", "text": content}]
    elif isinstance(content, list):
        new_content = list(content)
    else:
        new_content = [{"type": "text", "text": str(content)}]

    for img_bytes in ctx.image_bytes_list[:6]:
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        new_content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        )

    messages[last_user_idx]["content"] = new_content


def _reply(text: str):
    """快捷回复（不触发 rerun）。"""
    st.session_state.agent_messages.append({"role": "assistant", "content": text})
    with st.chat_message("assistant"):
        st.markdown(text)


# ============================================================================
# 最终报告渲染
# ============================================================================


def _render_final_report(report: dict):
    """渲染 Agent 最终报告（chat 内 + 侧边操作）。"""
    conclusion = report.get("conclusion", "未知")
    emoji = {"合格": "✅", "不合格": "❌", "有条件接受": "⚠️"}.get(conclusion, "📋")

    st.session_state.agent_messages.append(
        {"role": "assistant", "content": f"{emoji} **{conclusion}**\n\n报告已生成，可导出 PDF。"}
    )

    # 报告摘要卡片
    three = report.get("three_layer_result", {})
    c1, c2, c3 = st.columns(3)
    for col, key, label in zip(
        [c1, c2, c3], ["critical", "major", "minor"], ["致命缺陷", "主要缺陷", "次要缺陷"]
    ):
        layer = three.get(key, {})
        passed = layer.get("passed", None)
        color = "#16A34A" if passed else "#DC2626" if passed is False else "#64748B"
        icon = "✅" if passed else "❌" if passed is False else "➖"
        with col:
            st.markdown(
                f"**{label}**：{icon} {'通过' if passed else '不通过' if passed is False else '—'}"
            )
            st.caption(f"Ac={layer.get('ac', '?')} · 缺陷 {layer.get('defect_count', 0)}")

    defects = extract_defects_from_report(report)
    if defects:
        with st.expander(f"📋 缺陷清单（共 {len(defects)} 项）", expanded=False):
            for i, d in enumerate(defects, 1):
                sev_color = {"致命": "🔴", "主要": "🟡", "次要": "🟢"}.get(d["severity"], "⚪")
                st.markdown(
                    f"{sev_color} #{i} **{d['type']}** × {d['quantity']}件 "
                    f"（{d['severity']}）{d['image']}"
                )
                if d["description"]:
                    st.caption(f"   {d['description']}")

    # 建议
    rec = report.get("recommendation", "")
    if rec:
        st.success(f"💡 **{rec}**")

    st.divider()

    # PDF 导出
    if st.button("📄 导出报告 PDF", type="primary", use_container_width=True):
        _export_pdf(report)


def _export_pdf(report: dict):
    """生成并下载 PDF。"""
    font_ok = check_font_available()
    if not font_ok:
        st.warning(get_font_warning_message())

    try:
        # 补全 report_data 字段
        report_data = {
            "report_id": f"RPT-PRO-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "product_name": st.session_state.product_name,
            "factory_name": st.session_state.factory_name or "未提供",
            "order_quantity": st.session_state.order_quantity,
            "inspection_standard": st.session_state.inspection_standard or (
                f"致命:{st.session_state.aql_critical} "
                f"主要:{st.session_state.aql_major} "
                f"次要:{st.session_state.aql_minor}"
            ),
            "aql_critical": st.session_state.aql_critical,
            "aql_major": st.session_state.aql_major,
            "aql_minor": st.session_state.aql_minor,
            "conclusion": report.get("conclusion", ""),
            "three_layer_result": report.get("three_layer_result", {}),
            "defects": extract_defects_from_report(report),
            "recommendation": report.get("recommendation", ""),
            "confidence": report.get("confidence", 0.8),
        }

        pdf_bytes = generate_inspection_pdf(report_data, st.session_state.uploaded_files)
        st.success("PDF 生成成功！")
        st.download_button(
            "⬇️ 下载 PDF",
            data=pdf_bytes,
            file_name=f"{report_data['report_id']}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"PDF 生成失败: {e}")


# ============================================================================
# 快速模式（备用单轮）
# ============================================================================


def run_fast_mode():
    """快速模式：单轮 AI 分析，与 app_free 逻辑一致。"""
    from core.ai import build_ai_client

    api_key = get_api_key()
    if not api_key:
        st.error("未配置 AI API Key")
        return

    if not st.session_state.product_name:
        st.warning("请先填写产品名称")
        return

    if not st.session_state.image_bytes_list:
        st.warning("请先上传产品图片")
        return

    client, model_name = build_ai_client(qwen_key=api_key, timeout_seconds=60)
    if not client:
        st.error(model_name)
        return

    acre = compute_three_layer_acre(
        st.session_state.order_quantity,
        st.session_state.aql_critical,
        st.session_state.aql_major,
        st.session_state.aql_minor,
    )

    st.info(f"使用模型：{model_name}，分析中（最多60秒）...")

    # 构建消息（含图片）
    import base64

    user_content = [
        {
            "type": "text",
            "text": (
                f"请分析这款产品：{st.session_state.product_name}\n"
                f"验货标准：{st.session_state.inspection_standard or 'AQL 2.5 主要/次要'}\n"
                + format_acre_hint(acre)
                + "\n请识别图片中的缺陷，输出JSON格式结果。"
            ),
        }
    ]
    for img_bytes in st.session_state.image_bytes_list[:6]:
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})

    messages = [
        {
            "role": "system",
            "content": "你是一位专业验货专家，请分析产品图片并按JSON格式输出结论。",
        },
        {"role": "user", "content": user_content},
    ]

    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=1000,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content or ""

        # 解析 JSON
        result = json.loads(raw)
        # 基于真实 AQL 覆盖
        three, conclusion = judge_three_layer(result.get("defects", []), acre)
        result["three_layer_result"] = three
        result["conclusion"] = conclusion

        st.session_state.final_report = result
        st.session_state.agent_finished = True
        _render_final_report(result)

    except json.JSONDecodeError:
        st.error(f"AI 返回格式错误：{raw[:200]}")
    except Exception as e:
        st.error(f"分析失败：{e}")


# ============================================================================
# 图片上传区
# ============================================================================


def render_upload():
    """渲染图片上传区，提取字节存入 session_state。"""
    st.markdown("### 📷 上传产品图片")
    st.caption("支持 JPG/PNG，单张 ≤ 5MB，建议上传 3 张以上不同角度")

    uploaded = st.file_uploader(
        "选择图片",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        help="多张图片请一次性选择",
    )

    if uploaded:
        st.session_state.uploaded_files = uploaded
        st.session_state.image_bytes_list = [f.getvalue() for f in uploaded]

        # 预览缩略图
        cols = st.columns(min(len(uploaded), 6))
        for i, (f, col) in enumerate(zip(uploaded, cols)):
            with col:
                st.image(f, caption=f"图{i+1}: {f.name}", use_container_width=True)

        st.success(f"已上传 {len(uploaded)} 张图片，可开始分析")

        if st.session_state.agent_finished:
            st.session_state.agent_finished = False
            st.session_state.final_report = None


# ============================================================================
# 主函数
# ============================================================================


def main():
    # 认证
    try:
        show_auth_ui()
    except Exception:
        pass

    init_session_state()
    render_sidebar()

    # 顶部品牌栏
    st.markdown(
        """
    <div style="background: #1B4FD8; color: white; padding: 1rem 1.5rem; border-radius: 8px; margin-bottom: 1rem;">
        <b>🔍 验货AI Agent Pro</b> &nbsp;|&nbsp; 专业版 · 多轮追问 · 工具调用 · 记忆档案
    </div>
    """,
        unsafe_allow_html=True,
    )

    # 图片上传
    render_upload()

    st.divider()

    # 根据模式渲染不同 UI
    if st.session_state.mode == "intelligent":
        # ===== 智能模式 =====
        render_chat()

        # 开始分析按钮
        col_start, col_reset = st.columns([4, 1])
        with col_start:
            user_input = st.chat_input("输入消息，或描述问题/补充信息...")
        with col_reset:
            if st.button("🔄 重置", use_container_width=True):
                for k in ["agent_messages", "tool_calls", "agent_context", "agent_finished", "final_report"]:
                    st.session_state[k] = [] if k in ("agent_messages", "tool_calls") else None if k in ("agent_context", "final_report") else False
                st.rerun()

        if user_input:
            handle_user_input(user_input)
        elif (
            st.session_state.image_bytes_list
            and not st.session_state.agent_finished
            and not st.session_state.agent_messages
        ):
            # 自动触发：只上传了图片但没输入文本 → Agent 自动开始分析
            handle_user_input("请分析我刚上传的图片，给出验货结论。")

        # 如果没有对话历史，给出引导
        if not st.session_state.agent_messages:
            st.info(
                "👋 填写左侧参数并上传图片后，在下方输入任意消息开始验货。"
                "Agent 会根据产品信息主动查档案、历史和标准。"
            )

    else:
        # ===== 快速模式 =====
        st.markdown("### ⚡ 快速模式")
        st.caption("单轮 AI 分析，无需等待 Agent 追问，适合信息齐全时快速出报告")

        if st.button("🚀 开始分析", type="primary", use_container_width=True):
            run_fast_mode()


if __name__ == "__main__":
    main()
