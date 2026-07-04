"""
auth_helper.py - 用户认证和IP追踪模块
支持：Supabase Auth（邮箱验证）+ IP 防滥用 + 临时邮箱屏蔽 + 导出次数控制
"""

import os
import streamlit as st
from datetime import datetime, timezone, timedelta
import re

# ===== 配置 =====

# 临时邮箱域名黑名单（常见临时邮箱服务）
TEMP_EMAIL_DOMAINS = {
    # 英文临时邮箱
    "tempmail.org", "tempmail.com", "temp-mail.org", "tempail.com",
    "mailinator.com", "guerrillamail.com", "10minutemail.com",
    "throwawaymail.com", "mailcatch.com", "maildrop.cc",
    "yopmail.com", "yopmail.fr", "cool.fr.nf",
    "getnada.com", "inboxbear.com", "fakemailgenerator.com",
    "emailondeck.com", "fakeinbox.com", "spamgourmet.com",
    # 中文临时邮箱
    "linshiyouxiang.com", "shoujiweishi.com", "51aw.com",
    "yuncha33.com", "mobilefish.com", "free-email.com",
    # 其他
    "trashmail.com", "dispostable.com", "mailnesia.com",
    "jetable.org", "mytemp.email", "tempemail.com",
    "tempmailaddress.com", "crazymailing.com", "emailtemporario.com.br",
}

# 正则表达式：匹配临时邮箱模式（如 example@123456.com）
TEMP_EMAIL_REGEX = re.compile(r'^[a-z0-9]+@[a-z0-9]{6,}\.(com|net|org)$')

# ===== Supabase 客户端 =====

@st.cache_resource
def get_supabase_client():
    """
    获取 Supabase 客户端（单例模式）
    """
    try:
        from supabase import create_client, Client
        
        supabase_url = st.secrets.get("supabase", {}).get("url")
        supabase_key = st.secrets.get("supabase", {}).get("key")
        
        if not supabase_url or not supabase_key:
            return None
        
        client: Client = create_client(supabase_url, supabase_key)
        return client
    except Exception as e:
        print(f"Supabase 客户端初始化失败: {e}")
        return None

def is_supabase_configured():
    """检查 Supabase 是否已配置"""
    return get_supabase_client() is not None

# ===== 临时邮箱检测 =====

def is_temp_email(email):
    """
    检测是否为临时邮箱
    返回: True 表示是临时邮箱，False 表示正常邮箱
    """
    if not email or '@' not in email:
        return False
    
    # 提取域名
    domain = email.lower().split('@')[-1]
    
    # 1. 检查域名黑名单
    if domain in TEMP_EMAIL_DOMAINS:
        return True
    
    # 2. 检查正则表达式（匹配随机字符串域名）
    if TEMP_EMAIL_REGEX.match(email.lower()):
        return True
    
    return False

# ===== IP 追踪（防滥用）=====

def get_ip_usage(client_ip):
    """
    获取指定 IP 的使用次数（从 Supabase 读取）
    返回: 使用次数（整数）
    """
    supabase = get_supabase_client()
    if not supabase:
        return 0
    
    try:
        result = supabase.table("ip_usage") \
            .select("usage_count") \
            .eq("ip", client_ip) \
            .execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0].get("usage_count", 0)
        return 0
    except Exception as e:
        print(f"读取 IP 使用次数失败: {e}")
        return 0

