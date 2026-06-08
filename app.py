import streamlit as st
import os

# 页面配置
st.set_page_config(
    page_title="外贸验货AI Agent - MVP",
    page_icon="📦",
    layout="wide"
)

# ===== 新增：初始化免费次数 =====
if "free_quota" not in st.session_state:
    st.session_state["free_quota"] = 5  # 5次免费体验
if "user_logged_in" not in st.session_state:
    st.session_state["user_logged_in"] = False

# 标题
st.title("📦 外贸验货AI Agent - MVP")
st.markdown("---")

# ===== 新增：简化登录（侧边栏）=====
with st.sidebar:
    st.header("关于")
    st.info(
        "这是一个MVP版本，用于验证市场需求。\n\n"
        "**核心功能：** 上传产品照片 → AI分析 → 生成验货报告"
    )
    st.markdown("---")
    
    # ===== 简化登录：只需手机号 =====
    if not st.session_state["user_logged_in"]:
        st.subheader("🔐 快速登录")
        phone = st.text_input("手机号", placeholder="13800000000")
        
        col_login1, col_login2 = st.columns([2, 1])
        with col_login1:
            code = st.text_input("验证码", placeholder="4位数字")
        with col_login2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("获取验证码", use_container_width=True):
                if phone:
                    st.success("验证码已发送")  # TODO: 实际调用短信API
                else:
                    st.error("请输入手机号")
        
        if st.button("立即登录", type="primary"):
            if phone and code:
                st.session_state["user_logged_in"] = True
                st.session_state["phone"] = phone
                st.rerun()
        
        # 临时：直接跳过登录测试
        if st.button("跳过登录（测试用）"):
            st.session_state["user_logged_in"] = True
            st.session_state["phone"] = "13800000000"
            st.rerun()
    else:
        # 已登录显示用户信息
        st.success(f"✅ 已登录：{st.session_state.get('phone', '用户')}")
        st.info(f"🎁 免费剩余次数：{st.session_state['free_quota']} 次")
        if st.button("退出登录"):
            st.session_state["user_logged_in"] = False
            st.rerun()
    
    st.markdown("---")
    
    # API Key 配置（可选，免费次数用完才需要）
    st.subheader("🔑 API配置（可选）")
    api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        help="免费次数用完后需要填写自己的API Key"
    )
    
    if api_key:
        st.success("✅ API Key已设置")
        st.session_state["openai_api_key"] = api_key
    else:
        st.info("💡 免费次数用完后需填写")
    
    st.markdown("---")
    st.caption("版本：0.1.1 (MVP)")
    st.caption("更新时间：2026-06-08")

# 主界面
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1️⃣ 上传产品照片")
    
    # ===== 新增：拍照指南 =====
    with st.expander("📸 拍照指南（点击展开）", expanded=True):
        col_guide1, col_guide2 = st.columns(2)
        
        with col_guide1:
            st.markdown("**✅ 正确示范**")
            # 检查示例图片是否存在
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
        st.markdown(""""
        **💡 拍照小贴士**
        - 每次只拍1个产品
        - 缺陷细节要清晰对焦
        - 整体+局部各拍1张
        - 建议上传3-10张不同角度
        """)
    
    # 原有的上传组件
    uploaded_files = st.file_uploader(
        "选择产品照片（3-10张，不同角度）",
        type=['jpg', 'jpeg', 'png'],
        accept_multiple_files=True
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
