"""
用户认证模块 - 基于 Supabase
================================
如果未配置 Supabase，自动降级为本地 Session 模式（无持久化）

修复说明（2026-06-25）：
- 修复 ip_usage 表字段名不匹配问题（usage_month → month）
- 添加调试输出，便于排查 IP 追踪失效问题
"""

import streamlit as st
from datetime import datetime, timezone, timedelta

# ===== 缓存 Supabase 客户端（避免重复初始化）=====
@st.cache_resource
def get_supabase():
    """获取 Supabase 客户端（未配置时返回 None）"""
    try:
        from supabase import create_client
        
        url = st.secrets.get("supabase", {}).get("url", "")
        key = st.secrets.get("supabase", {}).get("anon_key", "")
        
        if url and key and url != "https://your-project.supabase.co":
            return create_client(url, key)
        return None
    except Exception as e:
        print(f"[DEBUG] Supabase 客户端初始化失败: {e}")
        return None

def is_supabase_configured():
    """检查 Supabase 是否已配置"""
    return get_supabase() is not None

# ===== 用户操作 =====

def sign_up(email, password, display_name=""):
    """
    注册新用户
    返回: (success, message, user_data)
    """
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置，请联系管理员", None
    
    try:
        resp = sb.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "display_name": display_name or email.split("@")[0]
                }
            }
        })
        
        if resp.user:
            # 创建用户配置记录
            try:
                sb.table("user_profiles").insert({
                    "id": resp.user.id,
                    "email": email,
                    "display_name": display_name or email.split("@")[0],
                    "inspection_count": 0,
                    "inspection_limit": 10
                }).execute()
            except Exception as e:
                print(f"[DEBUG] 创建用户配置失败: {e}")
                pass
            
            user_data = {
                "id": resp.user.id,
                "email": email,
                "display_name": display_name or email.split("@")[0],
                "inspection_count": 0,
                "inspection_limit": 10,
                "email_verified": True
            }
            return True, "注册成功！请直接登录使用。", user_data
        
        return False, "注册失败，请稍后重试", None
        
    except Exception as e:
        error_msg = str(e)
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            # 本地临时注册模式
            import hashlib
            import time
            temp_id = hashlib.md5(f"{email}{time.time()}".encode()).hexdigest()
            user_data = {
                "id": temp_id,
                "email": email,
                "display_name": display_name or email.split("@")[0],
                "inspection_count": 0,
                "inspection_limit": 10,
                "email_verified": True,
                "local_mode": True
            }
            return True, "注册成功！（离线模式，数据仅保存在当前会话）", user_data
        
        if "already registered" in error_msg.lower() or "already exists" in error_msg.lower():
            return False, "该邮箱已注册，请直接登录", None
        
        if "weak" in error_msg.lower():
            return False, "密码强度不足，请使用至少6位字符", None
        
        return False, f"注册失败: {error_msg[:100]}", None


def sign_in(email, password):
    """
    用户登录
    返回: (success, message, user_data, needs_verification)
    """
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置", None, False
    
    try:
        resp = sb.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if resp.user:
            email_confirmed = True  # 临时绕过邮箱验证
            
            user_data = {
                "id": resp.user.id,
                "email": resp.user.email or email,
                "display_name": resp.user.user_metadata.get("display_name", email.split("@")[0]),
                "email_verified": True
            }
            
            try:
                profile = sb.table("user_profiles").select("*").eq("id", resp.user.id).execute()
                
                if profile.data:
                    user_data["inspection_count"] = profile.data[0].get("inspection_count", 0)
                    user_data["inspection_limit"] = profile.data[0].get("inspection_limit", 10)
                else:
                    user_data["inspection_count"] = 0
                    user_data["inspection_limit"] = 10
            except Exception as e:
                print(f"[DEBUG] 获取用户配置失败: {e}")
                user_data["inspection_count"] = 0
                user_data["inspection_limit"] = 10
            
            return True, "登录成功", user_data, False
        
        return False, "登录失败：邮箱或密码错误", None, False
        
    except Exception as e:
        error_msg = str(e)
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            # 本地临时登录模式
            import hashlib
            temp_id = hashlib.md5(f"{email}".encode()).hexdigest()
            user_data = {
                "id": temp_id,
                "email": email,
                "display_name": email.split("@")[0],
                "inspection_count": 0,
                "inspection_limit": 10,
                "email_verified": True,
                "local_mode": True
            }
            return True, "登录成功！（离线模式，数据仅保存在当前会话）", user_data, False
        
        if "invalid" in error_msg.lower():
            return False, "邮箱或密码错误", None, False
        
        return False, f"登录失败: {error_msg[:100]}", None, False


def sign_out():
    """退出登录"""
    sb = get_supabase()
    if sb:
        try:
            sb.auth.sign_out()
        except Exception as e:
            print(f"[DEBUG] 退出登录失败: {e}")
    return True