def increment_ip_usage(client_ip):
    """
    增加指定 IP 的使用次数（原子操作）
    如果 IP 不存在，则创建新记录
    """
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        # 查询是否存在
        result = supabase.table("ip_usage") \
            .select("usage_count") \
            .eq("ip", client_ip) \
            .execute()
        
        if result.data and len(result.data) > 0:
            # 存在：累加
            new_count = result.data[0].get("usage_count", 0) + 1
            supabase.table("ip_usage") \
                .update({"usage_count": new_count, "updated_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("ip", client_ip) \
                .execute()
        else:
            # 不存在：创建
            supabase.table("ip_usage") \
                .insert({
                    "ip": client_ip,
                    "usage_count": 1,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }) \
                .execute()
        
        return True
    except Exception as e:
        print(f"增加 IP 使用次数失败: {e}")
        return False

def decrement_ip_usage(client_ip):
    """
    减少指定 IP 的使用次数（回退用）
    """
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        result = supabase.table("ip_usage") \
            .select("usage_count") \
            .eq("ip", client_ip) \
            .execute()
        
        if result.data and len(result.data) > 0:
            current_count = result.data[0].get("usage_count", 0)
            new_count = max(0, current_count - 1)
            
            supabase.table("ip_usage") \
                .update({"usage_count": new_count, "updated_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("ip", client_ip) \
                .execute()
        
        return True
    except Exception as e:
        print(f"减少 IP 使用次数失败: {e}")
        return False

# ===== 用户认证 =====

def sign_up(email, password, display_name=None):
    """
    注册新用户
    返回: (success, message, user_data, needs_verification)
    """
    supabase = get_supabase_client()
    if not supabase:
        return False, "Supabase 未配置", None, False
    
    # 1. 检查是否为临时邮箱
    if is_temp_email(email):
        return False, "不支持临时邮箱注册，请使用真实邮箱（如 Gmail、QQ、163 等）", None, False
    
    try:
        # 2. 调用 Supabase Auth 注册
        result = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "display_name": display_name or email.split('@')[0]
                }
            }
        })
        
        if result.user:
            user_id = result.user.id
            
            # 3. 检查是否需要邮箱验证
            email_confirmed = result.user.email_confirmed_at is not None
            
            # 4. 创建用户配置文件（在 user_profiles 表中）
            try:
                supabase.table("user_profiles").insert({
                    "id": user_id,
                    "email": email,
                    "display_name": display_name or email.split('@')[0],
                    "inspection_count": 0,
                    "inspection_limit": 10,  # 注册用户 10 次
                    "export_count": 0,  # PDF 导出次数
                    "created_at": datetime.now(timezone.utc).isoformat()
                }).execute()
            except Exception as db_error:
                print(f"创建用户配置文件失败: {db_error}")
                # 继续执行，不要因为配置文件创建失败而中断注册
            
            user_data = {
                "id": user_id,
                "email": email,
                "display_name": display_name or email.split('@')[0],
                "inspection_count": 0,
                "inspection_limit": 10,
                "export_count": 0
            }
            
            if email_confirmed:
                # 邮箱已验证（管理后台手动验证过或关闭了确认邮件）
                return True, "注册成功！您现在可以开始免费使用了", user_data, False
            else:
                # 需要验证
                return True, "注册成功！请检查邮箱验证邮件（通常1-2分钟），点击邮件中的链接后就可以登录了", user_data, True
        else:
            return False, "注册失败：未知错误", None, False
    
    except Exception as e:
        error_msg = str(e)
        
        # 解析常见错误
        if "User already registered" in error_msg or "already exists" in error_msg:
            return False, "该邮箱已注册，请直接登录或重置密码", None, False
        elif "Password should be at least 6 characters" in error_msg:
            return False, "密码至少6位", None, False
        elif "Unable to validate email address" in error_msg:
            return False, "邮箱格式不正确", None, False
        elif "Error sending confirmation email" in error_msg:
            return False, "注册失败：发送验证邮件时出错，请稍后重试", None, False
        else:
            return False, f"注册失败：{error_msg}", None, False

