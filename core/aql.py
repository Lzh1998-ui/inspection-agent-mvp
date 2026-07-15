# -*- coding: utf-8 -*-
"""
core.aql - AQL 抽样标准表与判定引擎

依据 ANSI/ASQ Z1.4 (ISO 2859-1 / MIL-STD-105E) 单次抽样、正常检验、一般检查水平 II。
纯逻辑，无 UI 依赖，免费版与付费 Agent 版共享。

对外接口:
- get_aql_sample_info(order_quantity, aql_value) -> (sample_size, sample_code, ac, re)
- compute_three_layer_acre(order_quantity, aql_critical, aql_major, aql_minor) -> dict
- judge_three_layer(defects, acre) -> (three_layer_result, conclusion)
- format_acre_hint(acre) -> str
"""

# ===== AQL 标准表(简化版 ANSI/ASQ Z1.4 / ISO 2859-1)=====
# 样本量代码表(根据订单数量查表)
AQL_SAMPLE_SIZE_CODE = {
    # 订单数量范围 : 样本量代码
    (2, 8): "A",
    (9, 15): "B",
    (16, 25): "C",
    (26, 50): "D",
    (51, 90): "E",
    (91, 150): "F",
    (151, 280): "G",
    (281, 500): "H",
    (501, 1200): "J",
    (1201, 3200): "K",
    (3201, 10000): "L",
    (10001, 35000): "M",
    (35001, 150000): "N",
    (150001, 500000): "P",
    (500001, float('inf')): "Q"
}

# 样本量代码对应的实际抽样数量
AQL_SAMPLE_SIZE = {
    "A": 2, "B": 3, "C": 5, "D": 8, "E": 13,
    "F": 20, "G": 32, "H": 50, "J": 80, "K": 125,
    "L": 200, "M": 315, "N": 500, "P": 800, "Q": 1250
}

# Ac/Re 表(接收数/拒收数)
# 格式:{样本量代码: {AQL值: (Ac, Re)}}
# 依据 ANSI/ASQ Z1.4 (ISO 2859-1 / MIL-STD-105E) 单次抽样、正常检验、一般检查水平 II
# Ac 序列沿对角线遵循标准接收数序列 [0,1,2,3,5,7,10,14,21],Re = Ac + 1
# 说明:小样本量(A/B/C/D)在低 AQL 处标准表为箭头(指向更大样本方案),
#      此处取保守值 Ac=0(Re=1),即"发现1个即拒收",偏严格更安全。
AQL_AC_RE = {
    "A": {  # n=2
        "AQL 0.65": (0, 1), "AQL 1.0": (0, 1), "AQL 1.5": (0, 1),
        "AQL 2.5": (0, 1), "AQL 4.0": (0, 1), "AQL 6.5": (0, 1)
    },
    "B": {  # n=3
        "AQL 0.65": (0, 1), "AQL 1.0": (0, 1), "AQL 1.5": (0, 1),
        "AQL 2.5": (0, 1), "AQL 4.0": (0, 1), "AQL 6.5": (0, 1)
    },
    "C": {  # n=5
        "AQL 0.65": (0, 1), "AQL 1.0": (0, 1), "AQL 1.5": (0, 1),
        "AQL 2.5": (0, 1), "AQL 4.0": (0, 1), "AQL 6.5": (1, 2)
    },
    "D": {  # n=8
        "AQL 0.65": (0, 1), "AQL 1.0": (0, 1), "AQL 1.5": (0, 1),
        "AQL 2.5": (0, 1), "AQL 4.0": (1, 2), "AQL 6.5": (1, 2)
    },
    "E": {  # n=13
        "AQL 0.65": (0, 1), "AQL 1.0": (0, 1), "AQL 1.5": (0, 1),
        "AQL 2.5": (1, 2), "AQL 4.0": (1, 2), "AQL 6.5": (2, 3)
    },
    "F": {  # n=20
        "AQL 0.65": (0, 1), "AQL 1.0": (0, 1), "AQL 1.5": (1, 2),
        "AQL 2.5": (1, 2), "AQL 4.0": (2, 3), "AQL 6.5": (3, 4)
    },
    "G": {  # n=32
        "AQL 0.65": (0, 1), "AQL 1.0": (1, 2), "AQL 1.5": (1, 2),
        "AQL 2.5": (2, 3), "AQL 4.0": (3, 4), "AQL 6.5": (5, 6)
    },
    "H": {  # n=50
        "AQL 0.65": (1, 2), "AQL 1.0": (1, 2), "AQL 1.5": (2, 3),
        "AQL 2.5": (3, 4), "AQL 4.0": (5, 6), "AQL 6.5": (7, 8)
    },
    "J": {  # n=80
        "AQL 0.65": (1, 2), "AQL 1.0": (2, 3), "AQL 1.5": (3, 4),
        "AQL 2.5": (5, 6), "AQL 4.0": (7, 8), "AQL 6.5": (10, 11)
    },
    "K": {  # n=125
        "AQL 0.65": (2, 3), "AQL 1.0": (3, 4), "AQL 1.5": (5, 6),
        "AQL 2.5": (7, 8), "AQL 4.0": (10, 11), "AQL 6.5": (14, 15)
    },
    "L": {  # n=200
        "AQL 0.65": (3, 4), "AQL 1.0": (5, 6), "AQL 1.5": (7, 8),
        "AQL 2.5": (10, 11), "AQL 4.0": (14, 15), "AQL 6.5": (21, 22)
    },
    "M": {  # n=315
        "AQL 0.65": (5, 6), "AQL 1.0": (7, 8), "AQL 1.5": (10, 11),
        "AQL 2.5": (14, 15), "AQL 4.0": (21, 22), "AQL 6.5": (21, 22)
    },
    "N": {  # n=500
        "AQL 0.65": (7, 8), "AQL 1.0": (10, 11), "AQL 1.5": (14, 15),
        "AQL 2.5": (21, 22), "AQL 4.0": (21, 22), "AQL 6.5": (21, 22)
    },
    "P": {  # n=800
        "AQL 0.65": (10, 11), "AQL 1.0": (14, 15), "AQL 1.5": (21, 22),
        "AQL 2.5": (21, 22), "AQL 4.0": (21, 22), "AQL 6.5": (21, 22)
    },
    "Q": {  # n=1250
        "AQL 0.65": (14, 15), "AQL 1.0": (21, 22), "AQL 1.5": (21, 22),
        "AQL 2.5": (21, 22), "AQL 4.0": (21, 22), "AQL 6.5": (21, 22)
    },
}


