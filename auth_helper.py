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

# ===== 临时邮箱黑名单 =====
TEMP_EMAIL_DOMAINS = {
    # 10分钟临时邮箱
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
    # 可以继续添加更多...
}

def is_temp_email(email):
    """
    检查邮箱是否为临时邮箱
    返回: True 表示是临时邮箱，False 表示是正常邮箱
    """
    if not email or "@" not in email:
        return False
    
    domain = email.split("@")[1].lower()
    
    # 检查是否是临时邮箱域名
    for temp_domain in TEMP_EMAIL_DOMAINS:
        if domain == temp_domain or domain.endswith("." + temp_domain):
            return True
    
    return False

# ===== 用户操作 =====

def sign_up(email, password, display_name=""):
    """
    注册新用户（真实邮箱验证模式）
    返回: (success, message, user_data, needs_verification)
    
    注册成功后，Supabase 会发送验证邮件到用户邮箱，
    用户需要点击邮件中的链接完成验证后才能登录。
    
    注意：不支持临时邮箱注册（如 Mailinator、10分钟邮箱等）
    """
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置，请联系管理员", None, False
    
    # 检查是否是临时邮箱
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
            
            # 检查是否需要邮箱验证
            if resp.user.email_confirmed_at is None:
                # 需要验证：返回 needs_verification=True，user_data=None
                return True, f"✅ 注册成功！请检查您的邮箱 {email} 完成验证（包括垃圾邮件文件夹）", None, True
            else:
                # 邮箱已验证（管理后台手动验证过或关闭了确认邮件）
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
        return False, f"注册失败：{error_msg}", None, False

