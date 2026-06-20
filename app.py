import streamlit as st
from PIL import Image, ImageStat
import io
import numpy as np
import os
from datetime import datetime, timezone, timedelta
import base64
from io import BytesIO
import openai
import json
import base64
import httpx
import re

def clean_json_string(s):
    """清理 JSON 字符串中的常见格式问题"""
    if not s:
        return s
    # 1. 移除末尾逗号（在 } 或 ] 之前）
    s = re.sub(r',\s*([}\]])', r'\1', s)
    # 2. 移除单引号包裹的字符串值（JSON 要求双引号）
    # 这是一个保守的修复，只处理明显的单引号问题
    s = re.sub(r"(?<=:)\s*'([^']*)'", r'"\1"', s)
    return s

def extract_balanced_json(text):
    """
    使用括号平衡算法从文本中提取完整的 JSON 对象
    能正确处理嵌套括号和字符串中的转义字符
    """
    start_idx = text.find('{')
    if start_idx == -1:
        return None
    
    depth = 0
    in_string = False
    escape_next = False
    
    for i in range(start_idx, len(text)):
        ch = text[i]
        
        if escape_next:
            escape_next = False
            continue
        
        if ch == '\\':
            escape_next = True
            continue
        
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        
        if not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start_idx:i+1]
    
    return None

def extract_json_robust(text):
    """
    从 AI 响应中鲁棒地提取并解析 JSON
    
    返回: (success, result_or_error_message)
    """
    if not text or not text.strip():
        return False, "AI 返回了空内容"
    
    raw_response = text
    
    # ===== 策略1: 直接解析 =====
    try:
        result = json.loads(text)
        return True, result
    except json.JSONDecodeError:
        pass
    
    # ===== 策略2: 提取 markdown 代码块 =====
    patterns = [
        r'```json\s*\n?(.*?)\n?\s*```',
        r'```\s*\n?(.*?)\n?\s*```',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            block_content = match.group(1).strip()
            try:
                result = json.loads(block_content)
                return True, result
            except json.JSONDecodeError:
                # 尝试清理后解析
                cleaned = clean_json_string(block_content)
                try:
                    result = json.loads(cleaned)
                    return True, result
                except json.JSONDecodeError:
                    pass   
    # ===== 策略3: 括号平衡提取 =====
    json_str = extract_balanced_json(text)
    if json_str:
        try:
            result = json.loads(json_str)
            return True, result
        except json.JSONDecodeError:
            cleaned = clean_json_string(json_str)
            try:
                result = json.loads(cleaned)
                return True, result
            except json.JSONDecodeError as e:
                return False, f"JSON 解析失败：{str(e)}\n提取内容：{json_str[:200]}"    
    # ===== 所有策略都失败 =====
    return False, f"无法解析 AI 返回的 JSON。原始响应前 200 字符：\n{raw_response[:200]}"
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
# ===== 配置 =====
MAX_FILE_SIZE_MB = 5  # 单个图片最大 5MB
MAX_FILES = 10       # 最多上传 10 张图片
API_TIMEOUT_SECONDS = 60  # API 调用超时时间
# ===== 配置API客户端 =====
# 优先级：通义千问VL > DeepSeek > OpenAI
def get_ai_client():
    """
    获取AI客户端（通义千问/DeepSeek/OpenAI）
    返回: (client, model_name) 或 (None, error_message)
    """
    try:
        # 1. 优先使用通义千问VL（支持视觉，便宜）
        qwen_key = st.secrets.get("qwen", {}).get("api_key")
        if qwen_key:
            client = openai.OpenAI(
                api_key=qwen_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                timeout=httpx.Timeout(API_TIMEOUT_SECONDS, connect=10.0)
            )
            return client, "qwen-vl-plus"        
        # 2. 降级到DeepSeek（便宜，仅文本）
        deepseek_key = st.secrets.get("deepseek", {}).get("api_key")
        if deepseek_key:
            client = openai.OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com",
                timeout=httpx.Timeout(API_TIMEOUT_SECONDS, connect=10.0)
            )
            return client, "deepseek-chat"        
        # 3. 降级到OpenAI（贵，但稳定）
        openai_key = st.secrets.get("openai", {}).get("api_key", os.getenv("OPENAI_API_KEY"))
        if openai_key:
            client = openai.OpenAI(
                api_key=openai_key,
                timeout=httpx.Timeout(API_TIMEOUT_SECONDS, connect=10.0)
            )
            return client, "gpt-4o"        
        # 未配置任何 API Key
        return None, "未配置API Key，请在 Streamlit Cloud Secrets 中配置 qwen/deepseek/openai 的 api_key"    
    except Exception as e:
        return None, f"API客户端初始化失败：{str(e)}"
