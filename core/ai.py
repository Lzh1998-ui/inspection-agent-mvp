# -*- coding: utf-8 -*-
"""
core.ai - AI 视觉分析封装（UI 无关）

职责:
- build_ai_client(): 按密钥构建 OpenAI 兼容客户端(qwen-vl / deepseek / openai)
- analyze_images(): 传入客户端 + 图片字节 + 三层 Ac/Re, 返回结构化验货结果
- JSON 鲁棒解析辅助(clean_json_string / extract_balanced_json / extract_json_robust)

设计原则: 不依赖 streamlit, 密钥与图片字节由调用方(app_free / app_pro)注入。
"""

import base64
import json
import re

import openai
import httpx

from core.aql import judge_three_layer, format_acre_hint

DEFAULT_TIMEOUT_SECONDS = 60


def clean_json_string(s):
    """清理 JSON 字符串中的常见格式问题"""
    if not s:
        return s
    # 1. 移除末尾逗号(在 } 或 ] 之前)
    s = re.sub(r',\s*([}\]])', r'\1', s)
    # 2. 移除单引号包裹的字符串值(JSON 要求双引号)
    # 这是一个保守的修复,只处理明显的单引号问题
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
                return False, f"JSON 解析失败:{str(e)}\n提取内容:{json_str[:200]}"
    # ===== 所有策略都失败 =====
    return False, f"无法解析 AI 返回的 JSON。原始响应前 200 字符:\n{raw_response[:200]}"


def build_ai_client(qwen_key=None, deepseek_key=None, openai_key=None,
                    timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    """
    根据传入的密钥构建 AI 客户端（纯逻辑，不读取任何 UI/secrets）。
    优先级:通义千问VL > DeepSeek > OpenAI
    返回: (client, model_name) 或 (None, error_message)
    """
    try:
        if qwen_key:
            client = openai.OpenAI(
                api_key=qwen_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            )
            return client, "qwen-vl-plus"
        if deepseek_key:
            client = openai.OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com",
                timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            )
            return client, "deepseek-chat"
        if openai_key:
            client = openai.OpenAI(
                api_key=openai_key,
                timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            )
            return client, "gpt-4o"
        return None, "未配置API Key,请在 Streamlit Cloud Secrets 中配置 qwen/deepseek/openai 的 api_key"
    except Exception as e:
        return None, f"API客户端初始化失败:{str(e)}"


