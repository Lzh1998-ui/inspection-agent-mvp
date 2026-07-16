# -*- coding: utf-8 -*-
"""
app_pro/tools.py - 工具注册表与工具实现

每个工具 = Python 函数 + JSON Schema 描述。
注册到 TOOLS 列表，供 Agent loop 的 function calling 使用。

设计原则：
- 工具执行必须有 try/except，返回结构化 dict（不抛异常到 Agent 层）
- description 写清楚"何时该调用"，让模型自主判断
- 参数严格校验，失败返回 {"error": ...}
"""

from __future__ import annotations

import json
from typing import Any

# ===== 依赖 core（共享内核）=====
from core.aql import get_aql_sample_info

# ===== Supabase 客户端（延迟初始化）=====
_supabase_client = None


def _get_supabase():
    """延迟初始化 Supabase 客户端（避免模块加载时未配置时报错）。"""
    global _supabase_client
    if _supabase_client is None:
        try:
            from supabase import create_client
            import streamlit as st

            url = st.secrets.get("supabase", {}).get("url")
            key = st.secrets.get("supabase", {}).get("service_role_key") or st.secrets.get(
                "supabase", {}
            ).get("anon_key")
            if url and key:
                _supabase_client = create_client(url, key)
        except Exception:
            _supabase_client = None
    return _supabase_client


# ============================================================================
# P0 工具实现
# ============================================================================


def tool_query_aql_plan(order_quantity: int, aql_value: str, severity: str = "主要") -> dict:
    """
    根据订单数量和 AQL 值查询 ANSI Z1.4 真实抽样方案。

    返回: {
        "sample_size": int,     # 抽样数量
        "sample_code": str,     # 字母代码(A-Q)
        "ac": int,             # 接收数 (Accept)
        "re": int,             # 拒收数 (Reject)
        "aql": str,            # 输入的 AQL 值
        "severity": str,       # 缺陷严重程度
        "note": str            # 提示信息
    }
    """
    try:
        if not isinstance(order_quantity, (int, float)) or order_quantity < 1:
            return {"error": "order_quantity 必须是正整数"}
        if not isinstance(aql_value, str) or not aql_value.strip():
            return {"error": "aql_value 格式如 'AQL 2.5'，请提供有效字符串"}

        aql_str = aql_value.strip()
        # 统一大小写
        aql_str = aql_str.upper()
        if not aql_str.startswith("AQL"):
            aql_str = "AQL " + aql_str

        sample_size, sample_code, ac, re = get_aql_sample_info(int(order_quantity), aql_str)

        # 严重程度对应
        severity_note = {
            "致命": "致命缺陷零容忍，任何数量均不合格（Ac=0）",
            "主要": f"主要缺陷：抽样{sample_size}件，Ac={ac}，Re={re}",
            "次要": f"次要缺陷：抽样{sample_size}件，Ac={ac}，Re={re}",
        }.get(severity, "")

        return {
            "sample_size": sample_size,
            "sample_code": sample_code,
            "ac": ac,
            "re": re,
            "aql": aql_str,
            "severity": severity,
            "note": severity_note,
        }
    except Exception as e:
        return {"error": f"查询 AQL 方案失败: {str(e)}"}


def tool_search_defect_history(
    product_name: str,
    factory_name: str | None = None,
    limit: int = 5,
) -> dict:
    """
    检索同类产品/工厂的历史验货缺陷记录，供 AI 参考同类产品的常见问题模式。

    返回: {
        "records": [  {
            "product_name": str,
            "factory_name": str,
            "report_date": str,
            "conclusion": str,
            "defects": [ {"type": str, "severity": str, "quantity": int, "description": str} ],
            "recommendation": str
        }, ... ],
        "count": int
    }
    """
    try:
        client = _get_supabase()
        if client is None:
            return {"error": "Supabase 未配置，无法查询历史记录"}

        if not product_name or not product_name.strip():
            return {"error": "请提供 product_name"}

        limit = min(max(int(limit), 1), 20)  # 限制最多20条

        query = (
            client.table("inspection_reports")
            .select("product_name, factory_name, conclusion, defects, recommendation, created_at")
            .ilike("product_name", f"%{product_name.strip()}%")
            .order("created_at", desc=True)
            .limit(limit)
        )

        if factory_name and factory_name.strip():
            query = query.ilike("factory_name", f"%{factory_name.strip()}%")

        resp = query.execute()
        records = []
        for row in (resp.data or []):
            defects = row.get("defects", [])
            if isinstance(defects, str):
                try:
                    defects = json.loads(defects)
                except Exception:
                    defects = []
            records.append(
                {
                    "product_name": row.get("product_name", ""),
                    "factory_name": row.get("factory_name", ""),
                    "report_date": str(row.get("created_at", ""))[:10],
                    "conclusion": row.get("conclusion", ""),
                    "defects": defects[: 10],  # 每条最多10个缺陷
                    "recommendation": row.get("recommendation", ""),
                }
            )

        return {"records": records, "count": len(records)}
    except Exception as e:
        return {"error": f"检索历史缺陷失败: {str(e)}"}