def check_api_available():
    """检查 API 是否可用，返回 (is_available, error_message)"""
    client, result = get_ai_client()
    if client:
        return True, None
    else:
        return False, result
# ===== 图片校验函数 =====
def validate_uploaded_file(uploaded_file):
    """
    校验上传的图片文件
    返回: (is_valid, error_message)
    """
    # 检查文件类型
    if uploaded_file.type not in ["image/jpeg", "image/jpg", "image/png"]:
        return False, f"不支持的文件格式：{uploaded_file.name}（仅支持 JPG/PNG）"
    
    # 检查文件大小
    file_size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        return False, f"文件过大：{uploaded_file.name}（{file_size_mb:.1f}MB > {MAX_FILE_SIZE_MB}MB）"    
    return True, None
def check_image_quality(uploaded_file):
    """
    检查图片质量：尺寸、模糊度、亮度
    返回: (quality_score, warnings)
    quality_score: 0-100
    warnings: 字符串列表
    """
    warnings = []
    score = 100
    img = None
    
    try:
        image_bytes = uploaded_file.getvalue()
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()  # 验证图片格式
        img = Image.open(io.BytesIO(image_bytes))  # verify 后需要重新打开
    except Exception as e:
        return 0, [f"无法读取图片：{str(e)}"]
    
    width, height = img.size
    
    # 1. 尺寸检查
    min_size = min(width, height)
    if min_size < 800:
        warnings.append(f"图片尺寸较小（{width}x{height}），建议至少 800x800 像素")
        score -= 15
    elif min_size < 1200:
        warnings.append(f"图片清晰度一般（{width}x{height}），建议拍摄更清晰的图片")
        score -= 5
    
    # 2. 亮度检查
    grayscale = img.convert("L")
    stat = ImageStat.Stat(grayscale)
    brightness = stat.mean[0]
    
    if brightness < 50:
        warnings.append("图片太暗，可能导致缺陷识别失败")
        score -= 20
    elif brightness > 240:
        warnings.append("图片过曝，细节可能丢失")
        score -= 10
    
    # 3. 模糊检测（需要 numpy）
    try:
        gray_array = np.array(grayscale)
        # 拉普拉斯方差
        laplacian_var = np.var(
            np.array([
                gray_array[2:, 1:-1] + gray_array[:-2, 1:-1] + gray_array[1:-1, 2:] + gray_array[1:-1, :-2]
                - 4 * gray_array[1:-1, 1:-1]
            ]).flatten()
        )
        
        if laplacian_var < 50:
            warnings.append("图片模糊，建议重新对焦拍摄")
            score -= 25
        elif laplacian_var < 100:
            warnings.append("图片 slightly 模糊，建议拍摄更清楚")
            score -= 10
    except Exception:
        pass  # 模糊检测失败不影响主流程
    
    # 4. 宽高比检查
    ratio = max(width, height) / min(width, height)
    if ratio > 3:
        warnings.append("图片过于细长，建议拍摄更接近正方形的角度")
        score -= 5
    return max(0, score), warnings
