"""
用户认证模块 - 基于 Supabase
================================
如果未配置 Supabase，自动降级为本地 Session 模式（无持久化）

修复说明（2026-07-06 03:32）：
- 【关键】DoH Monkey Patch：在 socket 层面劫持 DNS 失败，用 Cloudflare 1.1.1.1 兜底
  - 解决 Streamlit Cloud 容器 DNS 完全失效问题
  - 即使系统 DNS 100% 失败，supabase 库仍能解析域名
- DNS 预检：在 sign_in/sign_up 前先测试域名解析
- 详细错误诊断：把 DNS 错误翻译成用户可懂的提示
"""

# ===== DoH Monkey Patch（必须在所有 import 之前）=====
import sys as _sys
import socket as _socket
import json as _json
import urllib.request as _urllib_request
import time as _time

print("=" * 60, flush=True)
print("[AUTH_HELPER] v2026-07-06-DoH-fallback LOADED", flush=True)
print("=" * 60, flush=True)

# 保存原始 getaddrinfo
_original_getaddrinfo = _socket.getaddrinfo
_DOH_CACHE = {}
_DOH_CACHE_TTL = 600  # 10 分钟缓存

def _doh_resolve(hostname, timeout=5):
    """通过 Cloudflare DoH (1.1.1.1) 解析域名 — 1.1.1.1 是 IP，不需要 DNS"""
    now = _time.time()
    if hostname in _DOH_CACHE:
        ip, ts = _DOH_CACHE[hostname]
        if now - ts < _DOH_CACHE_TTL:
            return ip
    try:
        url = f"https://1.1.1.1/dns-query?name={hostname}&type=A"
        req = _urllib_request.Request(url, headers={"Accept": "application/dns-json"})
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read())
        if "Answer" in data:
            for ans in data["Answer"]:
                if ans.get("type") == 1:  # A 记录
                    ip = ans["data"]
                    _DOH_CACHE[hostname] = (ip, now)
                    print(f"[AUTH_HELPER] ✅ DoH 解析: {hostname} → {ip}", flush=True)
                    return ip
    except Exception as e:
        print(f"[AUTH_HELPER] ⚠️ DoH 失败: {hostname}: {e}", flush=True)
    return None


def _patched_getaddrinfo(host, port, *args, **kwargs):
    """先尝试系统 DNS，失败后用 DoH 兜底（关键修复）"""
    try:
        return _original_getaddrinfo(host, port, *args, **kwargs)
    except _socket.gaierror as e:
        print(f"[AUTH_HELPER] 系统 DNS 失败: {host}, 尝试 DoH fallback...", flush=True)
        ip = _doh_resolve(host)
        if ip:
            # 返回 (family, type, proto, canonname, sockaddr) 格式
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (ip, port or 0))]
        print(f"[AUTH_HELPER] ❌ 系统 DNS + DoH 都失败: {host}: {e}", flush=True)
        raise

# 立即 patch - 必须在 import supabase 之前
_socket.getaddrinfo = _patched_getaddrinfo
print("[AUTH_HELPER] ✅ socket.getaddrinfo DoH fallback 已启用", flush=True)
print("=" * 60, flush=True)


# ===== 正常 import =====
import streamlit as st
import socket
import time
from datetime import datetime, timezone, timedelta

# ===== DNS 诊断函数 =====

def check_dns_resolution(hostname, timeout=3):
    """
    快速 DNS 解析检测（用于登录前预检）
    
    返回: (success: bool, ip_or_error: str, error_type: str)
    """
    try:
        info = socket.getaddrinfo(hostname, 443, socket.AF_INET, socket.SOCK_STREAM)
        ip = info[0][4][0]
        return True, ip, None
    except socket.gaierror as e:
        return False, str(e), "dns_error"
    except socket.timeout:
        return False, "DNS 查询超时", "timeout"
    except Exception as e:
        return False, str(e), "other"