def get_aql_sample_info(order_quantity, aql_value):
    """
    根据订单数量和 AQL 值,查询样本量和 Ac/Re
    返回: (sample_size, sample_code, ac, re)
    """
    # 1. 查询样本量代码
    sample_code = "C"  # 默认值
    for (min_q, max_q), code in AQL_SAMPLE_SIZE_CODE.items():
        if min_q <= order_quantity <= max_q:
            sample_code = code
            break

    # 2. 查询样本量
    sample_size = AQL_SAMPLE_SIZE.get(sample_code, 50)

    # 3. 查询 Ac/Re
    ac_re_table = AQL_AC_RE.get(sample_code, {})
    ac, rej = ac_re_table.get(aql_value, (0, 1))

    return sample_size, sample_code, ac, rej


def compute_three_layer_acre(order_quantity, aql_critical, aql_major, aql_minor):
    """
    根据订单数量和三层 AQL 值,分别计算每层的真实 Ac/Re。
    返回: {"critical": {"aql":.., "ac":.., "re":.., "sample_size":..}, "major":..., "minor":...}
    """
    layers = {}
    for key, aql in (("critical", aql_critical), ("major", aql_major), ("minor", aql_minor)):
        sample_size, sample_code, ac, rej = get_aql_sample_info(order_quantity, aql)
        layers[key] = {
            "aql": aql,
            "ac": ac,
            "re": rej,
            "sample_size": sample_size,
            "sample_code": sample_code,
        }
    return layers


def judge_three_layer(defects, acre):
    """
    基于 AI 识别的缺陷列表 + 真实 Ac/Re,确定性地得出三层判定与总结论。
    返回: (three_layer_result, conclusion)
    """
    sev_map = {"致命": "critical", "主要": "major", "次要": "minor"}
    counts = {"critical": 0, "major": 0, "minor": 0}
    for d in (defects or []):
        sev = d.get("severity", "次要")
        layer = sev_map.get(sev)
        if layer:
            try:
                counts[layer] += int(d.get("quantity", 1) or 1)
            except (TypeError, ValueError):
                counts[layer] += 1

    three_layer_result = {}
    all_passed = True
    conditional = False
    for layer in ("critical", "major", "minor"):
        info = acre.get(layer, {})
        ac = info.get("ac", 0)
        # 致命缺陷零容忍:不论抽样表 Ac 为多少,发现任何致命缺陷即不合格(验货行业惯例)
        if layer == "critical":
            ac = 0
        cnt = counts[layer]
        passed = cnt <= ac
        if not passed:
            all_passed = False
        # 临界:次要层刚好等于 Ac(未超但已到上限)且 Ac>0
        if layer == "minor" and passed and ac > 0 and cnt == ac:
            conditional = True
        three_layer_result[layer] = {
            "passed": passed,
            "aql": info.get("aql", ""),
            "defect_count": cnt,
            "ac": ac,
            "re": info.get("re", ac + 1),
        }

    if not all_passed:
        conclusion = "不合格"
    elif conditional:
        conclusion = "有条件接受"
    else:
        conclusion = "合格"
    return three_layer_result, conclusion


def format_acre_hint(acre):
    """将三层真实 Ac/Re 格式化为注入 AI prompt 的文本提示"""
    if not acre:
        return ""
    c, m, n = acre.get("critical", {}), acre.get("major", {}), acre.get("minor", {})
    ss = c.get("sample_size", "?")
    return (
        f"\n【本次抽样方案】抽样数量:{ss} 件\n"
        f"- 致命缺陷 {c.get('aql','')}:接收数 Ac={c.get('ac',0)}(缺陷数≤{c.get('ac',0)}通过)\n"
        f"- 主要缺陷 {m.get('aql','')}:接收数 Ac={m.get('ac',0)}(缺陷数≤{m.get('ac',0)}通过)\n"
        f"- 次要缺陷 {n.get('aql','')}:接收数 Ac={n.get('ac',0)}(缺陷数≤{n.get('ac',0)}通过)\n"
    )
