import streamlit as st
import os
from datetime import datetime, timezone, timedelta
import base64
from io import BytesIO
import openai
import json
import base64

# ===== 页面配置（必须在所有Streamlit调用之前）=====
st.set_page_config(
    page_title="外贸验货AI Agent - MVP",
    page_icon="📦",
    layout="wide"
)

# 导入PDF生成模块
from generate_pdf import generate_inspection_pdf, check_font_available

# 导入用户认证模块
from auth_helper import (
    is_supabase_configured,
    sign_up, sign_in, sign_out,
    update_inspection_count, save_report, get_reports, get_user_count
)

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
    调用 AI Vision API 分析产品图片
    """
    try:
        client, model_name = get_ai_client()
        
        messages = [
            {
                "role": "system",
                "content": """你是一位拥有15年经验的外贸验货专家，精通ISO 2859-1/2抽样标准、AQL 2.5/4.0质量标准，熟悉电子产品、纺织品、机械配件、玩具等各类产品的国际质量标准（ISO、ASTM、GB、EN等）。

你的任务是根据用户上传的产品图片，进行专业的质量检验分析。

【输出要求】必须严格按以下JSON格式返回，不要添加任何其他文字：

{
  "conclusion": "合格/不合格/有条件接受",
  "defects": [
    {
      "type": "缺陷类型（如：划痕/变形/色差/功能异常/包装破损）",
      "quantity": 数字（必须是整数，如3，不能写"若干"或"少量"）,
      "severity": "严重/中等/轻微",
      "description": "详细描述缺陷位置、大小、程度（50字以内）",
      "image": ""（始终为空字符串）
    }
  ],
  "recommendation": "处理建议（100字以内，包含具体改进措施）",
  "confidence": 0.0-1.0之间的数字（表示判断置信度）

}

【判定标准】
- 合格：无严重缺陷，中等缺陷≤2个，轻微缺陷≤5个
- 不合格：存在任何严重缺陷，或中等缺陷>2个
- 有条件接受：介于两者之间，需客户确认