def get_dns_error_message(hostname, error_detail):
    """
    根据错误类型生成用户友好的错误提示
    """
    if "Name or service not known" in error_detail or "Errno -2" in error_detail:
        return (
            f"❌ **网络连接失败：无法解析域名 `{hostname}`**\n\n"
            f"**原因**：Streamlit Cloud 容器 DNS 解析失败\n\n"
            f"**已尝试的解决方法**：\n"
            f"1. ✅ 页面刷新（Ctrl+F5）\n"
            f"2. ✅ Reboot app（Manage app → Reboot）\n\n"
            f"**如果以上都无效**，这是 Streamlit Cloud 容器网络问题，**不是您的配置问题**。\n\n"
            f"**建议**：\n"
            f"- 联系 Streamlit Cloud 支持：support@streamlit.io\n"
            f"- 或迁移到其他平台（Railway / Render / Fly.io）\n"
            f"- 或在 Streamlit Community Cloud 论坛搜索类似问题\n\n"
            f"🔧 临时绕过：使用页面底部的「🩺 网络诊断」工具查看详细情况"
        )
    elif "timeout" in error_detail.lower():
        return (
            f"❌ **网络连接超时**\n\n"
            f"可能是容器网络过慢，请稍后重试。"
        )
    else:
        return f"❌ 网络错误：{error_detail}"


# ===== 缓存 Supabase 客户端（避免重复初始化）=====

SUPABASE_HOST = "zbepdifjpfvphcjbhchx.supabase.co"

@st.cache_resource
def get_supabase():
    """获取 Supabase 客户端（未配置时返回 None）"""
    try:
        from supabase import create_client
        
        url = st.secrets.get("supabase", {}).get("url", "")
        key = st.secrets.get("supabase", {}).get("anon_key", "")
        
        if url and key and url != "https://your-project.supabase.co":
            # 【新增】DNS 预检
            dns_ok, dns_info, _ = check_dns_resolution(SUPABASE_HOST, timeout=3)
            if dns_ok:
                print(f"[DEBUG] DNS 预检通过: {SUPABASE_HOST} → {dns_info}")
            else:
                print(f"[DEBUG] ⚠️ DNS 预检失败: {SUPABASE_HOST} → {dns_info}")
                print(f"[DEBUG] 应用仍会创建客户端（DNS 问题可能临时），但 API 调用会失败")
            
            return create_client(url, key)
        return None
    except Exception as e:
        print(f"[DEBUG] Supabase 客户端初始化失败: {e}")
        return None


def is_supabase_configured():
    """检查 Supabase 是否已配置"""
    return get_supabase() is not None


# ===== 临时邮箱黑名单 =====
TEMP_EMAIL_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "10minmail.com",
    "mailinator.com", "mailinator.net", "mailinator2.com",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.org", "guerrillamail.biz",
    "guerrillamailblock.com", "pokemail.net", "spam4.me",
    "tempmail.com", "temp-mail.org", "temp-mail.io", "tempmail.net",
    "throwaway.email", "throwawaymail.com",
    "fakeinbox.com", "fakemailgenerator.com",
    "maildrop.cc", "dispostable.com",
    "yopmail.com", "yopmail.fr", "yopmail.net",
    "trashmail.com", "trashmail.net", "trashmail.org",
    "getairmail.com", "getnada.com", "nada.email",
    "tempinbox.com", "mailnesia.com",
    "mintemail.com", "sharklasers.com",
    "spamgourmet.com", "mytrashmail.com",
    "mailcatch.com", "mailnull.com",
    "tempr.email", "discard.email", "discardmail.com",
    "spambox.us", "spamfree24.org", "spamherelots.com",
    "tempsky.com", "crazymailing.com",
    "emailondeck.com", "tempail.com",
    "mohmal.com", "mohmal.tech",
}


def is_temp_email(email):
    """检查邮箱是否为临时邮箱"""
    if not email or "@" not in email:
        return False
    domain = email.split("@")[1].lower()
    for temp_domain in TEMP_EMAIL_DOMAINS:
        if domain == temp_domain or domain.endswith("." + temp_domain):
            return True
    return False


# ===== 用户操作 =====

def _check_dns_with_retry(hostname, max_retries=2, delay=1):
    """
    带重试的 DNS 检测
    
    返回: (success, info, error_type)
    """
    for attempt in range(max_retries):
        success, info, error_type = check_dns_resolution(hostname, timeout=3)
        if success:
            return True, info, None
        if attempt < max_retries - 1:
            time.sleep(delay)
    return False, info, error_type