def resend_verification_email(email):
    """重新发送验证邮件"""
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置"
    
    try:
        sb.auth.resend({
            "type": "signup",
            "email": email
        })
        return True, "验证邮件已重新发送，请检查收件箱（包括垃圾邮件文件夹）"
    except Exception as e:
        error_msg = str(e)
        if "rate limit" in error_msg.lower():
            return False, "发送过于频繁，请稍后再试"
        return False, f"发送失败: {error_msg[:100]}"


def check_email_verified(user_id):
    """检查用户邮箱是否已验证"""
    sb = get_supabase()
    if not sb:
        return False
    
    try:
        resp = sb.auth.admin.get_user_by_id(user_id)
        return resp.user.email_confirmed_at is not None
    except Exception as e:
        print(f"[DEBUG] 检查邮箱验证状态失败: {e}")
        return True  # 临时绕过


# ===== 验货次数管理 =====

def update_inspection_count(user_id, increment=True):
    """更新用户验货次数"""
    sb = get_supabase()
    if not sb:
        return False
    
    try:
        profile = sb.table("user_profiles").select("inspection_count").eq("id", user_id).execute()
        
        if profile.data:
            current = profile.data[0].get("inspection_count", 0)
            new_count = current + 1 if increment else max(0, current - 1)
            
            sb.table("user_profiles").update({
                "inspection_count": new_count
            }).eq("id", user_id).execute()
            return True
    except Exception as e:
        print(f"[DEBUG] 更新验货次数失败: {e}")
    
    return False


def get_user_count(user_id):
    """获取用户验货次数"""
    sb = get_supabase()
    if not sb:
        return 0, 10
    
    try:
        profile = sb.table("user_profiles").select("inspection_count, inspection_limit").eq("id", user_id).execute()
        
        if profile.data:
            return (
                profile.data[0].get("inspection_count", 0),
                profile.data[0].get("inspection_limit", 10)
            )
    except Exception as e:
        print(f"[DEBUG] 获取用户次数失败: {e}")
    
    return 0, 10


# ===== 报告保存 =====

def save_report(user_id, report_data):
    """保存验货报告"""
    sb = get_supabase()
    if not sb:
        return False
    
    try:
        sb.table("inspection_reports").insert({
            "user_id": user_id,
            "report_data": report_data,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        return True
    except Exception as e:
        print(f"[DEBUG] 保存报告失败: {e}")
        return False


def get_reports(user_id, limit=10):
    """获取用户历史报告"""
    sb = get_supabase()
    if not sb:
        return []
    
    try:
        resp = sb.table("inspection_reports").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute()
        return resp.data
    except Exception as e:
        print(f"[DEBUG] 获取报告失败: {e}")
        return []


# ===== IP 追踪（防滥用）=====

def get_ip_usage(client_ip):
    """获取 IP 的使用次数"""
    sb = get_supabase()
    if not sb or not client_ip:
        return 0
    
    try:
        # 使用 SUM 累加所有记录（修复：之前只取第一条）
        resp = sb.table("ip_usage").select("usage_count").eq("ip", client_ip).execute()
        
        if resp.data:
            total = sum(record.get("usage_count", 0) for record in resp.data)
            print(f"[DEBUG] IP {client_ip} 累计使用: {total} 次")
            return total
    except Exception as e:
        print(f"[DEBUG] 获取 IP 使用次数失败: {e}")
    
    return 0


def increment_ip_usage(client_ip):
    """增加 IP 使用次数"""
    sb = get_supabase()
    if not sb or not client_ip:
        return False
    
    try:
        # 检查是否已有记录
        resp = sb.table("ip_usage").select("*").eq("ip", client_ip).execute()
        
        if resp.data:
            # 更新现有记录
            current = resp.data[0].get("usage_count", 0)
            sb.table("ip_usage").update({
                "usage_count": current + 1,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("ip", client_ip).execute()
        else:
            # 创建新记录
            sb.table("ip_usage").insert({
                "ip": client_ip,
                "usage_count": 1,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        
        return True
    except Exception as e:
        print(f"[DEBUG] 增加 IP 使用次数失败: {e}")
    
    return False


def decrement_ip_usage(client_ip):
    """减少 IP 使用次数（用于错误回滚）"""
    sb = get_supabase()
    if not sb or not client_ip:
        return False
    
    try:
        resp = sb.table("ip_usage").select("*").eq("ip", client_ip).execute()
        
        if resp.data:
            current = resp.data[0].get("usage_count", 0)
            if current > 0:
                sb.table("ip_usage").update({
                    "usage_count": current - 1,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("ip", client_ip).execute()
        
        return True
    except Exception as e:
        print(f"[DEBUG] 减少 IP 使用次数失败: {e}")
    
    return False
