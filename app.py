import streamlit as st
import os
from datetime import datetime, timezone, timedelta
import base64
from io import BytesIO
import openai
import json
import base64

# 导入PDF生成模块
from generate_pdf import generate_inspection_pdf, check_font_available

# ===== 配置API客户端 =====
# 优先级：通义千问VL > DeepSeek > OpenAI

def get_ai_client():
    """获取AI客户端（通义千问/DeepSeek/OpenAI）"""
    # 1. 优先使用通义千问VL（支持视觉，便宜）
    qwen_key = st.secrets.get("qwen", {}).get("api_key")
    if qwen_key:
        client = openai.OpenAI(
            api_key=qwen_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        return client, "qwen-vl-plus"  # 通义千问VL模型（支持图片）
    
    # 2. 降级到DeepSeek（便宜，仅文本）
    deepseek_key = st.secrets.get("deepseek", {}).get("api_key")
    if deepseek_key:
        client = openai.OpenAI(
            api_key=deepseek_key,
            base_url="https://api.deepseek.com"
        )
        return client, "deepseek-chat"
    
    # 3. 降级到OpenAI（贵，但稳定）
    openai_key = st.secrets.get("openai", {}).get("api_key", os.getenv("OPENAI_API_KEY"))
    if openai_key:
        client = openai.OpenAI(api_key=openai_key)
        return client, "gpt-4o"
    
    raise ValueError("❌ 未配置API Key！请在 .streamlit/secrets.toml 中配置 qwen/deepseek/openai")

# ===== AI分析函数 =====
def analyze_product_images(uploaded_files, product_name, inspection_standard):
    """
    调用 AI (DeepSeek/OpenAI) Vision API 分析产品图片
    
    Args:
        uploaded_files: Streamlit UploadedFile 列表
        product_name: 产品名称
        inspection_standard: 验货标准（如 "AQL 2.5"）
    
    Returns:
        dict: 包含 conclusion, defects 的报告数据
    """
    try:
        # 获取AI客户端和模型
        client, model_name = get_ai_client()
        
        # 构建消息内容
        messages = [
            {
                "role": "system",
                "content": """你是一位专业的外贸验货员。请分析产品图片，识别缺陷类型、数量和严重程度。
                
输出格式（严格按JSON）：
{
  "conclusion": "验货结论（接受/有条件通过/拒收）",
  "defects": [
    {"type": "缺陷类型", "quantity": 数量, "severity": "轻微/中等/严重"}
  ],
  "recommendation": "改进建议"
}
                """
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"请分析这款产品：{product_name}\n验货标准：{inspection_standard}\n\n请识别图片中的缺陷，输出JSON格式结果。"
                    }
                ]
            }
        ]
        
        # 添加图片到消息
        for uploaded_file in uploaded_files:
            # 将图片转换为 base64
            image_bytes = uploaded_file.getvalue()
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            
            messages[1]["content"].append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}"
                }
            })
        
        # 调用 AI Vision API
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=1000,
            temperature=0.3
        )
        
        # 解析AI返回的结果
        ai_response = response.choices[0].message.content
        
        # 尝试解析JSON
        try:
            result = json.loads(ai_response)
        except json.JSONDecodeError:
            # 如果AI返回的不是纯JSON，尝试提取JSON部分
            import re
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                raise ValueError("AI返回格式错误")
        
        return result
    
    except Exception as e:
        st.error(f"❌ AI分析失败：{str(e)}")
        # 返回模拟数据作为降级方案
        return {
            "conclusion": "⚠️ AI分析失败，使用模拟数据",
            "defects": [
                {"type": "分析失败", "quantity": 0, "severity": "未知"}
            ],
            "recommendation": "请检查API Key或网络连接"
        }

# 页面配置
st.set_page_config(
    page_title="外贸验货AI Agent - MVP",
    page_icon="📦",
    layout="wide"
)

# ===== 初始化session_state =====
# 次数限制（简单防护，刷新页面会重置）
if "inspection_count" not in st.session_state:
    st.session_state["inspection_count"] = 0  # 累计验货次数
if "inspection_limit" not in st.session_state:
    st.session_state["inspection_limit"] = 20  # 每次会话限制20次
if "inspection_history" not in st.session_state:
    st.session_state["inspection_history"] = []  # 验货历史记录
if "total_savings" not in st.session_state:
    st.session_state["total_savings"] = 0  # 累计节省金额

# ===== 检查是否超过次数限制 =====
def is_limit_reached():
    """检查是否达到使用次数限制"""
    return st.session_state["inspection_count"] >= st.session_state["inspection_limit"]

# 标题
st.title("📦 外贸验货AI Agent - MVP")
st.markdown("---")

