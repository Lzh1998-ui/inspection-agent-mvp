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
        "analysis_triggered": False,  # 防重复自动触发锁
        "trigger_signature": None,    # 上一次触发时的图片签名（去重 key）
        "mode": "turbo",  # "turbo" | "fast" | "intelligent"
        "pdf_bytes": None,            # 已生成的 PDF 字节（持久化按钮用）
        "pdf_filename": None,         # 下载时的默认文件名
        "_report_saved": False,     # 本次会话报告是否已入库（防重复写入）
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
        st.markdown("**⚙️ 运行模式**")
        mode = st.segmented_control(
            "",
            options=["🚀 极速", "⚡ 快速", "🤖 智能"],
            default={
                "turbo": "🚀 极速",
                "fast": "⚡ 快速",
                "intelligent": "🤖 智能",
            }.get(st.session_state.mode, "🚀 极速"),
            help=None,
        )
        if mode is None:
            mode = "🚀 极速"
        # 模式映射
        if "极速" in mode:
            st.session_state.mode = "turbo"
        elif "快速" in mode:
            st.session_state.mode = "fast"
        else:
            st.session_state.mode = "intelligent"

        # 模式说明
        if st.session_state.mode == "turbo":
            st.caption("🚀 单次视觉 + AQL 判定，5-10 秒，最快")
        elif st.session_state.mode == "fast":
            st.caption("⚡ 3次投票 + AQL 判定，15-45 秒，平衡速度与准确性")
        else:
            st.caption("🤖 Agent 多轮推理 + 工具调用，1-2 分钟，适合复杂场景")

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
            **🚀 极速模式（推荐首选，最快）**
            - 单次视觉分析 + AQL 判定，5-10 秒
            - 无 LLM 推理，直接出结论
            - 适合：标准产品、快速筛查、简单验货

            **⚡ 快速模式（平衡之选）**
            - 3次视觉投票 + AQL 判定，15-45 秒
            - 减少单次分析偶然误差
            - 适合：常规验货、缺陷明显产品

            **🤖 智能模式（适合复杂场景）**
            - Agent 多轮推理 + 工具调用，1-2 分钟
            - 自动查历史、标准、档案，可追问
            - 适合：新品首检、复杂问题、深度分析

            **通用操作：**
            1. 填写验货参数（产品名、订单数量、AQL 标准）
            2. 上传产品图片（JPG/PNG，单张 ≤ 5MB）
            3. 选择模式，点击按钮启动分析
            4. 支持导出 PDF 验货报告

            **提示：** 先试 🚀 极速模式，效果不好再试 ⚡ 快速或 🤖 智能模式。
            """
            )

        st.divider()
        _render_history_panel()
        show_user_info()


# ============================================================================
# 历史报告（侧边栏）
# ============================================================================


def _render_history_panel():
    """侧边栏历史报告面板：查询 Supabase 并允许回看。"""
    with st.expander("📁 历史报告", expanded=False):
        if st.button("🔄 刷新历史", use_container_width=True, key="hist_refresh"):
            st.session_state._hist_rows = None
        try:
            from app_pro.tools import _get_supabase
            client = _get_supabase()
        except Exception as e_init:
            client = None
            init_err = str(e_init)
        if client is None:
            st.warning(f"Supabase 未配置，无法加载历史。错误：{init_err if 'init_err' in dir() else '客户端初始化失败'}")
            return

        if st.session_state.get("_hist_rows") is None:
            try:
                resp = (
                    client.table("inspection_reports")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(50)
                    .execute()
                )
                st.session_state._hist_rows = resp.data or []
            except Exception as e:
                st.error(f"加载历史失败：{e}")
                st.session_state._hist_rows = []

        rows = st.session_state.get("_hist_rows", [])
        if not rows:
            st.info("暂无历史报告。验货一次后会自动保存。")
            return

        options = []
        for r in rows:
            prod = (r.get("product_name") or "?") or "?"
            date = str(r.get("created_at", ""))[:10]
            concl = (r.get("conclusion") or "").replace(" ", "")
            icon = {"合格": "✅", "不合格": "❌", "有条件接受": "⚠️"}.get(concl, "📋")
            options.append(f"{icon} {prod} · {date}")

        sel = st.selectbox("选择报告查看", options, key="hist_sel", index=0)
        if sel:
            idx = options.index(sel)
            _render_historical_report(rows[idx])


def _render_historical_report(row: dict):
    """只读渲染一条历史报告（不重复入库、不依赖当前图片）。"""
    report = {
        "conclusion": row.get("conclusion", ""),
        "three_layer_result": row.get("three_layer_result") or {},
        "defects": row.get("defects") or [],
        "recommendation": row.get("recommendation", ""),
        "confidence": row.get("confidence", 0.0),
    }
    conclusion = report["conclusion"]
    emoji = {"合格": "✅", "不合格": "❌", "有条件接受": "⚠️"}.get(conclusion, "📋")
    st.markdown(f"### {emoji} {conclusion}")
    st.caption(
        f"产品：{row.get('product_name', '')} ｜ 工厂：{row.get('factory_name') or '未提供'}"
        f" ｜ 日期：{str(row.get('created_at', ''))[:10]}"
    )

    three = report["three_layer_result"]
    c1, c2, c3 = st.columns(3)
    for col, key, label in zip(
        [c1, c2, c3], ["critical", "major", "minor"], ["致命缺陷", "主要缺陷", "次要缺陷"]
    ):
        layer = three.get(key, {})
        passed = layer.get("passed", None)
        icon = "✅" if passed else "❌" if passed is False else "➖"
        with col:
            st.markdown(f"**{label}**：{icon} {'通过' if passed else '不通过' if passed is False else '—'}")
            st.caption(f"缺陷 {layer.get('defect_count', 0)}")

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

    rec = report.get("recommendation", "")
    if rec:
        st.success(f"💡 **{rec}**")

    # 导出 PDF（历史数据，无图片）
    if st.button("⬇️ 导出此报告 PDF", key="hist_pdf"):
        try:
            report_data = {
                "report_id": f"RPT-HIST-{str(row.get('id', ''))[:8]}",
                "product_name": row.get("product_name", ""),
                "factory_name": row.get("factory_name") or "未提供",
                "order_quantity": row.get("order_quantity") or 0,
                "inspection_standard": (
                    f"致命:{row.get('aql_critical', 'AQL 0.65')} "
                    f"主要:{row.get('aql_major', 'AQL 2.5')} "
                    f"次要:{row.get('aql_minor', 'AQL 4.0')}"
                ),
                "aql_critical": row.get("aql_critical", "AQL 0.65"),
                "aql_major": row.get("aql_major", "AQL 2.5"),
                "aql_minor": row.get("aql_minor", "AQL 4.0"),
                "conclusion": report["conclusion"],
                "three_layer_result": report["three_layer_result"],
                "defects": report["defects"],
                "recommendation": report["recommendation"],
                "confidence": report.get("confidence", 0.8),
                "sample_size": row.get("sample_size") or "N/A",
                "inspection_date": str(row.get("created_at", ""))[:10],
            }
            pdf_bytes = generate_inspection_pdf(report_data, [])
            st.download_button(
                "📥 下载 PDF",
                data=pdf_bytes,
                file_name=f"{report_data['report_id']}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"PDF 生成失败：{e}")


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
            content = msg.get("content", "")
            # content 可能是 list（含 image_url/base64），此时只渲染文本，避免把整段
            # base64 图片数据当字符串刷到界面上。
            if isinstance(content, list):
                text_parts = [
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                st.markdown("\n".join(text_parts) or "(图片)")
            else:
                st.markdown(content)

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
    # 标记已触发（防自动触发重复调用）
    st.session_state.analysis_triggered = True
    st.session_state._report_saved = False  # 新一轮：允许重新入库
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
        timeout_seconds=120,  # 视觉分析可能较慢，延长至 120 秒
        max_steps=4,  # 4 轮足够收敛
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
    # 预计算 acre（极速模式需要）
    if ctx.order_quantity and not ctx.acre:
        try:
            from core.aql import compute_three_layer_acre
            ctx.acre = compute_three_layer_acre(
                ctx.order_quantity, ctx.aql_critical, ctx.aql_major, ctx.aql_minor
            )
        except Exception:
            pass
    st.session_state.agent_context = ctx

    # 构建 messages（含历史）
    # 必须用深拷贝：_inject_images_to_messages 会把 base64 图片写入 content，
    # 若只做浅拷贝，会污染 st.session_state.agent_messages 里的原始消息对象，
    # 导致 rerun 后 render_chat 把整段 base64 当文本渲染出来。
    import copy
    messages = copy.deepcopy(st.session_state.agent_messages)

    # 注入图片（如果用户发了图片）
    if st.session_state.image_bytes_list:
        _inject_images_to_messages(messages, ctx)

    # 追加用户最新输入
    messages.append({"role": "user", "content": user_input})

    # 根据模式选择运行方式
    mode = st.session_state.mode  # "turbo" | "fast" | "intelligent"

    with st.chat_message("assistant"):
        if mode == "turbo":
            # ===== 极速模式（Turbo）：单次视觉分析 + AQL 判定，5-10 秒 =====
            if not st.session_state.image_bytes_list:
                st.warning("🚀 极速模式需要上传产品图片，请先上传图片")
                return
            ctx.image_bytes_list = st.session_state.image_bytes_list
            with st.status("🚀 极速分析中（单次视觉分析，约5-10秒）...", expanded=True) as vstatus:
                status, result, defects, img_labels = run_agent(
                    messages=messages,
                    config=config,
                    context=ctx,
                    tools_schema=TOOLS_SCHEMA,
                    tool_registry=TOOL_REGISTRY,
                    mode="turbo",
                )
                if status == "report":
                    vstatus.update(
                        label=f"✅ 分析完成！发现 {len(defects)} 项缺陷（5-10秒极速）",
                        state="complete",
                    )
                    if defects:
                        st.markdown("**🔍 识别到的缺陷：**")
                        for d in defects[:10]:
                            sev_icon = {"致命": "🔴", "主要": "🟡", "次要": "🟢"}.get(d.get("severity", "次要"), "⚪")
                            st.markdown(
                                f"- {sev_icon} **{d.get('type', '未知')}** × {d.get('quantity', 0)}件"
                                f" — {d.get('description', '')}"
                            )
                    st.session_state.final_report = result
                    st.session_state.agent_finished = True
                    _render_final_report(result)
                    return
                else:
                    vstatus.update(label=f"❌ 分析失败：{result}", state="error")
                    st.error(f"分析失败：{result}")
                    return

        elif mode == "fast":
            # ===== 快速模式：3次视觉投票 + AQL 判定，15-45 秒 =====
            if not st.session_state.image_bytes_list:
                st.warning("⚡ 快速模式需要上传产品图片，请先上传图片")
                return
            ctx.image_bytes_list = st.session_state.image_bytes_list
            with st.status("⚡ 快速分析中（3次视觉投票，约15-45秒）...", expanded=True) as vstatus:
                status, result, defects, img_labels = run_agent(
                    messages=messages,
                    config=config,
                    context=ctx,
                    tools_schema=TOOLS_SCHEMA,
                    tool_registry=TOOL_REGISTRY,
                    mode="fast",
                )
                if status == "report":
                    vstatus.update(
                        label=f"✅ 分析完成！发现 {len(defects)} 项缺陷（3次投票）",
                        state="complete",
                    )
                    if defects:
                        st.markdown("**🔍 识别到的缺陷：**")
                        for d in defects[:10]:
                            sev_icon = {"致命": "🔴", "主要": "🟡", "次要": "🟢"}.get(d.get("severity", "次要"), "⚪")
                            st.markdown(
                                f"- {sev_icon} **{d.get('type', '未知')}** × {d.get('quantity', 0)}件"
                                f" — {d.get('description', '')}"
                            )
                    st.session_state.final_report = result
                    st.session_state.agent_finished = True
                    _render_final_report(result)
                    return
                else:
                    vstatus.update(label=f"❌ 分析失败：{result}", state="error")
                    st.error(f"分析失败：{result}")
                    return

        else:
            # ===== 智能模式：视觉分析（可见状态）+ Agent 多轮推理 =====
            vision_done = False
            if st.session_state.image_bytes_list:
                ctx.image_bytes_list = st.session_state.image_bytes_list
                ctx.images_preprocessed = True
                with st.status("🔍 正在分析图片（qwen-vl-plus）...", expanded=True) as vstatus:
                    from app_pro.agent_loop import analyze_images_vision
                    vok, vresult, vdefects, vlabels = analyze_images_vision(config, ctx)
                    if vok:
                        vstatus.update(
                            label=f"✅ 图片分析完成：{vresult}（发现 {len(vdefects)} 项缺陷）",
                            state="complete",
                        )
                        vision_done = True
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
                status, result, _, _ = run_agent(
                    messages=messages,
                    config=config,
                    context=ctx,
                    tools_schema=TOOLS_SCHEMA,
                    tool_registry=TOOL_REGISTRY,
                    mode="intelligent",
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
# 报告入库（Supabase）
# ============================================================================


def _get_current_user_email() -> str | None:
    """best-effort 获取当前登录用户邮箱。"""
    try:
        if hasattr(st, "user") and getattr(st.user, "is_logged_in", False):
            return getattr(st.user, "email", None)
    except Exception:
        pass
    return st.session_state.get("user_email") or None


def _save_report_to_supabase(report: dict) -> tuple[bool, str]:
    """
    把验货报告写入 Supabase `inspection_reports` 表。
    供智能模式工具（search_defect_history / get_product_profile）查询真实历史。
    失败不阻断主流程（报告照常展示 + PDF 照常生成）。
    返回: (success: bool, message: str)
    """
    try:
        from app_pro.tools import _get_supabase
        client = _get_supabase()
        if client is None:
            msg = "Supabase 未配置（检查 Secrets）"
            logger.warning("[DB] %s", msg)
            return False, msg

        # 抽样方案（与 PDF 计算一致）
        sample_size = None
        try:
            oq = int(st.session_state.order_quantity or 0)
        except (TypeError, ValueError):
            oq = 0
        if oq > 0:
            try:
                acre = compute_three_layer_acre(
                    oq,
                    st.session_state.aql_critical,
                    st.session_state.aql_major,
                    st.session_state.aql_minor,
                )
                sample_size = int(acre["critical"]["sample_size"])
            except Exception:
                pass

        row = {
            "user_email": _get_current_user_email() or "anonymous",
            "product_name": (st.session_state.product_name or "").strip(),
            "factory_name": (st.session_state.factory_name or "").strip() or None,
            "order_quantity": oq or None,
            "aql_critical": st.session_state.aql_critical,
            "aql_major": st.session_state.aql_major,
            "aql_minor": st.session_state.aql_minor,
            "conclusion": report.get("conclusion", ""),
            "three_layer_result": report.get("three_layer_result", {}),
            "defects": report.get("defects", []),
            "recommendation": report.get("recommendation", ""),
            "confidence": float(report.get("confidence", 0.0) or 0.0),
            "report_mode": report.get("mode", "unknown"),
            "sample_size": sample_size,
            "pdf_filename": st.session_state.get("pdf_filename"),
        }
        client.table("inspection_reports").insert(row).execute()
        msg = f"报告已入库: {row['product_name']}"
        logger.info("[DB] %s", msg)
        return True, msg
    except Exception as e:
        msg = str(e)
        logger.warning("[DB] 报告入库失败（不影响展示）: %s", msg)
        return False, msg


# ============================================================================
# 最终报告渲染
# ============================================================================


def _render_final_report(report: dict):
    """渲染 Agent 最终报告（chat 内 + 侧边操作），并触发入库与 PDF。"""
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

    # ===== 报告入库（Supabase，供工具/历史查询）=====
    if not st.session_state.get("_report_saved", False):
        db_ok, db_msg = _save_report_to_supabase(report)
        st.session_state._report_saved = db_ok
        if not db_ok:
            st.warning(f"⚠️ 报告未保存到历史：{db_msg}")

    # ===== PDF 自动生成 + 下载 =====
    # 报告生成后自动生成 PDF 并存入 session_state，下载按钮持久显示，无需额外点击
    if not st.session_state.pdf_bytes:
        with st.spinner("正在生成 PDF 报告..."):
            _generate_pdf_bytes(report)
    if st.session_state.pdf_bytes:
        st.success("✅ PDF 报告已生成，可直接下载：")
        # 顶部持久区也会同步显示，这里是报告内的直接下载入口
        st.download_button(
            "⬇️ 下载 PDF 报告",
            data=st.session_state.pdf_bytes,
            file_name=st.session_state.pdf_filename or "report.pdf",
            mime="application/pdf",
            use_container_width=True,
            key="pdf_dl_inline",
        )
        if st.button("🔄 重新生成 PDF", use_container_width=True, key="regen_pdf"):
            st.session_state.pdf_bytes = None
            st.rerun()
    else:
        st.error("PDF 生成失败，请检查字体配置或重试（点 🔄 重置后重新验货）。")


def _generate_pdf_bytes(report: dict):
    """生成 PDF 并存入 session_state，下方会持久渲染下载按钮。"""
    font_ok = check_font_available()
    if not font_ok:
        st.warning(get_font_warning_message())

    try:
        # 补全 report_data 字段（与报告一致）
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

        # ===== 计算抽样方案（样本量 + Ac/Re）=====
        # 依据 ANSI/ASQ Z1.4 一般检查水平 II，由订单数量查表得到
        try:
            oq = int(st.session_state.order_quantity or 0)
        except (TypeError, ValueError):
            oq = 0
        if oq > 0:
            acre = compute_three_layer_acre(
                oq,
                st.session_state.aql_critical,
                st.session_state.aql_major,
                st.session_state.aql_minor,
            )
            report_data["sample_size"] = acre["critical"]["sample_size"]
            report_data["sample_code"] = acre["critical"]["sample_code"]
            # aql_info 供 PDF 展示完整抽样方案（样本量代码 + 各层 Ac/Re）
            report_data["aql_info"] = {
                "sample_code": acre["critical"]["sample_code"],
                "critical_aql": st.session_state.aql_critical,
                "major_aql": st.session_state.aql_major,
                "minor_aql": st.session_state.aql_minor,
                "critical_ac": acre["critical"]["ac"], "critical_re": acre["critical"]["re"],
                "major_ac": acre["major"]["ac"], "major_re": acre["major"]["re"],
                "minor_ac": acre["minor"]["ac"], "minor_re": acre["minor"]["re"],
            }
        else:
            report_data["sample_size"] = "N/A"
        report_data["inspection_date"] = datetime.now().strftime("%Y-%m-%d")

        pdf_bytes = generate_inspection_pdf(report_data, st.session_state.uploaded_files)
        # 存入 session_state，以便任何后续 rerun 都能持久显示下载按钮
        st.session_state.pdf_bytes = pdf_bytes
        st.session_state.pdf_filename = f"{report_data['report_id']}.pdf"
    except Exception as e:
        st.session_state.pdf_bytes = None
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

    client, model_name = build_ai_client(qwen_key=api_key, timeout_seconds=120)
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
        new_bytes_list = [f.getvalue() for f in uploaded]
        # 用 (文件名, 长度) 作为图片集合签名，只在真正的图片集合变化时才解锁。
        # 这避免了逐张上传时每次 file_uploader 重新执行都把触发锁重置为 False，
        # 进而重复自动触发 "请分析我刚上传的图片…"。
        new_signature = tuple((f.name, len(b)) for f, b in zip(uploaded, new_bytes_list))
        if new_signature != st.session_state.trigger_signature:
            st.session_state.analysis_triggered = False
            st.session_state.trigger_signature = new_signature
        st.session_state.uploaded_files = uploaded
        st.session_state.image_bytes_list = new_bytes_list

        # 预览缩略图
        cols = st.columns(min(len(uploaded), 6))
        for i, (f, col) in enumerate(zip(uploaded, cols)):
            with col:
                st.image(f, caption=f"图{i+1}: {f.name}", use_container_width=True)

        st.success(f"已上传 {len(uploaded)} 张图片，自动开始分析...")

        if st.session_state.agent_finished:
            st.session_state.agent_finished = False
            st.session_state.final_report = None
    else:
        # 清空图片也重置触发锁和签名
        if st.session_state.image_bytes_list:
            st.session_state.analysis_triggered = False
            st.session_state.trigger_signature = None
        st.session_state.image_bytes_list = []


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

    # ===== PDF 下载区（任何时候只要 PDF 已生成就显示）=====
    def render_pdf_download():
        """持久化 PDF 下载按钮，写入 session_state 后任何 rerun 都能显示。"""
        if st.session_state.pdf_bytes:
            st.markdown("---")
            st.markdown("#### 📥 报告下载")
            st.download_button(
                "⬇️ 下载 PDF 报告",
                data=st.session_state.pdf_bytes,
                file_name=st.session_state.pdf_filename or "report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

    # 顶部品牌栏
    st.markdown(
        """
    <div style="background: #1B4FD8; color: white; padding: 1rem 1.5rem; border-radius: 8px; margin-bottom: 1rem;">
        <b>🔍 验货AI Agent Pro</b> &nbsp;|&nbsp; 专业版 · 多轮追问 · 工具调用 · 记忆档案
    </div>
    """,
        unsafe_allow_html=True,
    )

    render_pdf_download()

    # 图片上传
    render_upload()

    st.divider()

    # 顶层持久渲染：若已有最终结果，始终显示（避免 rerun 后丢失）
    if st.session_state.final_report:
        _render_final_report(st.session_state.final_report)
        st.divider()

    # 根据模式渲染不同 UI
    if st.session_state.mode == "intelligent":
        # ===== 智能模式 =====
        render_chat()

        # 开始验货按钮（取消自动触发，用户主动点击）
        col_start, col_reset = st.columns([4, 1])
        with col_start:
            user_input = st.chat_input("输入消息，或描述问题/补充信息...")
            start_inspection = st.button(
                "🔍 开始验货",
                type="primary",
                use_container_width=True,
                help="点击后开始对已上传的图片进行验货",
            )
        with col_reset:
            if st.button("🔄 重置", use_container_width=True):
                for k in ["agent_messages", "tool_calls"]:
                    st.session_state[k] = []
                for k in ["agent_context", "final_report"]:
                    st.session_state[k] = None
                st.session_state.agent_finished = False
                st.session_state.analysis_triggered = False
                st.session_state.trigger_signature = None
                st.session_state.pdf_bytes = None
                st.session_state.pdf_filename = None
                st.rerun()

        if user_input:
            handle_user_input(user_input)
        elif start_inspection:
            # 按钮触发：重置触发锁后启动一轮新验货（防双触发）
            st.session_state.analysis_triggered = False
            st.session_state.agent_finished = False
            st.session_state.pdf_bytes = None
            st.session_state.pdf_filename = None
            handle_user_input("请分析我上传的图片，给出验货结论。")

        # 如果没有对话历史，给出引导
        if not st.session_state.agent_messages:
            st.info(
                "👋 填写左侧参数并上传图片后，点击「🔍 开始验货」即可启动 Agent 分析；"
                "也可在下方输入框补充说明或提问。"
            )

    elif st.session_state.mode == "fast":
        # ===== 快速模式 =====
        st.markdown("### ⚡ 快速模式")
        st.caption("3次视觉投票 + AQL 确定性判定，约 15-45 秒，平衡速度与准确性")

        col_start, col_reset = st.columns([4, 1])
        with col_start:
            start_inspection = st.button(
                "🔍 开始验货",
                type="primary",
                use_container_width=True,
                help="点击后开始对已上传的图片进行验货",
            )
        with col_reset:
            if st.button("🔄 重置", use_container_width=True, key="fast_reset"):
                for k in ["agent_messages", "tool_calls"]:
                    st.session_state[k] = []
                for k in ["agent_context", "final_report"]:
                    st.session_state[k] = None
                st.session_state.agent_finished = False
                st.session_state.analysis_triggered = False
                st.session_state.trigger_signature = None
                st.session_state.pdf_bytes = None
                st.session_state.pdf_filename = None
                st.rerun()

        if start_inspection:
            st.session_state.analysis_triggered = False
            st.session_state.agent_finished = False
            st.session_state.pdf_bytes = None
            st.session_state.pdf_filename = None
            handle_user_input("请分析我上传的图片，给出验货结论。")
        elif not st.session_state.final_report:
            st.info("👋 填写左侧参数并上传图片后，点击「🔍 开始验货」启动快速分析。")

    else:
        # ===== 极速模式（Turbo）=====  # 默认模式
        st.markdown("### 🚀 极速模式")
        st.caption("单次视觉分析 + AQL 判定，5-10 秒完成，适合简单标准验货")

        col_start, col_reset = st.columns([4, 1])
        with col_start:
            start_inspection = st.button(
                "🚀 极速验货",
                type="primary",
                use_container_width=True,
                help="点击后开始对已上传的图片进行验货",
            )
        with col_reset:
            if st.button("🔄 重置", use_container_width=True, key="turbo_reset"):
                for k in ["agent_messages", "tool_calls"]:
                    st.session_state[k] = []
                for k in ["agent_context", "final_report"]:
                    st.session_state[k] = None
                st.session_state.agent_finished = False
                st.session_state.analysis_triggered = False
                st.session_state.trigger_signature = None
                st.session_state.pdf_bytes = None
                st.session_state.pdf_filename = None
                st.rerun()

        if start_inspection:
            st.session_state.analysis_triggered = False
            st.session_state.agent_finished = False
            st.session_state.pdf_bytes = None
            st.session_state.pdf_filename = None
            handle_user_input("请分析我上传的图片，给出验货结论。")
        elif not st.session_state.final_report:
            st.info("👋 填写左侧参数并上传图片后，点击「🚀 极速验货」启动分析（约5-10秒）。")


if __name__ == "__main__":
    main()
