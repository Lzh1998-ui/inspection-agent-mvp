import streamlit as st
import os
from datetime import datetime
import base64
from io import BytesIO

# 导入PDF生成模块
from generate_pdf import generate_inspection_pdf, check_font_available

# 页面配置
st.set_page_config(
    page_title="外贸验货AI Agent - MVP",
    page_icon="📦",
    layout="wide"
)

# ===== 初始化session_state =====
if "free_quota" not in st.session_state:
    st.session_state["free_quota"] = 5  # 5次免费体验
if "user_logged_in" not in st.session_state:
    st.session_state["user_logged_in"] = False
if "inspection_history" not in st.session_state:
    st.session_state["inspection_history"] = []  # 验货历史记录
if "total_savings" not in st.session_state:
    st.session_state["total_savings"] = 0  # 累计节省金额

# 标题
st.title("📦 外贸验货AI Agent - MVP")
st.markdown("---")

# ===== 侧边栏：简化登录 =====
with st.sidebar:
    st.header("关于")
    st.info(
        "这是一个MVP版本，用于验证市场需求。\n\n"
        "**核心功能：** 上传产品照片 → AI分析 → 生成验货报告"
    )
    st.markdown("---")
    
    # 登录逻辑
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
        
        # ===== 新增：ROI展示 =====
        if st.session_state["inspection_history"]:
            st.markdown("---")
            st.subheader("📊 您的节省统计")
            total_inspections = len(st.session_state["inspection_history"])
            total_savings = st.session_state["total_savings"]
            st.metric("累计验货次数", f"{total_inspections} 次")
            st.metric("累计节省金额", f"￥{total_savings:,.0f}")
            st.caption("每次AI验货约节省￥200-500人工成本")
        
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
    st.caption("版本：0.2.0 (MVP)")
    st.caption("更新时间：2026-06-09")

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
            # 检查免费次数
            if st.session_state["free_quota"] <= 0 and "openai_api_key" not in st.session_state:
                st.error("❌ 免费次数已用完，请填写API Key或联系客服购买套餐")
                st.stop()
            
            # 扣除免费次数
            if st.session_state["free_quota"] > 0:
                st.session_state["free_quota"] -= 1
            
            # 模拟AI分析过程
            with st.spinner("🤖 AI正在分析图片..."):
                import time
                time.sleep(3)  # 模拟3秒分析时间
            
            # ===== 生成模拟报告数据 =====
            report_data = {
                "report_id": f"RPT-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                "product_name": product_name,
                "inspection_date": datetime.now().strftime("%Y-%m-%d"),
                "inspection_standard": inspection_standard,
                "order_quantity": order_quantity,
                "sample_size": sample_size,
                "conclusion": "⚠️ 有条件通过（Minor Defects）",
                "defects": [
                    {"type": "划痕", "quantity": 3, "severity": "轻微", "image": uploaded_files[0] if uploaded_files else None},
                    {"type": "标签错误", "quantity": 1, "severity": "中等", "image": uploaded_files[1] if len(uploaded_files) > 1 else None},
                ],
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
            st.info("""
            **建议：** 接受该批次，但要求供应商改进包装，避免运输过程中产生划痕。
            **标签错误**需在出货前更正。
            """)
            
            # 第2页：缺陷清单
            st.markdown("---")
            st.subheader("2️⃣ 缺陷清单")
            for idx, defect in enumerate(report_data["defects"]):
                col_def1, col_def2, col_def3, col_def4 = st.columns([1, 1, 1, 2])
                with col_def1:
                    st.write(f"**缺陷{idx+1}**")
                    st.write(defect["type"])
                with col_def2:
                    st.write("**数量**")
                    st.write(defect["quantity"])
                with col_def3:
                    st.write("**严重程度**")
                    if defect["severity"] == "轻微":
                        st.success(defect["severity"])
                    elif defect["severity"] == "中等":
                        st.warning(defect["severity"])
                    else:
                        st.error(defect["severity"])
                with col_def4:
                    if defect["image"]:
                        st.image(defect["image"], caption=f"{defect['type']}示例", width=150)
            
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
                st.metric("AI验货成本", "￥0（免费次数）" if st.session_state["free_quota"] >= 0 else "￥9.9")
            with col_roi2:
                st.metric("节省人工成本", f"￥{report_data['savings']}")
            with col_roi3:
                st.metric("净节省", f"￥{report_data['savings']}")

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
