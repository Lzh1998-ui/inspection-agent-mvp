import streamlit as st

# 页面配置
st.set_page_config(
    page_title="外贸验货AI Agent - MVP",
    page_icon="📦",
    layout="wide"
)

# 标题
st.title("📦 外贸验货AI Agent - MVP")
st.markdown("---")

# 侧边栏
with st.sidebar:
    st.header("关于")
    st.info(
        "这是一个MVP版本，用于验证市场需求。\n\n"
        "**核心功能：** 上传产品照片 → AI分析 → 生成验货报告"
    )
    st.markdown("---")
    
    # API Key 配置（用户自己输入）
    st.subheader("🔑 API配置")
    api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        help="从 https://platform.openai.com/api-keys 获取"
    )
    
    if api_key:
        st.success("✅ API Key已设置")
        # 存储到session_state
        st.session_state["openai_api_key"] = api_key
    else:
        st.warning("⚠️ 请输入OpenAI API Key")
        # 尝试从secrets读取（本地开发用）
        try:
            st.session_state["openai_api_key"] = st.secrets["OPENAI_API_KEY"]
            st.success("✅ 已从secrets读取API Key（本地开发模式）")
        except:
            pass
    
    st.markdown("---")
    st.caption("版本：0.1.0 (MVP)")
    st.caption("更新时间：2026-06-07")

# 主界面
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1️⃣ 上传产品照片")
    uploaded_files = st.file_uploader(
        "选择产品照片（3-10张，不同角度）",
        type=['jpg', 'jpeg', 'png'],
        accept_multiple_files=True,
        help="建议上传：正面、背面、侧面、细节、包装等角度"
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
        help="请输入产品的通用名称"
    )
    
    inspection_standard = st.selectbox(
        "验货标准",
        options=["AQL 1.5", "AQL 2.5", "客户自定义"],
        index=1,
        help="AQL (Acceptable Quality Limit) 是外贸验货常用标准"
    )
    
    order_quantity = st.number_input(
        "订单数量",
        min_value=1,
        value=500,
        step=100,
        help="用于计算抽样数量"
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
col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    if st.button(
        "🚀 生成验货报告",
        use_container_width=True,
        type="primary",
        disabled=not (uploaded_files and product_name)
    ):
        if not uploaded_files:
            st.error("❌ 请至少上传1张产品照片")
        elif not product_name:
            st.error("❌ 请填写产品名称")
        else:
            st.success("✅ 准备生成报告...")
            st.info("🚧 MVP阶段：报告生成功能即将上线（Day 3-4）")
            
            # TODO: 后续集成 AI 分析逻辑
            # with st.spinner("AI正在分析图片..."):
            #     report_text = analyze_product_images(...)
            # st.success("✅ 报告生成完成！")

# 页脚
st.markdown("---")
st.caption("💡 MVP版本 - 功能持续迭代中 | 有问题请联系开发者")