# ===== 侧边栏 =====
with st.sidebar:
    st.header("关于")
    st.info(
        "这是一个MVP版本，用于验证市场需求。\n\n"
        "**核心功能：** 上传产品照片 → AI分析 → 生成验货报告"
    )
    st.markdown("---")
    
    # 使用次数提示
    remaining = st.session_state["inspection_limit"] - st.session_state["inspection_count"]
    st.subheader("📊 使用统计")
    st.metric("已使用次数", f"{st.session_state['inspection_count']} 次")
    st.metric("剩余次数", f"{remaining} 次")
    
    if remaining <= 5:
        st.warning(f"⚠️ 剩余次数不多，建议配置自己的API Key")
    
    st.caption(f"💡 每次会话限制 {st.session_state['inspection_limit']} 次")
    st.caption("如需更多次数，请联系开发者获取API Key")
    st.markdown("---")
    
    # ROI展示
    if st.session_state["inspection_history"]:
        st.subheader("💰 您的节省统计")
        total_inspections = len(st.session_state["inspection_history"])
        total_savings = st.session_state["total_savings"]
        st.metric("累计验货次数", f"{total_inspections} 次")
        st.metric("累计节省金额", f"￥{total_savings:,.0f}")
        st.caption("每次AI验货约节省￥200-500人工成本")
        st.markdown("---")
    
    st.caption("版本：0.2.2 (MVP)")
    st.caption("更新时间：2026-06-13")

# 主界面
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1️⃣ 上传产品照片")
    
    # 拍照指南
    with st.expander("📸 拍照指南（点击展开）", expanded=True):
        col_guide1, col_guide2 = st.columns(2)
        
        with col_guide1:
            st.markdown("**✅ 正确示范**")
            correct_img_path = os.path.join(os.path.dirname(__file__), "example_images", "correct.jpg")
            if os.path.exists(correct_img_path):
                st.image(correct_img_path, caption="光线充足、45°角、清晰", use_column_width=True)
            else:
                st.info("✅ 光线充足\n✅ 45°角拍摄\n✅ 缺陷细节清晰")
        
        with col_guide2:
            st.markdown("**❌ 错误示范**")
            wrong_img_path = os.path.join(os.path.dirname(__file__), "example_images", "wrong.jpg")
            if os.path.exists(wrong_img_path):
                st.image(wrong_img_path, caption="光线暗、距离远、模糊", use_column_width=True)
            else:
                st.error("❌ 光线太暗\n❌ 距离太远\n❌ 模糊不清")
        
        st.markdown("---")
        st.markdown("""
        **💡 拍照小贴士**
        - 每次只拍1个产品
        - 缺陷细节要清晰对焦
        - 整体+局部各拍1张
        - 建议上传3-10张不同角度
        """)
    
    # 上传组件
    uploaded_files = st.file_uploader(
        "选择产品照片（3-10张，不同角度）",
        type=['jpg', 'jpeg', 'png'],
        accept_multiple_files=True,
        disabled=is_limit_reached()
    )
    
    # 显示上传的图片预览
    if uploaded_files:
        st.success(f"✅ 已上传 {len(uploaded_files)} 张照片")
        cols = st.columns(3)
        for idx, file in enumerate(uploaded_files):
            with cols[idx % 3]:
                st.image(file, caption=file.name, use_column_width=True)

with col2:
    st.subheader("2️⃣ 填写基本信息")
    product_name = st.text_input(
        "产品名称",
        placeholder="例如：不锈钢保温杯",
        help="请输入产品的通用名称",
        disabled=is_limit_reached()
    )
    
    inspection_standard = st.selectbox(
        "验货标准",
        options=["AQL 1.5", "AQL 2.5", "客户自定义"],
        index=1,
        help="AQL (Acceptable Quality Limit) 是外贸验货常用标准",
        disabled=is_limit_reached()
    )
    
    order_quantity = st.number_input(
        "订单数量",
        min_value=1,
        value=500,
        step=100,
        help="用于计算抽样数量",
        disabled=is_limit_reached()
    )
    
    # 抽样数量（简化计算，实际应根据MIL-STD-105E）
    if order_quantity <= 500:
        sample_size = min(order_quantity, 50)
    elif order_quantity <= 1200:
        sample_size = 80
    else:
        sample_size = 125
    
    st.info(f"📊 建议抽样数量：**{sample_size}** 件")

# 生成报告按钮
st.markdown("---")

# 次数限制提示
if is_limit_reached():
    st.error("❌ 本次会话已达到使用次数限制（20次）")
    st.info("💡 刷新页面可重置次数，或联系开发者获取更多次数")
else:
    remaining = st.session_state["inspection_limit"] - st.session_state["inspection_count"]
    st.info(f"📊 您还有 **{remaining}** 次免费使用次数")

