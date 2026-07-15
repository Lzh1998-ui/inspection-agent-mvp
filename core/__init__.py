# -*- coding: utf-8 -*-
"""
core - 验货系统共享内核（UI 无关，纯逻辑）

子模块:
- core.aql : AQL 抽样标准表与三层判定引擎(ANSI/ASQ Z1.4 / ISO 2859-1)
- core.pdf : 验货报告 PDF 生成(中文字体、水印、AQL 表格)
- core.ai  : AI 视觉分析封装(qwen-vl/deepseek/openai 客户端 + 结果解析)

设计原则:纯逻辑、无 UI/无副作用，免费版(app_free)与付费 Agent 版(app_pro)共同引用。

注意:请从子模块显式导入(如 `from core.aql import ...`)，本包不做跨子模块的
预加载，以免仅需 AQL 逻辑时被迫加载 reportlab 等重依赖。
"""