【注意事项】
⚠️ quantity字段必须是整数数字，禁止使用"若干"、"一些"、"多个"等模糊词汇
⚠️ 如果图片不清晰，description中注明"图片模糊，无法准确判断"
⚠️ 不要编造图片中不存在的缺陷
⚠️ 如果未发现缺陷，defects数组设为空 []
"""
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
        
        for uploaded_file in uploaded_files:
            image_bytes = uploaded_file.getvalue()
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            
            messages[1]["content"].append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}"
                }
            })
        
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=1000,
            temperature=0.3
        )
        
        ai_response = response.choices[0].message.content
        
        try:
            result = json.loads(ai_response)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                raise ValueError("AI返回格式错误")
        
        return result
    
    except Exception as e:
        st.error(f"❌ AI分析失败：{str(e)}")
        return {
            "conclusion": "⚠️ AI分析失败，使用模拟数据",
            "defects": [
                {"type": "分析失败", "quantity": 0, "severity": "未知"}
            ],
            "recommendation": "请检查API Key或网络连接"
        }

# ===== 辅助函数 =====
def get_remaining():
    """获取当前用户剩余次数"""
    user = st.session_state.get("user")
    if user:
        return user["inspection_limit"] - user["inspection_count"]
    else:
        return st.session_state["inspection_limit"] - st.session_state["inspection_count"]

def is_limit_reached():
    """检查是否达到使用次数限制"""
    user = st.session_state.get("user")
    if user:
        return user["inspection_count"] >= user["inspection_limit"]
    else:
        return st.session_state["inspection_count"] >= st.session_state["inspection_limit"]

def get_inspection_count():
    """获取当前用户已使用次数"""
    user = st.session_state.get("user")
    if user:
        return user["inspection_count"]
    return st.session_state["inspection_count"]

def get_inspection_limit():
    """获取当前用户总限制"""
    user = st.session_state.get("user")
    if user:
        return user["inspection_limit"]
    return st.session_state["inspection_limit"]

# ===== 登录/注册 UI =====
def show_auth_ui():
    """显示登录/注册表单"""
    st.subheader("🔐 用户登录")
    
    # Tab 切换
    tab1, tab2 = st.tabs(["登录", "注册"])
    
    with tab1:
        login_email = st.text_input("邮箱", key="login_email", placeholder="your@email.com")
        login_password = st.text_input("密码", type="password", key="login_pwd", placeholder="输入密码")
        
        if st.button("登录", type="primary", use_container_width=True):
            if not login_email or not login_password:
                st.error("请填写邮箱和密码")
            else:
                success, msg, user_data = sign_in(login_email, login_password)
                if success:
                    st.session_state["user"] = user_data
                    st.rerun()
                else:
                    st.error(msg)
    
    with tab2:
        reg_email = st.text_input("邮箱", key="reg_email", placeholder="your@email.com")
        reg_name = st.text_input("昵称（可选）", key="reg_name", placeholder="如何称呼您？")
        reg_password = st.text_input("密码", type="password", key="reg_pwd", placeholder="至少6位字符")
        reg_confirm = st.text_input("确认密码", type="password", key="reg_confirm", placeholder="再次输入密码")
        
        if st.button("注册", type="primary", use_container_width=True):
            if not reg_email or not reg_password:
                st.error("请填写邮箱和密码")
            elif reg_password != reg_confirm:
                st.error("两次密码不一致")
            elif len(reg_password) < 6:
                st.error("密码至少6位")
            else:
                success, msg = sign_up(reg_email, reg_password, reg_name)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
    
    st.markdown("---")
    # 免登录体验
    if st.button("🎮 免登录体验", use_container_width=True):
        st.session_state["skip_login"] = True
        st.rerun()

def show_user_info():
    """显示已登录用户信息"""
    user = st.session_state.get("user")
    if user:
        st.success(f"✅ {user.get('display_name', user['email'])}")
        remaining = user["inspection_limit"] - user["inspection_count"]
        st.metric("剩余次数", f"{remaining} 次")
        st.caption(f"已使用 {user['inspection_count']} / {user['inspection_limit']} 次")
        st.markdown("---")

# ===== 初始化session_state =====
if "inspection_count" not in st.session_state:
    st.session_state["inspection_count"] = 0
if "inspection_limit" not in st.session_state:
    st.session_state["inspection_limit"] = 3
if "inspection_history" not in st.session_state:
    st.session_state["inspection_history"] = []
if "total_savings" not in st.session_state:
    st.session_state["total_savings"] = 0
if "user" not in st.session_state:
    st.session_state["user"] = None
if "skip_login" not in st.session_state:
    st.session_state["skip_login"] = False

supabase_ready = is_supabase_configured()

# ===== 处理未登录状态 =====
if not st.session_state["user"] and not st.session_state["skip_login"]:
    # 未登录：显示登录/注册页面
    st.title("📦 外贸验货AI Agent - MVP")
    st.markdown("---")
    
    col_auth1, col_auth2 = st.columns([1, 1])
    
    with col_auth1:
        show_auth_ui()
    
    with col_auth2:
        st.subheader("💡 关于本应用")
        st.info(
            "上传产品照片 → AI自动分析缺陷 → 生成专业验货报告\n\n"
            "**免费体验：** 每用户3次/天\n\n"
            "**适用场景：**\n"
            "- 外贸验货员\n"
            "- 质检部门\n"
            "- 供应商管理\n\n"
            "**注册登录后可持久保存你的验货记录**"
        )
        
        st.markdown("---")
        st.caption(f"版本：0.3.0 (MVP) | Supabase状态：{'✅ 已连接' if supabase_ready else '⚠️ 未配置（次数不持久化）'}")
    
    st.stop()

# ===== 已登录：显示主应用 =====

# 标题
st.title("📦 外贸验货AI Agent - MVP")
st.markdown("---")

# ===== 侧边栏 =====
with st.sidebar:
    st.header("关于")
    st.info(
        "上传产品照片 → AI分析 → 生成验货报告"
    )
    st.markdown("---")
    
    # 用户信息
    show_user_info()
    
    # 使用统计
    remaining = get_remaining()
    st.subheader("📊 使用统计")
    st.metric("已使用次数", f"{get_inspection_count()} 次")
    st.metric("剩余次数", f"{remaining} 次")
    
    if remaining <=2:
        st.warning(f"⚠️ 剩余次数不多")
    
    st.caption(f"💡 每用户 {get_inspection_limit()} 次")
    st.markdown("---")
    
    # ROI展示
    if st.session_state["inspection_history"]:
        st.subheader("💰 您的节省统计")
        st.metric("累计验货次数", f"{len(st.session_state['inspection_history'])} 次")
        st.metric("累计节省金额", f"￥{st.session_state['total_savings']:,.0f}")
        st.caption("每次AI验货约节省￥200-500人工成本")
        st.markdown("---")
    
    # 退出登录
    if st.button("🚪 退出登录"):
        sign_out()
        st.session_state["user"] = None
        st.session_state["skip_login"] = False
        st.session_state["inspection_history"] = []
        st.session_state["total_savings"] = 0
        st.rerun()
    
    st.markdown("---")
    st.caption(f"版本：0.3.0 (MVP)")
    st.caption(f"更新时间：2026-06-13")

# 主界面
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1️⃣ 上传产品照片")
    
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
    
    uploaded_files = st.file_uploader(
        "选择产品照片（3-10张，不同角度）",
        type=['jpg', 'jpeg', 'png'],
        accept_multiple_files=True,
        disabled=is_limit_reached()
    )
    
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
    
    if order_quantity <= 500:
        sample_size = min(order_quantity, 50)
    elif order_quantity <= 1200:
        sample_size = 80
    else:
        sample_size = 125
    
    st.info(f"📊 建议抽样数量：**{sample_size}** 件")

# 生成报告按钮
st.markdown("---")

if is_limit_reached():
    st.error(f"❌ 已达到使用次数限制（{get_inspection_limit()}次）")
    st.info("💡 请联系开发者增加次数")
else:
    remaining = get_remaining()
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
            # 增加次数
            user = st.session_state.get("user")
            if user:
                user["inspection_count"] += 1
            else:
                st.session_state["inspection_count"] += 1
            
            # 同步到数据库
            if user and supabase_ready:
                update_inspection_count(user["id"], user["inspection_count"])
            
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
                "savings": 350
            }
            
            # 保存到本地历史
            st.session_state["inspection_history"].append(report_data)
            st.session_state["total_savings"] += report_data["savings"]
            
            # 保存到数据库
            if user and supabase_ready:
                save_report(user["id"], report_data)
            
            st.success("✅ 报告生成完成！")
            
            # ===== 显示报告 =====
            st.markdown("---")
            st.header("📋 验货报告")
            
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
            
            st.markdown("---")
            st.subheader("3️⃣ 照片附件")
            if uploaded_files:
                photo_cols = st.columns(3)
                for idx, file in enumerate(uploaded_files):
                    with photo_cols[idx % 3]:
                        st.image(file, caption=file.name, use_column_width=True)
            
            # PDF导出
            st.markdown("---")
            st.subheader("📥 导出报告")
            font_available = check_font_available()
            
            col_pdf1, col_pdf2 = st.columns(2)
            with col_pdf1:
                if st.button("📄 预览报告（HTML）", use_container_width=True):
                    st.success("✅ 报告已生成！")
                    st.info("💡 使用浏览器打印功能保存为PDF：Ctrl+P 或 Cmd+P")
            
            with col_pdf2:
                try:
                    pdf_buffer = generate_inspection_pdf(report_data, uploaded_files)
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
            
            # ROI展示
            st.markdown("---")
            st.subheader("💰 本次验货价值")
            col_roi1, col_roi2, col_roi3 = st.columns(3)
            with col_roi1:
                st.metric("AI验货成本", "￥0（MVP免费）")
            with col_roi2:
                st.metric("节省人工成本", f"￥{report_data['savings']}")
            with col_roi3:
                st.metric("净节省", f"￥{report_data['savings']}")

# 页脚
st.markdown("---")
st.caption("💡 MVP版本 - 功能持续迭代中 | 有问题请联系开发者")

# ===== 历史记录 =====
if st.session_state["inspection_history"]:
    with st.sidebar:
        st.markdown("---")
        st.subheader("📜 验货历史")
        for idx, record in enumerate(st.session_state["inspection_history"][-5:]):
            st.text(f"{idx+1}. {record['product_name']}")
            st.caption(f"   {record['inspection_date']} | {record['conclusion']}")
