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
    返回: (success, message)
    """
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置，请联系管理员"
    
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
                    "inspection_limit": 20
                }).execute()
            except Exception as e:
                print(f"[DEBUG] 创建用户配置失败: {e}")
                pass  # 可能已经存在
            
            return True, "注册成功！请检查邮箱确认链接（部分情况下可直接登录）"
        return False, "注册失败"
    except Exception as e:
        error_msg = str(e)
        if "already registered" in error_msg.lower() or "重复" in error_msg:
            return False, "该邮箱已注册，请直接登录"
        if "weak" in error_msg.lower():
            return False, "密码强度不足，请使用至少6位字符"
        return False, f"注册失败：{error_msg}"

def sign_in(email, password):
    """
    用户登录
    返回: (success, message, user_data)
    """
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置", None
    
    try:
        resp = sb.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if resp.user:
            # 获取用户配置
            user_data = {
                "id": resp.user.id,
                "email": resp.user.email or email,
                "display_name": resp.user.user_metadata.get("display_name", email.split("@")[0])
            }
            
            # 获取用户配置
            try:
                profile = sb.table("user_profiles")\
                    .select("*")\
                    .eq("id", resp.user.id)\
                    .execute()
                
                if profile.data:
                    user_data["inspection_count"] = profile.data[0].get("inspection_count", 0)
                    user_data["inspection_limit"] = profile.data[0].get("inspection_limit", 20)
                else:
                    user_data["inspection_count"] = 0
                    user_data["inspection_limit"] = 20
            except Exception as e:
                print(f"[DEBUG] 获取用户配置失败: {e}")
                user_data["inspection_count"] = 0
                user_data["inspection_limit"] = 20
            
            return True, "登录成功", user_data
        return False, "登录失败：邮箱或密码错误", None
    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            return False, "邮箱或密码错误", None
        return False, f"登录失败：{error_msg}", None

def sign_out():
    """退出登录"""
    sb = get_supabase()
    if sb:
        try:
            sb.auth.sign_out()
        except Exception as e:
            print(f"[DEBUG] 退出登录失败: {e}")
            pass

def update_inspection_count(user_id, new_count):
    """更新用户的验货次数"""
    sb = get_supabase()
    if not sb or not user_id:
        return False
    
    try:
        sb.table("user_profiles")\
            .update({
                "inspection_count": new_count,
                "updated_at": datetime.now(timezone.utc).isoformat()
            })\
            .eq("id", user_id)\
            .execute()
        return True
    except Exception as e:
        print(f"[DEBUG] 更新验货次数失败: {e}")
        return False

def save_report(user_id, report_data):
    """保存验货报告到数据库"""
    sb = get_supabase()
    if not sb or not user_id:
        return False
    
    try:
        sb.table("inspection_reports").insert({
            "user_id": user_id,
            "product_name": report_data.get("product_name", ""),
            "report_data": report_data,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        return True
    except Exception as e:
        print(f"[DEBUG] 保存报告失败: {e}")
        return False

def get_reports(user_id, limit=10):
    """获取用户的验货历史"""
    sb = get_supabase()
    if not sb or not user_id:
        return []
    
    try:
        resp = sb.table("inspection_reports")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()
        return resp.data if resp.data else []
    except Exception as e:
        print(f"[DEBUG] 获取报告失败: {e}")
        return []

def get_user_count(user_id):
    """从数据库获取用户当前验货次数"""
    sb = get_supabase()
    if not sb or not user_id:
        return 0, 20
    
    try:
        resp = sb.table("user_profiles")\
            .select("inspection_count, inspection_limit")\
            .eq("id", user_id)\
            .execute()
        if resp.data:
            return resp.data[0].get("inspection_count", 0), resp.data[0].get("inspection_limit", 20)
    except Exception as e:
        print(f"[DEBUG] 获取用户次数失败: {e}")
        pass
    return 0, 20


# ===== IP 追踪（防换浏览器/无痕模式白嫖）=====
# 修复：字段名从 usage_month 改为 month（匹配 Supabase 表结构）

def get_ip_usage(ip_address, month):
    """
    获取IP地址当月的使用次数
    
    参数:
        ip_address: 客户端IP地址
        month: 月份字符串（格式：YYYY-MM）
    
    返回: int（使用次数，查询失败返回0）
    """
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        print(f"[DEBUG] get_ip_usage 跳过: sb={sb}, ip={ip_address}")
        return 0
    
    try:
        resp = sb.table("ip_usage")\
            .select("usage_count")\
            .eq("ip_address", ip_address)\
            .eq("month", month)\  # 修复：使用 month 字段
            .execute()
        
        if resp.data:
            count = resp.data[0].get("usage_count", 0)
            print(f"[DEBUG] get_ip_usage 成功: ip={ip_address}, month={month}, count={count}")
            return count
        
        print(f"[DEBUG] get_ip_usage 无记录: ip={ip_address}, month={month}")
        return 0
    except Exception as e:
        print(f"[DEBUG] get_ip_usage 失败: {e}")
        return 0

def increment_ip_usage(ip_address, month):
    """
    增加IP地址当月使用次数
    
    参数:
        ip_address: 客户端IP地址
        month: 月份字符串（格式：YYYY-MM）
    
    返回: bool（是否成功）
    """
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        print(f"[DEBUG] increment_ip_usage 跳过: sb={sb}, ip={ip_address}")
        return False
    
    try:
        # 查询现有记录
        existing = sb.table("ip_usage")\
            .select("usage_count")\
            .eq("ip_address", ip_address)\
            .eq("month", month)\  # 修复：使用 month 字段
            .execute()
        
        if existing.data:
            # 更新现有记录
            new_count = existing.data[0]["usage_count"] + 1
            sb.table("ip_usage")\
                .update({
                    "usage_count": new_count,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })\
                .eq("ip_address", ip_address)\
                .eq("month", month)\  # 修复：使用 month 字段
                .execute()
            print(f"[DEBUG] increment_ip_usage 更新: ip={ip_address}, month={month}, new_count={new_count}")
        else:
            # 创建新记录
            sb.table("ip_usage").insert({
                "ip_address": ip_address,
                "month": month,  # 修复：使用 month 字段
                "usage_count": 1,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            print(f"[DEBUG] increment_ip_usage 创建: ip={ip_address}, month={month}, count=1")
        
        return True
    except Exception as e:
        print(f"[DEBUG] increment_ip_usage 失败: {e}")
        return False

def decrement_ip_usage(ip_address, month):
    """
    减少IP地址当月使用次数（分析失败回退）
    
    参数:
        ip_address: 客户端IP地址
        month: 月份字符串（格式：YYYY-MM）
    
    返回: bool（是否成功）
    """
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        print(f"[DEBUG] decrement_ip_usage 跳过: sb={sb}, ip={ip_address}")
        return False
    
    try:
        # 查询现有记录
        existing = sb.table("ip_usage")\
            .select("usage_count")\
            .eq("ip_address", ip_address)\
            .eq("month", month)\  # 修复：使用 month 字段
            .execute()
        
        if existing.data and existing.data[0]["usage_count"] > 0:
            # 减少计数
            new_count = existing.data[0]["usage_count"] - 1
            sb.table("ip_usage")\
                .update({
                    "usage_count": new_count,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })\
                .eq("ip_address", ip_address)\
                .eq("month", month)\  # 修复：使用 month 字段
                .execute()
            print(f"[DEBUG] decrement_ip_usage 成功: ip={ip_address}, month={month}, new_count={new_count}")
        else:
            print(f"[DEBUG] decrement_ip_usage 无记录或计数已为0: ip={ip_address}, month={month}")
        
        return True
    except Exception as e:
        print(f"[DEBUG] decrement_ip_usage 失败: {e}")
        return False