col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    if st.button(
        "🚀 生成验货报告",
        use_container_width=True,
        type="primary",
        disabled=is_limit_reached() or not (uploaded_files and product_name)
    ):
        if not uploaded_files:
            st.error("❌ 请至少上传1张产品照片")
        elif not product_name:
            st.error("❌ 请填写产品名称")
        else:
            # 增加使用次数
            st.session_state["inspection_count"] += 1
            
            # 调用AI分析
            with st.spinner("🤖 AI正在分析图片..."):
                ai_result = analyze_product_images(
                    uploaded_files, 
                    product_name, 
                    inspection_standard
                )
            
            # ===== 生成报告数据 =====
            report_data = {
                "report_id": f"RPT-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                "product_name": product_name,
                "inspection_date": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
                "inspection_standard": inspection_standard,
                "order_quantity": order_quantity,
                "sample_size": sample_size,
                "conclusion": ai_result.get("conclusion", "⚠️ 分析失败"),
                "defects": ai_result.get("defects", []),
                "recommendation": ai_result.get("recommendation", ""),
                "savings": 350  # 每次验货节省金额（元）
            }
            
            # 保存到历史记录
            st.session_state["inspection_history"].append(report_data)
            st.session_state["total_savings"] += report_data["savings"]
            
            st.success("✅ 报告生成完成！")
            
            # ===== 显示报告 =====
            st.markdown("---")
            st.header("📋 验货报告")
            
            # 第1页：结论页
            st.subheader("1️⃣ 验货结论")
            col_con1, col_con2, col_con3 = st.columns(3)
            with col_con1:
                st.metric("验货编号", report_data["report_id"])
            with col_con2:
                st.metric("验货日期", report_data["inspection_date"])
            with col_con3:
                st.metric("抽样数量", f"{report_data['sample_size']} 件")
            
            st.markdown(f"### {report_data['conclusion']}")
            st.info(f"**建议：** {report_data['recommendation']}")
            
            # 第2页：缺陷清单
            st.markdown("---")
            st.subheader("2️⃣ 缺陷清单")
            if report_data["defects"]:
                for idx, defect in enumerate(report_data["defects"]):
                    col_def1, col_def2, col_def3 = st.columns([1, 1, 1])
                    with col_def1:
                        st.write(f"**缺陷{idx+1}**")
                        st.write(defect.get("type", "未知"))
                    with col_def2:
                        st.write("**数量**")
                        st.write(defect.get("quantity", 0))
                    with col_def3:
                        st.write("**严重程度**")
                        severity = defect.get("severity", "未知")
                        if severity == "轻微":
                            st.success(severity)
                        elif severity == "中等":
                            st.warning(severity)
                        else:
                            st.error(severity)
            else:
                st.info("✅ 未发现明显缺陷")
            
            # 第3页：照片附件
            st.markdown("---")
            st.subheader("3️⃣ 照片附件")
            if uploaded_files:
                photo_cols = st.columns(3)
                for idx, file in enumerate(uploaded_files):
                    with photo_cols[idx % 3]:
                        st.image(file, caption=file.name, use_column_width=True)
            
            # ===== 一键导出PDF按钮 =====
            st.markdown("---")
            st.subheader("📥 导出报告")
            
            # 检查字体是否可用
            font_available = check_font_available()
            
            col_pdf1, col_pdf2 = st.columns(2)
            with col_pdf1:
                if st.button("📄 预览报告（HTML）", use_container_width=True):
                    st.success("✅ 报告已生成！")
                    st.info("💡 使用浏览器打印功能保存为PDF：Ctrl+P 或 Cmd+P")
            
            with col_pdf2:
                # 生成PDF下载按钮
                try:
                    pdf_buffer = generate_inspection_pdf(report_data, uploaded_files)
                    
                    # 下载文件名
                    pdf_filename = f"验货报告_{report_data['product_name']}_{report_data['report_id']}.pdf"
                    
                    st.download_button(
                        label="📥 下载PDF报告",
                        data=pdf_buffer,
                        file_name=pdf_filename,
                        mime="application/pdf",
                        use_container_width=True,
                        key="download_pdf"
                    )
                    
                    if not font_available:
                        st.warning("⚠️ 未检测到中文字体，PDF可能显示为英文。请联系管理员添加字体文件。")
                
                except Exception as e:
                    st.error(f"❌ PDF生成失败：{str(e)}")
                    st.info("💡 临时方案：使用浏览器打印功能（Ctrl+P）保存为PDF")
            
            # ROI展示（本次验货）
            st.markdown("---")
            st.subheader("💰 本次验货价值")
            col_roi1, col_roi2, col_roi3 = st.columns(3)
            with col_roi1:
                st.metric("AI验货成本", "￥0（MVP免费）")
            with col_roi2:
                st.metric("节省人工成本", f"￥{report_data['savings']}")
            with col_roi3:
                st.metric("净节省", f"￥{report_data['savings']}")
            
            # 剩余次数提示
            remaining = st.session_state["inspection_limit"] - st.session_state["inspection_count"]
            if remaining <= 5:
                st.warning(f"⚠️ 剩余使用次数不多（{remaining}次），请珍惜使用")

# 页脚
st.markdown("---")
st.caption("💡 MVP版本 - 功能持续迭代中 | 有问题请联系开发者")

# ===== 历史记录（侧边栏底部）=====
if st.session_state["inspection_history"]:
    with st.sidebar:
        st.markdown("---")
        st.subheader("📜 验货历史")
        for idx, record in enumerate(st.session_state["inspection_history"][-5:]):  # 只显示最近5条
            st.text(f"{idx+1}. {record['product_name']}")
            st.caption(f"   {record['inspection_date']} | {record['conclusion']}")