# ============================================================================
# P1 工具实现
# ============================================================================


# 内置标准知识库（可后续扩展为 Supabase 表）
_STANDARDS_DB: dict[str, dict] = {
    "电子产品": {
        "standard": "GB 4943.1 / IEC 60950-1",
        "key_checks": [
            "安全标识（CCC/CE）完整且清晰",
            "电源线插头规格符合目的地国家",
            "防水等级（IPXX）与标称一致",
            "铭牌参数与实物一致",
            "电池安全（锂电池需 UN38.3）",
        ],
        "common_defects": [
            "标签信息缺失或错误",
            "电源线规格不符",
            "外壳缝隙过大",
            "按键手感异常",
            "接口松动",
        ],
        "reference": "GB 4943.1-2022 / IEC 60950-1:2013",
    },
    "纺织品/服装": {
        "standard": "GB 18401 / ISO 3758",
        "key_checks": [
            "纤维成分标签与实际一致",
            "色牢度（洗水/摩擦/汗渍）",
            "尺寸偏差在允收范围内",
            "外观缺陷（断纱/跳线/污渍）",
            "附件安全性（拉链/纽扣/装饰物）",
        ],
        "common_defects": [
            "色差（件与件/部位与部位）",
            "尺寸超差",
            "针距不足",
            "洗后缩水超标",
            "附件脱落风险",
        ],
        "reference": "GB 18401-2010 / ISO 3758:2012",
    },
    "玩具": {
        "standard": "GB 6675 / EN 71 / ASTM F963",
        "key_checks": [
            "年龄标识与实际适龄性",
            "小零件（窒息风险）",
            "锐边/锐尖",
            "可燃性",
            "重金属含量（EN 71-3）",
        ],
        "common_defects": [
            "小零件未标识",
            "涂层铅含量超标",
            "结构强度不足",
            "标识缺失",
        ],
        "reference": "GB 6675.1-2014 / EN 71-1:2014+A3:2019 / ASTM F963-17",
    },
    "机械配件": {
        "standard": "GB/T 1804 / ISO 2768",
        "key_checks": [
            "尺寸精度（关键尺寸全检）",
            "表面粗糙度",
            "材质证明（MTC）",
            "硬度/强度测试",
            "螺纹通止规检验",
        ],
        "common_defects": [
            "关键尺寸超差",
            "表面裂纹/气孔",
            "螺纹不合格",
            "材质偏差",
        ],
        "reference": "GB/T 1804-2000 / ISO 2768-1:1989",
    },
}


def tool_lookup_standard(product_category: str) -> dict:
    """
    查询指定产品类别的验货标准要点和常见缺陷模式。

    返回: {
        "category": str,
        "standard": str,
        "key_checks": [str, ...],
        "common_defects": [str, ...],
        "reference": str
    }
    """
    try:
        if not product_category or not product_category.strip():
            return {"error": "请提供 product_category（产品类别）"}

        key = product_category.strip()
        # 模糊匹配
        for cat_key, info in _STANDARDS_DB.items():
            if cat_key in key or key in cat_key:
                result = dict(info)
                result["category"] = cat_key
                return result

        # 无匹配时返回已知类别列表
        return {
            "error": f"未找到类别 '{product_category}' 的内置标准",
            "known_categories": list(_STANDARDS_DB.keys()),
            "hint": "请尝试：电子产品、纺织品/服装、玩具、机械配件",
        }
    except Exception as e:
        return {"error": f"查询标准失败: {str(e)}"}