def sign_in(email, password):
    """
    用户登录
    返回: (success, message, user_data, needs_verification)
    """
    supabase = get_supabase_client()
    if not supabase:
        return False, "Supabase 未配置", None, False
    
    try:
        # 1. 调用 Supabase Auth 登录
        result = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if result.user:
            user_id = result.user.id
            
            # 2. 检查邮箱是否已验证
            email_confirmed = result.user.email_confirmed_at is not None
            
            if not email_confirmed:
                return False, "邮箱尚未验证，请先完成邮箱验证（检查邮箱中的链接）", None, True
            
            # 3. 读取用户配置文件
            try:
                profile_result = supabase.table("user_profiles") \
                    .select("*") \
                    .eq("id", user_id) \
                    .execute()
                
                if profile_result.data and len(profile_result.data) > 0:
                    profile = profile_result.data[0]
                    user_data = {
                        "id": user_id,
                        "email": email,
                        "display_name": profile.get("display_name", email.split('@')[0]),
                        "inspection_count": profile.get("inspection_count", 0),
                        "inspection_limit": profile.get("inspection_limit", 10),
                        "export_count": profile.get("export_count", 0)
                    }
                else:
                    # 配置文件不存在：创建默认配置
                    supabase.table("user_profiles").insert({
                        "id": user_id,
                        "email": email,
                        "display_name": email.split('@')[0],
                        "inspection_count": 0,
                        "inspection_limit": 10,
                        "export_count": 0,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }).execute()
                    
                    user_data = {
                        "id": user_id,
                        "email": email,
                        "display_name": email.split('@')[0],
                        "inspection_count": 0,
                        "inspection_limit": 10,
                        "export_count": 0
                    }
                
                return True, "登录成功！", user_data, False
            
            except Exception as db_error:
                print(f"读取用户配置文件失败: {db_error}")
                # 降级：使用默认配置
                user_data = {
                    "id": user_id,
                    "email": email,
                    "display_name": email.split('@')[0],
                    "inspection_count": 0,
                    "inspection_limit": 10,
                    "export_count": 0
                }
                return True, "登录成功！（配置文件读取失败，使用默认配置）", user_data, False
        else:
            return False, "登录失败：未知错误", None, False
    
    except Exception as e:
        error_msg = str(e)
        
        if "Invalid login credentials" in error_msg:
            return False, "邮箱或密码错误", None, False
        elif "Email not confirmed" in error_msg:
            return False, "邮箱尚未验证，请先完成邮箱验证", None, True
        else:
            return False, f"登录失败：{error_msg}", None, False

def sign_out():
    """用户退出登录"""
    supabase = get_supabase_client()
    if supabase:
        try:
            supabase.auth.sign_out()
        except Exception as e:
            print(f"退出登录失败: {e}")

def resend_verification_email(email):
    """
    重发验证邮件
    返回: (success, message)
    """
    supabase = get_supabase_client()
    if not supabase:
        return False, "Supabase 未配置"
    
    try:
        supabase.auth.resend({
            "type": "signup",
            "email": email
        })
        return True, "验证邮件已重新发送，请检查邮箱（包括垃圾邮件文件夹）"
    except Exception as e:
        return False, f"重发验证邮件失败：{str(e)}"

def check_email_verified(user_id):
    """
    检查用户邮箱是否已验证
    返回: True 表示已验证，False 表示未验证
    """
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        # 获取用户信息
        user = supabase.auth.admin.get_user_by_id(user_id)
        if user and user.user:
            return user.user.email_confirmed_at is not None
        return False
    except Exception as e:
        print(f"检查邮箱验证状态失败: {e}")
        return False

# ===== 用户数据管理 =====

def update_inspection_count(user_id, new_count):
    """
    更新用户的使用次数
    返回: True 表示成功，False 表示失败
    """
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        supabase.table("user_profiles") \
            .update({"inspection_count": new_count}) \
            .eq("id", user_id) \
            .execute()
        return True
    except Exception as e:
        print(f"更新使用次数失败: {e}")
        return False

def update_export_count(user_id, new_count):
    """
    更新用户的 PDF 导出次数
    返回: True 表示成功，False 表示失败
    """
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        supabase.table("user_profiles") \
            .update({"export_count": new_count}) \
            .eq("id", user_id) \
            .execute()
        return True
    except Exception as e:
        print(f"更新导出次数失败: {e}")
        return False

