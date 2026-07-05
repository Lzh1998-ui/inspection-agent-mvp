"""
DNS 诊断工具 - 排查 Streamlit Cloud 容器网络问题
====================================================
功能：
1. 测试 Supabase 域名解析
2. 测试多个外部域名（判断容器网络状态）
3. 显示 /etc/resolv.conf DNS 配置
4. TCP 连接测试
5. 生成诊断报告

使用：
- 在 Streamlit 应用中：from dns_diagnostic import show_dns_diagnostic
- 独立运行：python dns_diagnostic.py
"""

import socket
import sys
import platform
import time

def test_dns_resolution(hostname, port=443, timeout=5):
    """测试单个域名的 DNS 解析（同时尝试 IPv4 和 IPv6）"""
    results = {
        "hostname": hostname,
        "ipv4": None,
        "ipv6": None,
        "ipv4_error": None,
        "ipv6_error": None,
        "tcp_ok": False,
        "tcp_error": None,
        "tcp_ip": None,
    }
    
    # 测试 IPv4
    try:
        info = socket.getaddrinfo(hostname, port, socket.AF_INET, socket.SOCK_STREAM)
        results["ipv4"] = info[0][4][0]
    except socket.gaierror as e:
        results["ipv4_error"] = str(e)
    except Exception as e:
        results["ipv4_error"] = f"异常: {e}"
    
    # 测试 IPv6
    try:
        info = socket.getaddrinfo(hostname, port, socket.AF_INET6, socket.SOCK_STREAM)
        results["ipv6"] = info[0][4][0]
    except socket.gaierror as e:
        results["ipv6_error"] = str(e)
    except Exception as e:
        results["ipv6_error"] = f"异常: {e}"
    
    # TCP 连接测试（使用 IPv4）
    if results["ipv4"]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((results["ipv4"], port))
            results["tcp_ok"] = True
            results["tcp_ip"] = results["ipv4"]
            sock.close()
        except socket.timeout:
            results["tcp_error"] = "TCP 连接超时"
        except Exception as e:
            results["tcp_error"] = str(e)
    
    return results


def get_dns_config():
    """读取系统 DNS 配置"""
    config = {"raw": "", "nameservers": [], "search": [], "options": []}
    try:
        with open('/etc/resolv.conf', 'r') as f:
            config["raw"] = f.read()
        for line in config["raw"].split("\n"):
            line = line.strip()
            if line.startswith("nameserver"):
                config["nameservers"].append(line.split()[1])
            elif line.startswith("search"):
                config["search"].append(line.split()[1])
            elif line.startswith("options"):
                config["options"].append(line[7:].strip())
    except Exception as e:
        config["raw"] = f"无法读取 /etc/resolv.conf: {e}"
    return config


def run_diagnostics(hostname="zbepdifjpfvphcjbhchx.supabase.co"):
    """
    运行完整 DNS 诊断
    
    参数:
        hostname: 要测试的目标域名
    
    返回: dict 包含所有诊断结果
    """
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "system": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "hostname": socket.gethostname(),
        },
        "dns_config": get_dns_config(),
        "tests": {},
        "summary": "",
    }
    
    # 关键测试目标
    test_hosts = [
        (hostname, "🎯 Supabase API（你的项目）", True),
        ("supabase.co", "🌐 Supabase 根域", False),
        ("www.baidu.com", "🇨🇳 百度（国内网络测试）", False),
        ("www.google.com", "🔍 Google", False),
        ("github.com", "💻 GitHub", False),
        ("pypi.org", "📦 PyPI", False),
        ("1.1.1.1", "☁️ Cloudflare DNS（IP直连）", False),
    ]
    
    for host, desc, is_target in test_hosts:
        # 如果是 IP 地址，跳过 DNS 解析，只测试 TCP
        if host.replace(".", "").isdigit():
            tcp_result = test_dns_resolution(host, port=443, timeout=3)
            report["tests"][host] = {
                "description": desc,
                "is_target": is_target,
                "ipv4": host,
                "ipv4_error": None,
                "ipv6": None,
                "ipv6_error": None,
                "tcp_ok": tcp_result["tcp_ok"],
                "tcp_error": tcp_result["tcp_error"],
                "tcp_ip": host,
            }
        else:
            r = test_dns_resolution(host, port=443, timeout=5)
            report["tests"][host] = {
                "description": desc,
                "is_target": is_target,
                "ipv4": r["ipv4"],
                "ipv4_error": r["ipv4_error"],
                "ipv6": r["ipv6"],
                "ipv6_error": r["ipv6_error"],
                "tcp_ok": r["tcp_ok"],
                "tcp_error": r["tcp_error"],
                "tcp_ip": r["tcp_ip"],
            }
    
    # 生成总结
    target = report["tests"].get(hostname, {})
    if target.get("ipv4"):
        if target.get("tcp_ok"):
            report["summary"] = "✅ Supabase 网络完全正常 - 问题在应用层（可能需要重启或查看其他错误）"
        else:
            report["summary"] = f"⚠️ Supabase 域名能解析但 TCP 连接失败 - 网络层问题: {target.get('tcp_error')}"
    else:
        # 检查其他域名
        other_ok = any(
            r.get("ipv4") for h, r in report["tests"].items() 
            if h != hostname and not h.replace(".", "").isdigit()
        )
        if not other_ok:
            report["summary"] = "❌ 容器完全无法访问外部网络 - Streamlit Cloud 网络故障，需要联系支持"
        else:
            report["summary"] = "❌ Supabase 域名解析失败但其他域名正常 - 可能是 DNS 缓存或 supabase.co 路由问题"
    
    return report