def sign_up(email, password, display_name=""):
    """
    注册新用户（真实邮箱验证模式）
    返回: (success, message, user_data, needs_verification)
    """
    # 【新增】DNS 预检（带 2 次重试）
    dns_ok, dns_info, error_type = _check_dns_with_retry(SUPABASE_HOST, max_retries=2, delay=1)
    if not dns_ok:
        msg = get_dns_error_message(SUPABASE_HOST, dns_info)
        return False, msg, None, False
    
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置，请联系管理员", None, False
    
    if is_temp_email(email):
        return False, "❌ 不支持临时邮箱注册。请使用您的工作邮箱或真实邮箱进行注册。", None, False
    
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
            
            if resp.user.email_confirmed_at is None:
                return True, f"✅ 注册成功！请检查您的邮箱 {email} 完成验证（包括垃圾邮件文件夹）", None, True
            else:
                user_data = {
                    "id": resp.user.id,
                    "email": email,
                    "display_name": display_name or email.split("@")[0],
                    "inspection_count": 0,
                    "inspection_limit": 10,
                    "email_verified": True
                }
                return True, "注册成功！", user_data, False
        
        return False, "注册失败：未返回用户信息", None, False
    except Exception as e:
        error_msg = str(e)
        if "already registered" in error_msg.lower() or "重复" in error_msg:
            return False, "该邮箱已注册，请直接登录", None, False
        if "weak" in error_msg.lower() or "password" in error_msg.lower():
            return False, "密码强度不足，请使用至少6位字符", None, False
        # 【新增】捕获 DNS 错误
        if "name or service not known" in error_msg.lower() or "errno -2" in error_msg.lower():
            return False, get_dns_error_message(SUPABASE_HOST, error_msg), None, False
        return False, f"注册失败：{error_msg}", None, False


def sign_in(email, password, local_usage_count=0):
    """
    用户登录（真实邮箱验证模式）
    返回: (success, message, user_data, needs_verification)
    """
    # 【新增】DNS 预检（带 2 次重试）
    dns_ok, dns_info, error_type = _check_dns_with_retry(SUPABASE_HOST, max_retries=2, delay=1)
    if not dns_ok:
        msg = get_dns_error_message(SUPABASE_HOST, dns_info)
        return False, msg, None, False
    
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置", None, False
    
    try:
        resp = sb.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if resp.user:
            if resp.user.email_confirmed_at is None:
                try:
                    sb.auth.sign_out()
                except:
                    pass
                return False, f"请先验证您的邮箱后再登录（请检查 {email} 的收件箱，包括垃圾邮件文件夹）", None, True
            
            user_data = {
                "id": resp.user.id,
                "email": resp.user.email or email,
                "display_name": resp.user.user_metadata.get("display_name", email.split("@")[0]),
                "email_verified": True
            }
            
            try:
                profile = sb.table("user_profiles").select("*").eq("id", resp.user.id).execute()
                
                if profile.data:
                    db_count = profile.data[0].get("inspection_count", 0)
                    user_data["inspection_limit"] = profile.data[0].get("inspection_limit", 10)
                    
                    merged_count = db_count
                    if local_usage_count > 0 and local_usage_count > db_count:
                        merged_count = local_usage_count
                        try:
                            sb.table("user_profiles").update({
                                "inspection_count": merged_count
                            }).eq("id", resp.user.id).execute()
                            print(f"[DEBUG] 合并使用次数: DB={db_count} + 本地={local_usage_count} → {merged_count}")
                        except Exception as update_err:
                            print(f"[DEBUG] 合并次数更新失败: {update_err}")
                    
                    user_data["inspection_count"] = merged_count
                else:
                    user_data["inspection_count"] = local_usage_count
                    user_data["inspection_limit"] = 10
                    try:
                        sb.table("user_profiles").insert({
                            "id": resp.user.id,
                            "email": email,
                            "display_name": user_data["display_name"],
                            "inspection_count": local_usage_count,
                            "inspection_limit": 10
                        }).execute()
                    except Exception as insert_err:
                        print(f"[DEBUG] 自动创建 profile 失败: {insert_err}")
            except Exception as e:
                print(f"[DEBUG] 获取用户配置失败: {e}")
                user_data["inspection_count"] = local_usage_count
                user_data["inspection_limit"] = 10
            
            return True, "登录成功", user_data, False
        return False, "登录失败：邮箱或密码错误", None, False
    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            return False, "邮箱或密码错误", None, False
        if "email not confirmed" in error_msg.lower():
            return False, "请先验证您的邮箱后再登录（请查收验证邮件）", None, True
        # 【新增】捕获 DNS 错误
        if "name or service not known" in error_msg.lower() or "errno -2" in error_msg.lower():
            return False, get_dns_error_message(SUPABASE_HOST, error_msg), None, False
        return False, f"登录失败：{error_msg}", None, False