def save_report(user_id, report_data):
    """
    保存验货报告到数据库
    返回: True 表示成功，False 表示失败
    """
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        supabase.table("inspection_reports").insert({
            "user_id": user_id,
            "report_id": report_data.get("report_id"),
            "product_name": report_data.get("product_name"),
            "inspection_date": report_data.get("inspection_date"),
            "inspection_standard": report_data.get("inspection_standard"),
            "order_quantity": report_data.get("order_quantity"),
            "sample_size": report_data.get("sample_size"),
            "conclusion": report_data.get("conclusion"),
            "defects": report_data.get("defects", []),
            "recommendation": report_data.get("recommendation"),
            "confidence": report_data.get("confidence", 0.5),
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        return True
    except Exception as e:
        print(f"保存报告失败: {e}")
        return False

def get_reports(user_id, limit=20):
    """
    获取用户的验货报告列表
    返回: 报告列表（按创建时间倒序）
    """
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        result = supabase.table("inspection_reports") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        
        return result.data if result.data else []
    except Exception as e:
        print(f"获取报告列表失败: {e}")
        return []

def get_user_count():
    """
    获取注册用户总数（用于管理后台）
    返回: 用户总数
    """
    supabase = get_supabase_client()
    if not supabase:
        return 0
    
    try:
        result = supabase.table("user_profiles") \
            .select("id", count="exact") \
            .execute()
        
        return result.count if result.count else 0
    except Exception as e:
        print(f"获取用户总数失败: {e}")
        return 0

# ===== 工具函数 =====

def get_user_profile(user_id):
    """
    获取用户配置文件
    返回: 用户配置文件字典，或 None
    """
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        result = supabase.table("user_profiles") \
            .select("*") \
            .eq("id", user_id) \
            .execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        print(f"获取用户配置文件失败: {e}")
        return None

def is_admin(email):
    """
    检查是否为管理员邮箱
    返回: True 表示是管理员，False 表示不是
    """
    admin_emails = st.secrets.get("admin", {}).get("emails", [])
    return email in admin_emails

# ===== 初始化数据库表（首次使用时）=====

def init_database():
    """
    初始化数据库表（如果不存在）
    注意：此函数需要在 Supabase SQL Editor 中手动执行
    这里只是提供 SQL 语句供参考
    """
    sql_statements = [
        # 1. 创建 user_profiles 表
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            id UUID REFERENCES auth.users(id) PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            display_name TEXT,
            inspection_count INTEGER DEFAULT 0,
            inspection_limit INTEGER DEFAULT 10,
            export_count INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        
        # 2. 创建 inspection_reports 表
        """
        CREATE TABLE IF NOT EXISTS inspection_reports (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID REFERENCES auth.users(id),
            report_id TEXT UNIQUE NOT NULL,
            product_name TEXT,
            inspection_date TEXT,
            inspection_standard TEXT,
            order_quantity INTEGER,
            sample_size INTEGER,
            conclusion TEXT,
            defects JSONB,
            recommendation TEXT,
            confidence FLOAT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        
        # 3. 创建 ip_usage 表
        """
        CREATE TABLE IF NOT EXISTS ip_usage (
            ip TEXT PRIMARY KEY,
            usage_count INTEGER DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        
        # 4. 启用行级安全（RLS）
        """
        ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE inspection_reports ENABLE ROW LEVEL SECURITY;
        
        CREATE POLICY "Users can view own profile" ON user_profiles
            FOR SELECT USING (auth.uid() = id);
        
        CREATE POLICY "Users can update own profile" ON user_profiles
            FOR UPDATE USING (auth.uid() = id);
        
        CREATE POLICY "Users can view own reports" ON inspection_reports
            FOR SELECT USING (auth.uid() = user_id);
        
        CREATE POLICY "Users can insert own reports" ON inspection_reports
            FOR INSERT WITH (auth.uid() = user_id);
        """
    ]
    
    return sql_statements

# ===== 主程序入口（测试用）=====

if __name__ == "__main__":
    # 测试 Supabase 连接
    print("测试 Supabase 连接...")
    supabase = get_supabase_client()
    if supabase:
        print("✓ Supabase 客户端初始化成功")
        print(f"  URL: {st.secrets.get('supabase', {}).get('url')}")
    else:
        print("✗ Supabase 客户端初始化失败")
    
    # 测试临时邮箱检测
    print("\n测试临时邮箱检测...")
    test_emails = [
        "test@gmail.com",
        "user@tempmail.org",
        "admin@qq.com",
        "fake@yopmail.com"
    ]
    for email in test_emails:
        result = is_temp_email(email)
        print(f"  {email}: {'临时邮箱' if result else '正常邮箱'}")