def format_report_text(report):
    """格式化诊断报告为可读文本"""
    lines = []
    lines.append("=" * 70)
    lines.append("🔍 DNS 诊断报告")
    lines.append("=" * 70)
    lines.append(f"生成时间: {report['timestamp']}")
    
    # 系统信息
    s = report["system"]
    lines.append(f"\n📋 系统信息:")
    lines.append(f"  Python: {s['python']}")
    lines.append(f"  Platform: {s['platform']}")
    lines.append(f"  Hostname: {s['hostname']}")
    
    # DNS 配置
    dns = report["dns_config"]
    lines.append(f"\n📡 DNS 配置 (/etc/resolv.conf):")
    if dns["nameservers"]:
        for ns in dns["nameservers"]:
            lines.append(f"  nameserver: {ns}")
    else:
        lines.append(f"  (无法解析)")
    if dns["raw"]:
        lines.append(f"\n  完整内容:")
        for line in dns["raw"].split("\n")[:10]:
            lines.append(f"    {line}")
    
    # 测试结果
    lines.append(f"\n🌐 DNS 解析 + TCP 连接测试:")
    for host, r in report["tests"].items():
        lines.append(f"\n  {r['description']}")
        lines.append(f"    {host}")
        
        if host.replace(".", "").isdigit():
            # IP 直连
            if r["tcp_ok"]:
                lines.append(f"    ✅ TCP 连通: {r['tcp_ip']}:443")
            else:
                lines.append(f"    ❌ TCP 失败: {r['tcp_error']}")
        else:
            # 域名测试
            if r["ipv4"]:
                lines.append(f"    ✅ IPv4 解析: {r['ipv4']}")
            else:
                lines.append(f"    ❌ IPv4 解析失败: {r['ipv4_error']}")
            
            if r["ipv6"]:
                lines.append(f"    ✅ IPv6 解析: {r['ipv6']}")
            else:
                lines.append(f"    ⚠️ IPv6 解析失败: {r['ipv6_error']}")
            
            if r["tcp_ok"]:
                lines.append(f"    ✅ TCP 连通: {r['tcp_ip']}:443")
            elif r["ipv4"]:
                lines.append(f"    ❌ TCP 失败: {r['tcp_error']}")
    
    # 总结
    lines.append(f"\n" + "=" * 70)
    lines.append(f"📊 诊断总结")
    lines.append(f"=" * 70)
    lines.append(f"  {report['summary']}")
    
    # 修复建议
    lines.append(f"\n💡 修复建议:")
    if "完全无法访问外部网络" in report["summary"]:
        lines.append(f"  1. 这不是代码问题，是 Streamlit Cloud 容器网络故障")
        lines.append(f"  2. 建议联系 Streamlit Cloud 支持: support@streamlit.io")
        lines.append(f"  3. 临时方案: 迁移到 Railway.app / Render.com / Fly.io")
        lines.append(f"  4. 或在 GitHub Issue 搜索: 'Streamlit Cloud DNS not working'")
    elif "Supabase 域名解析失败但其他域名正常" in report["summary"]:
        lines.append(f"  1. 尝试 Reboot app: Manage app → Reboot app")
        lines.append(f"  2. 如仍失败，联系 Streamlit Cloud 支持说明情况")
    elif "TCP 连接失败" in report["summary"]:
        lines.append(f"  1. DNS 解析正常但网络层不通 - 防火墙或路由问题")
        lines.append(f"  2. Reboot app 试试")
        lines.append(f"  3. 仍失败则联系支持")
    
    return "\n".join(lines)


def show_dns_diagnostic():
    """
    在 Streamlit 页面中显示 DNS 诊断工具
    """
    import streamlit as st
    
    st.markdown("### 🩺 网络诊断工具")
    st.caption("诊断 Streamlit Cloud 容器到 Supabase 服务器的网络连接")
    
    col1, col2 = st.columns(2)
    with col1:
        target_host = st.text_input(
            "目标域名",
            value="zbepdifjpfvphcjbhchx.supabase.co",
            help="默认是你的 Supabase 项目域名"
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        run_btn = st.button("🚀 运行诊断", type="primary", use_container_width=True)
    
    if run_btn:
        with st.spinner("正在诊断网络..."):
            report = run_diagnostics(target_host)
            text = format_report_text(report)
            
            # 显示结果
            st.code(text, language=None)
            
            # 总结卡片
            summary = report["summary"]
            if "✅" in summary:
                st.success(summary)
            elif "⚠️" in summary:
                st.warning(summary)
            else:
                st.error(summary)
            
            # 复制按钮
            st.download_button(
                "📋 下载诊断报告",
                data=text,
                file_name=f"dns_diagnosis_{report['timestamp'].replace(' ', '_').replace(':', '-')}.txt",
                mime="text/plain"
            )


# ===== 独立运行 =====
if __name__ == "__main__":
    print(run_diagnostics())