def resend_verification_email(email):
    """重新发送邮箱验证邮件"""
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置"
    
    try:
        resp = sb.auth.resend({"type": "signup", "email": email})
        if resp:
            return True, "验证邮件已重新发送，请检查收件箱（包括垃圾邮件文件夹）"
        return False, "发送失败，请稍后重试"
    except Exception as e:
        error_msg = str(e)
        if "rate limit" in error_msg.lower():
            return False, "发送过于频繁，请稍后再试"
        if "name or service not known" in error_msg.lower() or "errno -2" in error_msg.lower():
            return False, get_dns_error_message(SUPABASE_HOST, error_msg)
        return False, f"发送失败：{error_msg}"


def check_email_verified(user_id):
    """检查用户邮箱是否已验证"""
    sb = get_supabase()
    if not sb or not user_id:
        return False
    try:
        resp = sb.auth.get_user()
        if resp and resp.user:
            return resp.user.email_confirmed_at is not None
        return False
    except Exception as e:
        print(f"[DEBUG] 检查邮箱验证状态失败: {e}")
        return False


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
        sb.table("user_profiles").update({
            "inspection_count": new_count,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", user_id).execute()
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
        resp = sb.table("inspection_reports").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute()
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
        resp = sb.table("user_profiles").select("inspection_count, inspection_limit").eq("id", user_id).execute()
        if resp.data:
            return resp.data[0].get("inspection_count", 0), resp.data[0].get("inspection_limit", 20)
    except Exception as e:
        print(f"[DEBUG] 获取用户次数失败: {e}")
        pass
    return 0, 20


# ===== IP 追踪 =====
def get_ip_usage(ip_address):
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        return 0
    try:
        resp = sb.table("ip_usage").select("usage_count").eq("ip_address", ip_address).execute()
        if resp.data:
            total = sum(record.get("usage_count", 0) for record in resp.data)
            return total
        return 0
    except Exception as e:
        print(f"[DEBUG] get_ip_usage 失败: {e}")
        return 0


def increment_ip_usage(ip_address):
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        return False
    try:
        existing = sb.table("ip_usage").select("usage_count").eq("ip_address", ip_address).execute()
        if existing.data:
            new_count = existing.data[0]["usage_count"] + 1
            sb.table("ip_usage").update({
                "usage_count": new_count,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("ip_address", ip_address).execute()
        else:
            sb.table("ip_usage").insert({
                "ip_address": ip_address,
                "usage_count": 1,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        return True
    except Exception as e:
        print(f"[DEBUG] increment_ip_usage 失败: {e}")
        return False


def decrement_ip_usage(ip_address):
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        return False
    try:
        existing = sb.table("ip_usage").select("usage_count").eq("ip_address", ip_address).execute()
        if existing.data and existing.data[0]["usage_count"] > 0:
            new_count = existing.data[0]["usage_count"] - 1
            sb.table("ip_usage").update({
                "usage_count": new_count,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("ip_address", ip_address).execute()
        return True
    except Exception as e:
        print(f"[DEBUG] decrement_ip_usage 失败: {e}")
        return False


# ===== 导出次数管理 =====
def update_export_count(user_id, export_count):
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("user_profiles").update({
            "export_count": export_count,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", user_id).execute()
        return True
    except Exception as e:
        print(f"[DEBUG] 更新导出次数失败: {e}")
        return False


def get_export_count(user_id):
    sb = get_supabase()
    if not sb or not user_id:
        return 0
    try:
        resp = sb.table("user_profiles").select("export_count").eq("id", user_id).execute()
        if resp.data:
            return resp.data[0].get("export_count", 0) or 0
    except Exception as e:
        print(f"[DEBUG] 获取导出次数失败: {e}")
        pass
    return 0