def tool_get_product_profile(product_name: str, factory_name: str | None = None) -> dict:
    """
    获取产品/工厂档案摘要，包括历史验货次数、质量趋势、典型问题。

    返回: {
        "product_name": str,
        "factory_name": str | None,
        "inspection_count": int,
        "pass_rate": float,
        "typical_defects": [str, ...],
        "quality_trend": str,  # "上升"/"下降"/"稳定"
        "last_inspection": str
    }
    """
    try:
        client = _get_supabase()
        if client is None:
            return {"error": "Supabase 未配置"}

        if not product_name or not product_name.strip():
            return {"error": "请提供 product_name"}

        query = (
            client.table("inspection_reports")
            .select("factory_name, conclusion, defects, created_at")
            .ilike("product_name", f"%{product_name.strip()}%")
            .order("created_at", desc=True)
            .limit(30)
        )
        if factory_name and factory_name.strip():
            query = query.ilike("factory_name", f"%{factory_name.strip()}%")

        resp = query.execute()
        rows = resp.data or []
        if not rows:
            return {
                "product_name": product_name,
                "factory_name": factory_name,
                "inspection_count": 0,
                "message": "暂无历史记录",
            }

        total = len(rows)
        passed = sum(
            1 for r in rows if r.get("conclusion", "").replace(" ", "") in ("合格", "通过")
        )
        pass_rate = round(passed / total * 100, 1) if total > 0 else 0.0

        # 统计典型缺陷
        defect_counter: dict[str, int] = {}
        for r in rows:
            defects = r.get("defects", [])
            if isinstance(defects, str):
                try:
                    defects = json.loads(defects)
                except Exception:
                    defects = []
            for d in defects:
                t = d.get("type", "未知")
                defect_counter[t] = defect_counter.get(t, 0) + 1

        typical = sorted(defect_counter.items(), key=lambda x: -x[1])[:5]
        typical_defects = [t for t, _ in typical]

        # 质量趋势（最近5次 vs 更早5次）
        trend = "稳定"
        if total >= 6:
            recent = rows[:5]
            older = rows[5:10] if len(rows) > 5 else rows[5:]
            recent_pass = sum(
                1
                for r in recent
                if r.get("conclusion", "").replace(" ", "") in ("合格", "通过")
            )
            older_pass = sum(
                1
                for r in older
                if r.get("conclusion", "").replace(" ", "") in ("合格", "通过")
            )
            if len(older) > 0 and (recent_pass / len(recent)) > (older_pass / len(older)):
                trend = "上升"
            elif len(older) > 0 and (recent_pass / len(recent)) < (older_pass / len(older)) - 0.1:
                trend = "下降"

        return {
            "product_name": product_name,
            "factory_name": factory_name or "未指定",
            "inspection_count": total,
            "pass_rate": pass_rate,
            "typical_defects": typical_defects,
            "quality_trend": trend,
            "last_inspection": str(rows[0].get("created_at", ""))[:10],
        }
    except Exception as e:
        return {"error": f"获取产品档案失败: {str(e)}"}


# ============================================================================
# 工具注册表（供 Agent loop 使用）
# ============================================================================

TOOL_REGISTRY: dict[str, callable] = {
    "query_aql_plan": tool_query_aql_plan,
    "search_defect_history": tool_search_defect_history,
    "lookup_standard": tool_lookup_standard,
    "get_product_profile": tool_get_product_profile,
}

# JSON Schema 描述（供 function calling）
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "query_aql_plan",
            "description": "查询 ANSI Z1.4 抽样表，获取指定订单数量和 AQL 值对应的真实抽样方案（样本量、接收数Ac、拒收数Re）。在需要确定抽样数量或验收标准时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_quantity": {
                        "type": "integer",
                        "description": "订单总数量（正整数）",
                    },
                    "aql_value": {
                        "type": "string",
                        "description": "AQL 值，如 'AQL 2.5' 或 '2.5'",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["致命", "主要", "次要"],
                        "description": "缺陷严重程度，用于确认对应的 AQL 标准",
                    },
                },
                "required": ["order_quantity", "aql_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_defect_history",
            "description": "在历史验货记录中检索同类产品/工厂的缺陷模式。AI 需要参考历史来判断重点检查方向时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "产品名称（支持模糊匹配）",
                    },
                    "factory_name": {
                        "type": "string",
                        "description": "工厂名称（可选，缩小搜索范围）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回记录数量上限（默认5，最大20）",
                    },
                },
                "required": ["product_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_standard",
            "description": "查询指定产品类别的验货标准要点（国家标准、关键检查项、常见缺陷）。AI 需要了解某类产品该检查什么时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_category": {
                        "type": "string",
                        "description": "产品类别，如 '电子产品'、'纺织品/服装'、'玩具'、'机械配件'",
                    },
                },
                "required": ["product_category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_profile",
            "description": "获取某产品/工厂的验货档案摘要（历史次数、通过率、典型缺陷、质量趋势）。AI 在验货开始前了解该供应商历史表现时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "产品名称",
                    },
                    "factory_name": {
                        "type": "string",
                        "description": "工厂名称（可选）",
                    },
                },
                "required": ["product_name"],
            },
        },
    },
]