def analyze_images(client, model_name, image_bytes_list, product_name,
                   inspection_standard, acre=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    """
    调用 AI Vision API 分析产品图片
    返回: (success, result_or_error_message)
    acre: compute_three_layer_acre() 的返回值,用于向 AI 注入真实 Ac/Re 并做最终判定
    """
    try:

        # 3. 构建消息
        messages = [
            {
"role": "system",
"content": """你是一位拥有15年经验的外贸验货专家,精通ISO 2859-1/2抽样标准、AQL质量标准(AQL 0.65/1.0/1.5/2.5/4.0/6.5),熟悉电子产品、纺织品、机械配件、玩具等各类产品的国际质量标准(ISO、ASTM、GB、EN等)。
你的任务是根据用户上传的产品图片和指定的AQL标准,进行专业的质量检验分析。

用户上传了多张图片,按顺序编号为:图1、图2、图3...。
在描述缺陷时,请用"图1"、"图2"这样的编号指明缺陷出现在哪张图片中。

【AQL三层抽样标准】
用户会提供一个三层AQL标准,格式为:"致命:AQL X.X / 主要:AQL Y.Y / 次要:AQL Z.Z"

请根据缺陷严重程度分类:
1. **致命缺陷 (Critical)**:安全风险、违法、危及生命 - 使用 AQL X.X 判定
2. **主要缺陷 (Major)**:功能失效、影响使用、关键尺寸偏差 - 使用 AQL Y.Y 判定
3. **次要缺陷 (Minor)**:外观瑕疵、不影响功能、包装问题 - 使用 AQL Z.Z 判定

【三层判定标准--基于真实 AQL 抽样方案】
判定依据 ANSI/ASQ Z1.4 抽样表的接收数 Ac:某层缺陷总数 ≤ Ac → 该层通过;> Ac → 不通过。
(具体 Ac 数值会在下方用户消息中给出,请客观识别并统计缺陷数量,不要自己冇断合格与否。)

【最终结论】
你只需按格式返回每个缺陷的严重程度与数量;最终合格/不合格由系统根据真实 Ac/Re 计算,three_layer_result 的 passed 字段你可估算填写。

【输出格式要求】必须严格按以下JSON格式返回:
{
  "conclusion": "合格/不合格/有条件接受",
  "three_layer_result": {
    "critical": {"passed": true/false, "aql": "AQL X.X", "defect_count": 数字},
    "major": {"passed": true/false, "aql": "AQL Y.Y", "defect_count": 数字},
    "minor": {"passed": true/false, "aql": "AQL Z.Z", "defect_count": 数字}
  },
  "defects": [
    {
      "type": "划痕/变形/色差/功能异常/包装破损等",
      "quantity": 数字(必须是整数),
      "severity": "致命/主要/次要",
      "description": "详细描述缺陷位置、大小、程度(50字以内)",
      "image": "图1 / 图2 / 图3"
    }
  ],
  "recommendation": "处理建议(100字以内)",
  "confidence": 0.0-1.0
}

【注意事项】
[注意] quantity字段必须是整数数字,禁止使用"若干"、"一些"、"多个"等模糊词汇
[注意] 请确保输出标准 JSON 格式,不要使用尾逗号,字符串使用双引号
[注意] 如果图片不清晰,description中注明"图片模糊,无法准确判断"
[注意] 不要编造图片中不存在的缺陷
[注意] 如果未发现缺陷,defects数组设为空 []
"""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"请分析这款产品:{product_name}\n验货标准:{inspection_standard}\n"
                            + (format_acre_hint(acre) if acre else "")
                            + "\n请识别图片中的缺陷,输出JSON格式结果。"
                        )
                    }
                ]
            }
        ]

        # 4. 添加图片
        for image_bytes in image_bytes_list:
            # 图片按上传顺序编号,AI 在分析时引用 "图1/图2/图3" 对应缺陷
            try:
                image_b64 = base64.b64encode(image_bytes).decode('utf-8')

                messages[1]["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}"
                    }
                })
            except Exception as img_error:
                return False, f"图片处理失败:{str(img_error)}"

        # 5. 调用 API
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=1000,
                temperature=0.3
            )
        except openai.APIConnectionError:
            return False, "网络连接失败,请检查网络后重试"
        except openai.APITimeoutError:
            return False, f"API 调用超时({timeout_seconds}秒),请稍后重试"
        except openai.RateLimitError:
            return False, "API 调用频率超限,请等待1分钟后重试"
        except openai.AuthenticationError:
            return False, "API Key 认证失败,请检查密钥是否正确"
        except openai.APIStatusError as e:
            return False, f"API 错误:{e.message}(状态码:{e.status_code})"

        # 6. 解析响应(使用增强版解析器)
        ai_response = response.choices[0].message.content

        # 使用增强版 JSON 解析(支持多层 fallback)
        success, result = extract_json_robust(ai_response)

        if not success:
            return False, result

        # 7. 解析 JSON(支持 markdown 代码块包裹)
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
                        return False, f"AI 返回格式错误,无法解析 JSON。原始响应:{ai_response[:200]}..."
            else:
                # 尝试直接提取 {...}
                json_match3 = re.search(r'\{.*\}', ai_response, re.DOTALL)
                if json_match3:
                    try:
                        result = json.loads(json_match3.group())
                    except json.JSONDecodeError:
                        return False, f"AI 返回格式错误,无法解析 JSON。原始响应:{ai_response[:200]}..."
                else:
                    return False, f"AI 返回格式错误,未找到 JSON 内容。原始响应:{ai_response[:200]}..."

        # 8. 校验必需字段
        required_fields = ["conclusion", "defects", "recommendation"]
        for field in required_fields:
            if field not in result:
                return False, f"AI 返回数据缺少必需字段:{field}"

        # 9. 校验 defects 格式
        if not isinstance(result["defects"], list):
            return False, "AI 返回的 defects 字段格式错误(应为数组)"

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

        # 11. 【关键】基于真实 Ac/Re 确定性重算三层判定与总结论,覆盖 AI 冇断
        if acre:
            three_layer_result, conclusion = judge_three_layer(result.get("defects", []), acre)
            result["three_layer_result"] = three_layer_result
            result["conclusion"] = conclusion

        return True, result

    except Exception as e:
        return False, f"AI 分析过程发生未知错误:{str(e)}"