def sign_in(email, password):
    """
    用户登录（真实邮箱验证模式）
    返回: (success, message, user_data, needs_verification)
    
    未验证邮箱的用户将无法登录，会提示用户去检查邮箱。
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
            # 检查邮箱是否已验证
            if resp.user.email_confirmed_at is None:
                # 立即退出登录（不允许未验证用户使用）
                try:
                    sb.auth.sign_out()
                except:
                    pass
                return False, f"请先验证您的邮箱后再登录（请检查 {email} 的收件箱，包括垃圾邮件文件夹）", None, True
            
            # 邮箱已验证，读取或创建用户配置
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
                    # 老用户没有 profile，自动创建
                    user_data["inspection_count"] = 0
                    user_data["inspection_limit"] = 10
                    try:
                        sb.table("user_profiles").insert({
                            "id": resp.user.id,
                            "email": email,
                            "display_name": user_data["display_name"],
                            "inspection_count": 0,
                            "inspection_limit": 10
                        }).execute()
                    except Exception as insert_err:
                        print(f"[DEBUG] 自动创建 profile 失败: {insert_err}")
            except Exception as e:
                print(f"[DEBUG] 获取用户配置失败: {e}")
                user_data["inspection_count"] = 0
                user_data["inspection_limit"] = 10
            
            return True, "登录成功", user_data, False
        return False, "登录失败：邮箱或密码错误", None, False
    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            return False, "邮箱或密码错误", None, False
        if "email not confirmed" in error_msg.lower():
            return False, "请先验证您的邮箱后再登录（请查收验证邮件）", None, True
        return False, f"登录失败：{error_msg}", None, False


def resend_verification_email(email):
    """
    重新发送邮箱验证邮件
    返回: (success, message)
    """
    sb = get_supabase()
    if not sb:
        return False, "Supabase 未配置"
    
    try:
        resp = sb.auth.resend({
            "type": "signup",
            "email": email
        })
        
        if resp:
            return True, "验证邮件已重新发送，请检查收件箱（包括垃圾邮件文件夹）"
        return False, "发送失败，请稍后重试"
    except Exception as e:
        error_msg = str(e)
        if "rate limit" in error_msg.lower():
            return False, "发送过于频繁，请稍后再试"
        return False, f"发送失败：{error_msg}"


def check_email_verified(user_id):
    """
    检查用户邮箱是否已验证
    返回: bool
    """
    sb = get_supabase()
    if not sb or not user_id:
        return False
    
    try:
        # 获取当前会话用户信息
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


# ===== IP 追踪（防换浏览器/无痕模式白嫖）=====
# 修改为永久计数（不按月重置）

def get_ip_usage(ip_address):
    """
    获取IP地址的总使用次数（永久累计）
    修复：同一 IP 可能有多个月份的旧记录，需 SUM 累加
    
    参数:
        ip_address: 客户端IP地址
    
    返回: int（总使用次数，查询失败返回0）
    """
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        print(f"[DEBUG] get_ip_usage 跳过: sb={sb}, ip={ip_address}")
        return 0
    
    try:
        # 修复：从只取第一条改为 SUM 累加所有记录
        # 这样即使旧数据有多个月份的记录，也能返回总使用次数
        resp = sb.table("ip_usage").select("usage_count").eq("ip_address", ip_address).execute()
        
        if resp.data:
            # 累加所有记录（兼容旧数据中同一 IP 多月份的情况）
            total = sum(record.get("usage_count", 0) for record in resp.data)
            print(f"[DEBUG] get_ip_usage 成功: ip={ip_address}, 总计={total} ({len(resp.data)}条记录)")
            return total
        
        print(f"[DEBUG] get_ip_usage 无记录: ip={ip_address}")
        return 0
    except Exception as e:
        print(f"[DEBUG] get_ip_usage 失败: {e}")
        return 0

def increment_ip_usage(ip_address):
    """
    增加IP地址的总使用次数（永久累计）
    
    参数:
        ip_address: 客户端IP地址
    
    返回: bool（是否成功）
    """
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        print(f"[DEBUG] increment_ip_usage 跳过: sb={sb}, ip={ip_address}")
        return False
    
    try:
        # 查询现有记录
        existing = sb.table("ip_usage").select("usage_count").eq("ip_address", ip_address).execute()
        
        if existing.data:
            # 更新现有记录
            new_count = existing.data[0]["usage_count"] + 1
            sb.table("ip_usage").update({
                "usage_count": new_count,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("ip_address", ip_address).execute()
            print(f"[DEBUG] increment_ip_usage 更新: ip={ip_address}, new_count={new_count}")
        else:
            # 创建新记录
            sb.table("ip_usage").insert({
                "ip_address": ip_address,
                "usage_count": 1,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            print(f"[DEBUG] increment_ip_usage 创建: ip={ip_address}, count=1")
        
        return True
    except Exception as e:
        print(f"[DEBUG] increment_ip_usage 失败: {e}")
        return False

def decrement_ip_usage(ip_address):
    """
    减少IP地址的总使用次数（分析失败回退）
    
    参数:
        ip_address: 客户端IP地址
    
    返回: bool（是否成功）
    """
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        print(f"[DEBUG] decrement_ip_usage 跳过: sb={sb}, ip={ip_address}")
        return False
    
    try:
        # 查询现有记录
        existing = sb.table("ip_usage").select("usage_count").eq("ip_address", ip_address).execute()
        
        if existing.data and existing.data[0]["usage_count"] > 0:
            # 减少计数
            new_count = existing.data[0]["usage_count"] - 1
            sb.table("ip_usage").update({
                "usage_count": new_count,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("ip_address", ip_address).execute()
            print(f"[DEBUG] decrement_ip_usage 成功: ip={ip_address}, new_count={new_count}")
        else:
            print(f"[DEBUG] decrement_ip_usage 无记录或计数已为0: ip={ip_address}")
        
        return True
    except Exception as e:
        print(f"[DEBUG] decrement_ip_usage 失败: {e}")
        return False


# ===== IP 黑名单（防滥用远程控制）=====

def is_ip_blocked(ip_address):
    """
    检查 IP 是否在黑名单中
    
    参数:
        ip_address: 客户端IP地址
    
    返回: bool（True=已封禁，False=未封禁）
    """
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        return False
    
    try:
        resp = sb.table("ip_blacklist").select("ip_address, reason").eq("ip_address", ip_address).execute()
        if resp.data:
            reason = resp.data[0].get("reason", "访问受限")
            print(f"[DEBUG] IP 已被封禁: {ip_address}, 原因: {reason}")
            return True
        return False
    except Exception as e:
        # 表不存在或其他错误，不拦截
        print(f"[DEBUG] 检查黑名单失败: {e}")
        return False

def block_ip(ip_address, reason="异常使用模式"):
    """
    封禁 IP（管理员手动调用，或在应用内调用）
    
    参数:
        ip_address: 要封禁的 IP
        reason: 封禁原因
    
    返回: bool
    """
    sb = get_supabase()
    if not sb or not ip_address or ip_address == "unknown":
        return False
    
    try:
        # 使用 upsert 避免重复
        sb.table("ip_blacklist").upsert({
            "ip_address": ip_address,
            "reason": reason,
            "blocked_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        print(f"[DEBUG] IP 已封禁: {ip_address}, 原因: {reason}")
        return True
    except Exception as e:
        print(f"[DEBUG] 封禁失败: {e}")
        return False

def unblock_ip(ip_address):
    """解封 IP"""
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("ip_blacklist").delete().eq("ip_address", ip_address).execute()
        print(f"[DEBUG] IP 已解封: {ip_address}")
        return True
    except Exception as e:
        print(f"[DEBUG] 解封失败: {e}")
        return False

def get_blacklist():
    """获取所有黑名单记录"""
    sb = get_supabase()
    if not sb:
        return []
    try:
        resp = sb.table("ip_blacklist").select("*").order("blocked_at", desc=True).execute()
        return resp.data if resp.data else []
    except Exception as e:
        print(f"[DEBUG] 获取黑名单失败: {e}")
        return []


# ===== 恶意使用模式检测 =====

def detect_suspicious_ip_patterns():
    """
    检测异常使用模式：
    1. 同一个 IP 在极短时间内（1小时内）使用次数过多
    2. 多个 IP 在同一小时段内都被更新（可能同一人换了多个IP）
    
    返回: list of dict，包含可疑IP及其原因
    """
    sb = get_supabase()
    if not sb:
        return []
    
    suspicious = []
    try:
        # 检测 1: 1 小时内使用超过 8 次的 IP（异常快）
        resp = sb.table("ip_usage")\
            .select("ip_address, usage_count, updated_at")\
            .gte("updated_at", (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())\
            .execute()
        
        if resp.data:
            for record in resp.data:
                usage = record.get("usage_count", 0)
                if usage >= 8:  # 1小时内用了8次（接近上限）
                    suspicious.append({
                        "ip_address": record["ip_address"],
                        "reason": f"1小时内使用{usage}次，接近上限",
                        "severity": "high" if usage >= 10 else "medium"
                    })
        
        # 检测 2: 1小时内创建了多条不同 IP 的记录（可能换 IP 刷）
        # 通过时间窗口分组
        if resp.data:
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            recent_ips = set()
            for record in resp.data:
                updated = record.get("updated_at", "")
                if updated and updated > one_hour_ago.isoformat():
                    recent_ips.add(record["ip_address"])
            
            # 如果 1 小时内有 3+ 个不同 IP 都被使用，可能是同一人换 IP
            if len(recent_ips) >= 3:
                for ip in recent_ips:
                    suspicious.append({
                        "ip_address": ip,
                        "reason": f"1小时内检测到{len(recent_ips)}个不同IP同时活跃",
                        "severity": "high"
                    })
        
        return suspicious
    except Exception as e:
        print(f"[DEBUG] 检测异常模式失败: {e}")
        return []

# ===== 导出次数管理 =====

def update_export_count(user_id, export_count):
    """
    更新用户导出次数（持久化到数据库）
    
    参数:
        user_id: 用户ID
        export_count: 新的导出次数
    
    返回: bool（成功/失败）
    """
    sb = get_supabase()
    if not sb:
        print("[DEBUG] Supabase 未配置，无法更新导出次数")
        return False
    
    try:
        # 尝试更新 user_profiles 表中的 export_count 字段
        # 注意：需要先在 Supabase 中添加 export_count 字段
        sb.table("user_profiles").update({
            "export_count": export_count
        }).eq("id", user_id).execute()
        
        print(f"[DEBUG] 更新导出次数成功: user_id={user_id}, export_count={export_count}")
        return True
    except Exception as e:
        # 如果字段不存在，会报错
        print(f"[DEBUG] 更新导出次数失败: {e}")
        print("[DEBUG] 提示：需要在 Supabase 的 user_profiles 表中添加 export_count 字段")
        return False

def get_export_count(user_id):
    """
    获取用户导出次数
    
    参数:
        user_id: 用户ID
    
    返回: int（导出次数，失败返回0）
    """
    sb = get_supabase()
    if not sb:
        return 0
    
    try:
        resp = sb.table("user_profiles").select("export_count").eq("id", user_id).execute()
        if resp.data:
            return resp.data[0].get("export_count", 0)
        return 0
    except Exception as e:
        print(f"[DEBUG] 获取导出次数失败: {e}")
        return 0