# ===== AI分析函数 =====
def analyze_product_images(uploaded_files, product_name, inspection_standard):
    """
    调用 AI Vision API 分析产品图片
    返回: (success, result_or_error_message)
    """
    # 1. 检查 API 可用性
    api_available, api_error = check_api_available()
    if not api_available:
        return False, f"API 不可用：{api_error}"
    
    # 2. 校验输入
    if not uploaded_files:
        return False, "请至少上传1张产品照片"
    if not product_name or not product_name.strip():
        return False, "请填写产品名称"
    
    try:
        client, model_name = get_ai_client()
        
        # 3. 构建消息
        messages = [
            {
"role": "system",
"content": """你是一位拥有15年经验的外贸验货专家，精通ISO 2859-1/2抽样标准、AQL 2.5/4.0质量标准，熟悉电子产品、纺织品、机械配件、玩具等各类产品的国际质量标准（ISO、ASTM、GB、EN等）。
你的任务是根据用户上传的产品图片，进行专业的质量检验分析。

用户上传了多张图片，按顺序编号为：图1、图2、图3...。
在描述缺陷时，请用"图1"、"图2"这样的编号指明缺陷出现在哪张图片中。
【输出要求】必须严格按以下JSON格式返回，不要添加任何其他文字：
{
  "conclusion": "合格/不合格/有条件接受",
  "defects": [
    {
      "type": "划痕/变形/色差/功能异常/包装破损等",
      "quantity": 数字（必须是整数，如3，不能写"若干"或"少量"）,
      "severity": "严重/中等/轻微",
      "description": "详细描述缺陷位置、大小、程度（50字以内）",
      "image": "图1 / 图2 / 图3"（缺陷出现在哪张图片，用编号表示；不确定则写"未明确"）
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
[注意] quantity字段必须是整数数字，禁止使用"若干"、"一些"、"多个"等模糊词汇
[注意] 请确保输出标准 JSON 格式，不要使用尾逗号，字符串使用双引号
[注意] 如果图片不清晰，description中注明"图片模糊，无法准确判断"
[注意] 不要编造图片中不存在的缺陷
[注意] 如果未发现缺陷，defects数组设为空 []
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
        
        # 4. 添加图片
        for uploaded_file in uploaded_files:
            # 图片按上传顺序编号，AI 在分析时引用 "图1/图2/图3" 对应缺陷
            try:
                image_bytes = uploaded_file.getvalue()
                image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                
                messages[1]["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}"
                    }
                })
            except Exception as img_error:
                return False, f"图片处理失败：{uploaded_file.name} - {str(img_error)}"
        
        # 5. 调用 API
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=1000,
                temperature=0.3
            )
        except openai.APIConnectionError:
            return False, "网络连接失败，请检查网络后重试"
        except openai.APITimeoutError:
            return False, f"API 调用超时（{API_TIMEOUT_SECONDS}秒），请稍后重试"
        except openai.RateLimitError:
            return False, "API 调用频率超限，请等待1分钟后重试"
        except openai.AuthenticationError:
            return False, "API Key 认证失败，请检查密钥是否正确"
        except openai.APIStatusError as e:
            return False, f"API 错误：{e.message}（状态码：{e.status_code}）"
        
        # 6. 解析响应（使用增强版解析器）
        ai_response = response.choices[0].message.content
        
        # 使用增强版 JSON 解析（支持多层 fallback）
        success, result = extract_json_robust(ai_response)
        
        if not success:
            return False, result
        
        # 7. 解析 JSON（支持 markdown 代码块包裹）
        try:
            result = json.loads(ai_response)
        except json.JSONDecodeError:
            # 尝试提取 ```json ... ``` 中的内容
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', ai_response, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    # 最后尝试提取第一个 {...} 块
                    json_match2 = re.search(r'\{.*\}', ai_response, re.DOTALL)
                    if json_match2:
                        result = json.loads(json_match2.group())
                    else:
                        return False, f"AI 返回格式错误，无法解析 JSON。原始响应：{ai_response[:200]}..."
            else:
                # 尝试直接提取 {...}
                json_match3 = re.search(r'\{.*\}', ai_response, re.DOTALL)
                if json_match3:
                    try:
                        result = json.loads(json_match3.group())
                    except json.JSONDecodeError:
                        return False, f"AI 返回格式错误，无法解析 JSON。原始响应：{ai_response[:200]}..."
                else:
                    return False, f"AI 返回格式错误，未找到 JSON 内容。原始响应：{ai_response[:200]}..."
        
        # 8. 校验必需字段
        required_fields = ["conclusion", "defects", "recommendation"]
        for field in required_fields:
            if field not in result:
                return False, f"AI 返回数据缺少必需字段：{field}"
        
        # 9. 校验 defects 格式
        if not isinstance(result["defects"], list):
            return False, "AI 返回的 defects 字段格式错误（应为数组）"
        
        for idx, defect in enumerate(result["defects"]):
            if not isinstance(defect, dict):
                return False, f"缺陷 #{idx+1} 格式错误"
            # 填充缺失字段
            defect.setdefault("type", "未知")
            defect.setdefault("quantity", 0)
            defect.setdefault("severity", "未知")
            defect.setdefault("description", "")
            defect.setdefault("image", "")
        
        # 10. 填充其他可选字段
        result.setdefault("confidence", 0.5)
        
        return True, result
    
    except Exception as e:
        return False, f"AI 分析过程发生未知错误：{str(e)}"
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
    st.subheader("用户登录")
    
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
    if st.button("免登录体验", use_container_width=True):
        st.session_state["skip_login"] = True
        st.rerun()
def show_user_info():
    """显示已登录用户信息"""
    user = st.session_state.get("user")
    if user:
        st.success(f"{user.get('display_name', user['email'])}")
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
if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = None
if "analysis_error" not in st.session_state:
    st.session_state["analysis_error"] = None
if "last_raw_ai_response" not in st.session_state:
    st.session_state["last_raw_ai_response"] = None
supabase_ready = is_supabase_configured()
# ===== 处理未登录状态 =====
if not st.session_state["user"] and not st.session_state["skip_login"]:
    # 未登录：显示登录/注册页面
    st.title("外贸验货AI Agent - MVP")
    st.markdown("---")
    col_auth1, col_auth2 = st.columns([1, 1])    
    with col_auth1:
        show_auth_ui()    
    with col_auth2:
        st.subheader("关于本应用")
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
        st.caption(f"版本：0.3.2 (MVP) | Supabase状态：{'已连接' if supabase_ready else '未配置（次数不持久化）'}")  
        st.stop()
# ===== 已登录：显示主应用 =====
# 标题
st.title("外贸验货AI Agent - MVP")
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
    st.subheader("使用统计")
    st.metric("已使用次数", f"{get_inspection_count()} 次")
    st.metric("剩余次数", f"{remaining} 次")
    
    if remaining <= 2:
        st.warning(f"剩余次数不多")
    
    st.caption(f"每用户 {get_inspection_limit()} 次")
    st.markdown("---")
    
    # ROI展示
    if st.session_state["inspection_history"]:
        st.subheader("您的节省统计")
        st.metric("累计验货次数", f"{len(st.session_state['inspection_history'])} 次")
        st.metric("累计节省金额", f"￥{st.session_state['total_savings']:,.0f}")
        st.caption("每次AI验货约节省￥200-500人工成本")
        st.markdown("---")
    
    # 退出登录
    if st.button("退出登录"):
        sign_out()
        st.session_state["user"] = None
        st.session_state["skip_login"] = False
        st.session_state["inspection_history"] = []
        st.session_state["total_savings"] = 0
        st.rerun()
    
    st.markdown("---")
    st.caption(f"版本：0.3.2 (MVP)")
    st.caption(f"更新时间：2026-06-18")

# 主界面
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. 上传产品照片")
    
    # 检查 API 可用性
    api_available, api_error = check_api_available()
    if not api_available:
        st.error(f"API 不可用：{api_error}")
        st.info("请联系管理员配置 API Key")
        uploaded_files = None
    else:
        with st.expander("拍照指南（点击展开）", expanded=True):
            col_guide1, col_guide2 = st.columns(2)
            
            with col_guide1:
                st.markdown("**正确示范**")
                correct_img_path = os.path.join(os.path.dirname(__file__), "example_images", "correct.jpg")
                if os.path.exists(correct_img_path):
                    st.image(correct_img_path, caption="光线充足、45°角、清晰", use_column_width=True)
                else:
                    st.info("光线充足\n45°角拍摄\n缺陷细节清晰")
            
            with col_guide2:
                st.markdown("**错误示范**")
                wrong_img_path = os.path.join(os.path.dirname(__file__), "example_images", "wrong.jpg")
                if os.path.exists(wrong_img_path):
                    st.image(wrong_img_path, caption="光线暗、距离远、模糊", use_column_width=True)
                else:
                    st.error("光线太暗\n距离太远\n模糊不清")
            
            st.markdown("---")
            st.markdown(f"""
            **必须拍摄的照片类型：**
            1. **整体图** — 产品完整外观，至少1张
            2. **细节图** — 缺陷或关键部位特写
            3. **标签/包装图** — 产品标签、包装、条码        
            **建议：**
            - 光线充足，不要逆光
            - 每张图只聚焦1个产品/1个缺陷
            - 单张图片不超过 {MAX_FILE_SIZE_MB}MB
            """)
            st.markdown("""
            **上传建议：**
            - 按顺序上传：整体外观 → 缺陷细节 → 标签/包装
            - 建议上传 3-6 张不同角度的照片
            - 上传后可删除不需要的照片
            """)

        uploaded_files = st.file_uploader(
            f"选择产品照片（最多{MAX_FILES}张，每张≤{MAX_FILE_SIZE_MB}MB）",
            type=['jpg', 'jpeg', 'png'],
            accept_multiple_files=True,
            disabled=is_limit_reached()
        )
        
    # 文件校验
    if uploaded_files:
        if len(uploaded_files) > MAX_FILES:
            st.error(f"上传图片数量超限：{len(uploaded_files)} 张 > {MAX_FILES} 张")
            uploaded_files = None
        else:
            valid_files = []
            quality_issues = []
            has_error = False
        
        for file in uploaded_files:
            # 基础校验（格式、大小）
            is_valid, error_msg = validate_uploaded_file(file)
            if not is_valid:
                st.error(error_msg)
                has_error = True
                continue
            
            # 质量检查
            quality_score, warnings = check_image_quality(file)
            if quality_score < 60:
                # 质量太差，直接拒绝
                quality_issues.append(f"#{file.name} 质量评分 {quality_score} 分，建议重新拍摄")
                has_error = True
                continue
            elif warnings:
                quality_issues.append(f"#{file.name}：{'；'.join(warnings)}")
            
            valid_files.append(file)
        
        if quality_issues:
            st.warning("**图片质量提醒：**\n" + "\n".join(f"- {issue}" for issue in quality_issues))
        
        if has_error and not valid_files:
            uploaded_files = None
        elif has_error and valid_files:
            st.warning(f"部分图片被过滤，剩余 {len(valid_files)} 张有效图片")
            uploaded_files = valid_files
        else:
            uploaded_files = valid_files
        
        if uploaded_files:
            st.success(f"已通过质量检测 {len(uploaded_files)} 张照片")
            cols = st.columns(min(3, len(uploaded_files)))
            for idx, file in enumerate(uploaded_files):
                quality_score, warnings = check_image_quality(file)
                with cols[idx % 3]:
                    try:
                        caption = f"#{idx+1} {file.name}"
                        if warnings:
                            caption += f"\\n⚠️ {warnings[0]}"
                        st.image(file, caption=caption, use_column_width=True)
                        # 质量进度条
                        st.progress(quality_score / 100, text=f"质量评分：{quality_score}")
                    except Exception as img_error:
                        st.warning(f"[图片加载失败: {file.name}]")
    # 删除按钮区域
    st.markdown("**管理已上传图片**")
if uploaded_files and len(uploaded_files) > 0:
    del_cols = st.columns(min(5, len(uploaded_files)))
    for idx, (col, file) in enumerate(zip(del_cols, uploaded_files)):
    for idx in range(len(uploaded_files)):
        with del_cols[idx % 5]:
            if st.button(f"删除 #{idx+1}", key=f"del_{idx}"):
                files_to_remove.append(idx)
    
   if files_to_remove:
        uploaded_files = [f for i, f in enumerate(uploaded_files) if i not in files_to_remove]
        st.rerun()

with col2:
    st.subheader("2. 填写基本信息")
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
    
    st.info(f"建议抽样数量：**{sample_size}** 件")

# 生成报告按钮
st.markdown("---")

if is_limit_reached():
    st.error(f"已达到使用次数限制（{get_inspection_limit()}次）")
    st.info("请联系开发者增加次数")
else:
    remaining = get_remaining()
    st.info(f"您还有 **{remaining}** 次免费使用次数")

col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    # 按钮禁用条件
    button_disabled = is_limit_reached() or not (uploaded_files and product_name and product_name.strip())
    
    if st.button(
        "生成验货报告",
        use_container_width=True,
        type="primary",
        disabled=button_disabled
    ):
        # 前置校验
        if not uploaded_files:
            st.error("请至少上传1张产品照片")
        elif not product_name or not product_name.strip():
            st.error("请填写产品名称")
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
            with st.spinner(f"AI正在分析图片（最多等待{API_TIMEOUT_SECONDS}秒）..."):
                success, result = analyze_product_images(
                    uploaded_files, 
                    product_name.strip(), 
                    inspection_standard
                )         
            if not success:
                # 分析失败 - 回退次数
                if user:
                    user["inspection_count"] -= 1
                else:
                    st.session_state["inspection_count"] -= 1
                
                if user and supabase_ready:
                    update_inspection_count(user["id"], user["inspection_count"])
                
                st.session_state["analysis_error"] = result
                st.session_state["analysis_result"] = None
                st.rerun()            
            # 分析成功
            st.session_state["analysis_result"] = result
            st.session_state["analysis_error"] = None
            st.rerun()
# ===== 显示分析错误 =====
if st.session_state.get("analysis_error"):
    st.markdown("---")
    st.error(f"AI 分析失败：{st.session_state['analysis_error']}")
    col_retry1, col_retry2, col_retry3 = st.columns([1, 1, 1])
    with col_retry2:
        if st.button("重试", type="primary", use_container_width=True):
            st.session_state["analysis_error"] = None
            st.rerun()
    st.info("请检查：\n1. 图片是否清晰\n2. 网络是否正常\n3. 如持续失败，请联系管理员")

# ===== 显示报告 =====
if st.session_state.get("analysis_result"):
    ai_result = st.session_state["analysis_result"]
    
    # 生成报告数据
    report_data = {
        "report_id": f"RPT-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "product_name": product_name,
        "inspection_date": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
        "inspection_standard": inspection_standard,
        "order_quantity": order_quantity,
        "sample_size": sample_size,
        "conclusion": ai_result.get("conclusion", "分析结果未知"),
        "defects": ai_result.get("defects", []),
        "recommendation": ai_result.get("recommendation", "暂无建议"),
        "confidence": ai_result.get("confidence", 0.5),
        "savings": 350
    }
    
    # 保存到本地历史
    st.session_state["inspection_history"].append(report_data)
    st.session_state["total_savings"] += report_data["savings"]
    
    # 保存到数据库
    user = st.session_state.get("user")
    if user and supabase_ready:
        save_report(user["id"], report_data)   
    st.success("报告生成完成！")    
    # ===== 显示报告 =====
    st.markdown("---")
    # 报告头部 - 专业化格式
    report_header_cols = st.columns([2, 1])
    with report_header_cols[0]:
        st.header("验货报告")
        st.caption(f"报告编号：{report_data['report_id']}")
    with report_header_cols[1]:
        st.markdown(f"""
        **委托方：** {st.session_state.get('user', {}).get('email', '免费体验用户')} 
        
        **检验标准：** {report_data.get('inspection_standard', 'AQL 2.5')}        
        
        **订单数量：** {report_data.get('order_quantity', 500)} 件        
        
        **抽样数量：** {report_data['sample_size']} 件
        """)
        
    st.divider()
    st.header("验货报告") 
    st.subheader("1. 验货结论")
    col_con1, col_con2, col_con3 = st.columns(3)
    with col_con1:
        st.metric("验货编号", report_data["report_id"])
    with col_con2:
        st.metric("验货日期", report_data["inspection_date"])
    with col_con3:
        st.metric("抽样数量", f"{report_data['sample_size']} 件")    
    # 结论颜色标识
    conclusion = report_data['conclusion']
    if "合格" in conclusion and "有条件" not in conclusion:
        st.success(f"### {conclusion}")
    elif "不合格" in conclusion:
        st.error(f"### {conclusion}")
    else:
        st.warning(f"### {conclusion}")
    
    st.info(f"**建议：** {report_data['recommendation']}")    
    # 置信度
    confidence = report_data.get('confidence', 0.5)
    if confidence >= 0.8:
        st.caption(f"置信度：{confidence:.0%}（高）")
    elif confidence >= 0.5:
        st.caption(f"置信度：{confidence:.0%}（中）")
    else:
        st.caption(f"置信度：{confidence:.0%}（低）")
    
    st.markdown("---")
    st.subheader("2. 缺陷清单")
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
        st.info("未发现明显缺陷")
    
    st.markdown("---")
        # 缺陷统计摘要
    if report_data["defects"]:
        defects = report_data["defects"]
        severity_counts = {"严重": 0, "中等": 0, "轻微": 0}
        for d in defects:
            sev = d.get("severity", "轻微")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        stat_cols = st.columns(3)
        with stat_cols[0]:
            st.metric("严重缺陷", severity_counts.get("严重", 0))
        with stat_cols[1]:
            st.metric("中等缺陷", severity_counts.get("中等", 0))
        with stat_cols[2]:
            st.metric("轻微缺陷", severity_counts.get("轻微", 0))
        
        # 通过率计算
        if report_data.get("sample_size", 0) > 0:
            total_defects = sum(d.get("quantity", 1) for d in defects)
            pass_rate = max(0, (report_data["sample_size"] - total_defects) / report_data["sample_size"] * 100)
            st.progress(pass_rate / 100, text=f"估算通过率：{pass_rate:.1f}%")

    st.subheader("3. 照片附件")
    if uploaded_files:
        photo_cols = st.columns(3)
        for idx, file in enumerate(uploaded_files):
            with photo_cols[idx % 3]:
                try:
                    st.image(file, caption=file.name, use_column_width=True)
                except Exception:
                    st.warning(f"[图片加载失败: {file.name}]")
    
    # PDF导出
    st.markdown("---")
    st.subheader("导出报告")
    font_available = check_font_available()
    
    col_pdf1, col_pdf2 = st.columns(2)
    with col_pdf1:
        if st.button("预览报告（HTML）", use_container_width=True):
            st.success("报告已生成！")
            st.info("使用浏览器打印功能保存为PDF：Ctrl+P 或 Cmd+P")
    
    with col_pdf2:
        try:
            pdf_buffer = generate_inspection_pdf(report_data, uploaded_files)
            conclusion_tag = "合格" if "合格" in report_data['conclusion'] else "不合格"
            pdf_filename = f"验货报告_{conclusion_tag}_{report_data['product_name']}_{report_data['report_id'][:8]}.pdf"
            st.download_button(
                label="下载PDF报告",
                data=pdf_buffer,
                file_name=pdf_filename,
                mime="application/pdf",
                use_container_width=True,
                key="download_pdf"
            )
            if not font_available:
                st.warning("未检测到中文字体，PDF可能显示为英文。请联系管理员添加字体文件。")
        except Exception as e:
            st.error(f"PDF生成失败：{str(e)}")
            st.info("临时方案：使用浏览器打印功能（Ctrl+P）保存为PDF")
    
    # ROI展示
    st.markdown("---")
    st.subheader("本次验货价值")
    col_roi1, col_roi2, col_roi3 = st.columns(3)
    with col_roi1:
        st.metric("AI验货成本", "￥0（MVP免费）")
    with col_roi2:
        st.metric("节省人工成本", f"￥{report_data['savings']}")
    with col_roi3:
        st.metric("净节省", f"￥{report_data['savings']}")
    
    # 新建报告按钮
    st.markdown("---")
    col_new1, col_new2, col_new3 = st.columns([1, 1, 1])
    with col_new2:
        if st.button("新建验货报告", use_container_width=True):
            st.session_state["analysis_result"] = None
            st.session_state["analysis_error"] = None
            st.rerun()

# 页脚
st.markdown("---")
st.caption("MVP版本 - 功能持续迭代中 | 有问题请联系开发者")

# ===== 历史记录 =====
if st.session_state["inspection_history"]:
    with st.sidebar:
        st.markdown("---")
        st.subheader("验货历史")
        
        # 历史总数
        total = len(st.session_state["inspection_history"])
        st.caption(f"共 {total} 条记录")
        
        for idx, record in enumerate(reversed(st.session_state["inspection_history"])):
            with st.expander(f"#{total-idx} {record['product_name']} - {record['inspection_date'][:10]}", expanded=False):
                col_h1, col_h2 = st.columns(2)
                with col_h1:
                    conclusion = record.get("conclusion", "未知")
                    if "合格" in conclusion and "有条件" not in conclusion:
                        st.success(conclusion[:20])
                    elif "不合格" in conclusion:
                        st.error(conclusion[:20])
                    else:
                        st.warning(conclusion[:20])
                with col_h2:
                    defect_count = len(record.get("defects", []))
                    st.metric("缺陷数", f"{defect_count}")
                
                st.write(f"**建议：** {record.get('recommendation', '暂无')}")
                
                # 删除按钮
                if st.button("删除此记录", key=f"del_history_{idx}"):
                    st.session_state["inspection_history"].pop(total - 1 - idx)
                    st.rerun()
