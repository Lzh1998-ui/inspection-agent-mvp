"""
PDF 生成模块 - 外贸验货报告
支持中文、图片嵌入、水印

=== 2026-07-11 修复说明 ===
1. 【中文字体】原代码查找 "fonts/simhei.ttf"（全小写），但仓库实际文件为
   "fonts/SimHei.ttf"（大写 S/H）。Linux（Streamlit Cloud）区分大小写，
   导致字体加载失败、中文显示为 ■。已补全大小写正确的路径。
2. 【AQL 表格】原代码把 three_layer_result["critical"] 当作字符串 str(dict)
   直接塞进表格，导致 PDF 中出现 {'passed': False, ...} 原始字典。
   已改为正确提取 passed / aql / defect_count 字段。
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import Color
import os
from io import BytesIO
from PIL import Image as PILImage

# A4 页面尺寸（单位：points，1 inch = 72 points）
PAGE_WIDTH, PAGE_HEIGHT = A4
# 边距
MARGIN = 2 * cm
# 可用内容区域
AVAILABLE_WIDTH = PAGE_WIDTH - 2 * MARGIN
AVAILABLE_HEIGHT = PAGE_HEIGHT - 2 * MARGIN

# 尝试注册中文字体（优先级：项目目录 > Windows 系统目录）
FONT_AVAILABLE = False
FONT_NAME = "Chinese"
FONT_SOURCE = None

# 1. 首先尝试项目目录下的 fonts/ 文件夹（推荐方式，用于 Streamlit Cloud）
#    ⚠️ 注意大小写：仓库实际文件名是 SimHei.ttf / SourceHanSansCN-Regular.otf
#    Linux 文件系统区分大小写，必须用正确大小写，否则加载失败。
PROJECT_FONT_PATHS = [
    # 实际存在于仓库中的文件（大小写必须精确匹配）
    "fonts/SimHei.ttf",                       # ✅ 仓库真实文件
    "SimHei.ttf",                             # 根目录也有一份
    "fonts/SourceHanSansCN-Regular.otf",      # ✅ 仓库真实文件
    "SourceHanSansCN-Regular.otf",            # 根目录也有一份
    # 其他常见开源字体（按需补充）
    "fonts/NotoSansCJK-Regular.ttc",
    "fonts/NotoSansCJK-Regular.otf",
    "fonts/SourceHanSansCN-Regular.ttf",
    "fonts/wqy-microhei.ttc",
    "fonts/wqy-zenhei.ttc",
    "fonts/simsun.ttc",
]

# 2. 备用：Windows 系统字体（本地开发环境，Windows 不区分大小写）
SYSTEM_FONT_PATHS = [
    "C:/Windows/Fonts/simhei.ttf",  # 黑体
    "C:/Windows/Fonts/simsun.ttc",  # 宋体
    "C:/Windows/Fonts/msyh.ttc",    # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",  # 微软雅黑粗体
]

# 合并所有字体路径（项目目录优先）
ALL_FONT_PATHS = PROJECT_FONT_PATHS + SYSTEM_FONT_PATHS

for path in ALL_FONT_PATHS:
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, path))
            FONT_AVAILABLE = True
            FONT_SOURCE = path
            print(f"✅ 成功加载中文字体: {path}")
            break
        except Exception as e:
            print(f"⚠️ 字体加载失败 {path}: {e}")
            continue

if not FONT_AVAILABLE:
    print("❌ 未找到任何中文字体，PDF 中文将显示为空白方块（■）")


def check_font_available():
    """检查中文字体是否可用"""
    return FONT_AVAILABLE


def get_font_warning_message():
    """获取字体警告信息"""
    if FONT_AVAILABLE:
        return None
    return """
    ⚠️ **未检测到中文字体，PDF可能显示为英文**

    **解决方案：**
    1. 下载开源中文字体（推荐思源黑体）
       - 地址：https://github.com/adobe-fonts/source-han-sans/releases
       - 下载 `SourceHanSansCN-Regular.otf`

    2. 在项目根目录创建 `fonts/` 文件夹

    3. 将字体文件放入 `fonts/` 目录

    4. 重新部署即可

    **备用字体下载：**
    - 文泉驿微米黑：https://sourceforge.net/projects/wqy/files/wqy-microhei/
    - Google Noto CJK：https://fonts.google.com/noto/fonts?noto.query=chinese
    """


def add_watermark(canvas, doc):
    """
    添加水印到每一页
    水印内容："仅限内部使用"
    样式：半透明斜体
    """
    canvas.saveState()

    # 设置字体（斜体）
    if FONT_AVAILABLE:
        try:
            canvas.setFont(FONT_NAME, 60)
        except Exception:
            canvas.setFont("Helvetica-BoldOblique", 60)
    else:
        canvas.setFont("Helvetica-BoldOblique", 60)

    # 设置浅灰色模拟半透明效果
    canvas.setFillColorRGB(0.85, 0.85, 0.85)

    # 旋转画布 45 度
    canvas.rotate(45)

    # 在页面对角线位置绘制水印
    x = -300
    y = -100

    # 绘制多行水印，覆盖整个页面
    for i in range(-2, 3):
        for j in range(-2, 3):
            canvas.drawString(x + i * 300, y + j * 200, "仅限内部使用")

    canvas.restoreState()


def resize_image_to_fit(img_width, img_height, max_width, max_height):
    """
    计算图片缩放后的尺寸，确保不超出指定边界

    参数:
        img_width: 原始图片宽度
        img_height: 原始图片高度
        max_width: 最大允许宽度
        max_height: 最大允许高度

    返回:
        (new_width, new_height): 缩放后的尺寸
    """
    # 初始按宽度缩放
    ratio = max_width / img_width
    new_width = max_width
    new_height = img_height * ratio

    # 如果高度超出，再按高度缩放
    if new_height > max_height:
        ratio = max_height / new_height
        new_width = new_width * ratio
        new_height = max_height

    return new_width, new_height


def _extract_layer(layer_dict, default_aql):
    """
    从 three_layer_result 的某一层（critical/major/minor）安全提取字段。
    兼容两种数据格式：
      A) dict: {"passed": bool, "aql": "AQL X.X", "defect_count": int}
      B) str / bool: 直接为判定结果
    """
    if not isinstance(layer_dict, dict):
        # 兼容旧格式：直接传了字符串或布尔
        if isinstance(layer_dict, bool):
            return default_aql, "通过" if layer_dict else "不通过", 0
        return default_aql, str(layer_dict), 0

    aql = layer_dict.get("aql", default_aql)
    passed = layer_dict.get("passed", False)
    result = "通过" if passed else "不通过"
    count = layer_dict.get("defect_count", layer_dict.get("count", 0))
    return aql, result, count


def generate_inspection_pdf(report_data, uploaded_files):
    """
    生成验货报告 PDF

    参数:
        report_data: dict, 报告数据
        uploaded_files: list, 上传的图片文件列表

    返回:
        BytesIO: PDF 二进制数据
    """
    buffer = BytesIO()

    # 创建 PDF 文档
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm
    )

    # 样式
    styles = getSampleStyleSheet()

    if FONT_AVAILABLE:
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontName=FONT_NAME,
            fontSize=18,
            alignment=TA_CENTER
        )

        heading_style = ParagraphStyle(
            "CustomHeading",
            parent=styles["Heading2"],
            fontName=FONT_NAME,
            fontSize=14
        )

        normal_style = ParagraphStyle(
            "CustomNormal",
            parent=styles["Normal"],
            fontName=FONT_NAME,
            fontSize=10
        )
    else:
        title_style = styles["Heading1"]
        heading_style = styles["Heading2"]
        normal_style = styles["Normal"]

    # 内容列表
    story = []

    # 标题
    story.append(Paragraph("验货报告", title_style))
    story.append(Spacer(1, 0.5 * cm))

    # 报告基本信息
    info_data = [
        ["报告编号", report_data.get("report_id", "N/A")],
        ["产品名称", report_data.get("product_name", "N/A")],
        ["验货日期", report_data.get("inspection_date", "N/A")],
        ["验货标准", report_data.get("inspection_standard", "N/A")],
        ["订单数量", str(report_data.get("order_quantity", "N/A"))],
        ["抽样数量", str(report_data.get("sample_size", "N/A"))]
    ]

    # 添加 AQL 信息（如果存在）
    if "aql_info" in report_data:
        aql_info = report_data["aql_info"]
        info_data.append(["样本量代码", aql_info.get("sample_code", "N/A")])
        info_data.append(["致命缺陷(AQL 1.0)", f"Ac={aql_info.get('critical_ac', 'N/A')}, Re={aql_info.get('critical_re', 'N/A')}"])
        info_data.append(["主要缺陷(AQL 2.5)", f"Ac={aql_info.get('major_ac', 'N/A')}, Re={aql_info.get('major_re', 'N/A')}"])
        info_data.append(["次要缺陷(AQL 4.0)", f"Ac={aql_info.get('minor_ac', 'N/A')}, Re={aql_info.get('minor_re', 'N/A')}"])

    if FONT_AVAILABLE:
        info_table = Table(info_data, colWidths=[4 * cm, 10 * cm])
        info_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey)
        ]))
    else:
        info_table = Table(info_data, colWidths=[4 * cm, 10 * cm])
        info_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey)
        ]))

    story.append(info_table)
    story.append(Spacer(1, 0.5 * cm))

    # 验货结论
    story.append(Paragraph("1. 验货结论", heading_style))

    # 三层 AQL 结果（如果存在）
    if "three_layer_result" in report_data:
        three_layer = report_data["three_layer_result"]
        story.append(Paragraph("<b>三层 AQL 判定结果：</b>", normal_style))

        # === 修复：从 dict 中正确提取字段，避免显示原始字典 ===
        crit_aql, crit_res, crit_cnt = _extract_layer(three_layer.get("critical"), "1.0")
        maj_aql,  maj_res,  maj_cnt  = _extract_layer(three_layer.get("major"), "2.5")
        min_aql,  min_res,  min_cnt  = _extract_layer(three_layer.get("minor"), "4.0")

        layer_data = [
            ["缺陷层级", "AQL 值", "判定结果", "发现数量"],
            ["致命缺陷", str(crit_aql), crit_res, str(crit_cnt)],
            ["主要缺陷", str(maj_aql),  maj_res,  str(maj_cnt)],
            ["次要缺陷", str(min_aql),  min_res,  str(min_cnt)]
        ]

        if FONT_AVAILABLE:
            layer_table = Table(layer_data, colWidths=[3 * cm, 3 * cm, 4 * cm, 4 * cm])
            layer_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER")
            ]))
        else:
            layer_table = Table(layer_data, colWidths=[3 * cm, 3 * cm, 4 * cm, 4 * cm])
            layer_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER")
            ]))

        story.append(layer_table)
        story.append(Spacer(1, 0.3 * cm))

    conclusion = report_data.get("conclusion", "未知")
    conclusion_para = Paragraph(f"<b>综合结论：</b>{conclusion}", normal_style)
    story.append(conclusion_para)
    story.append(Spacer(1, 0.3 * cm))

    recommendation = report_data.get("recommendation", "暂无建议")
    recommendation_para = Paragraph(f"<b>建议：</b>{recommendation}", normal_style)
    story.append(recommendation_para)
    story.append(Spacer(1, 0.5 * cm))

    # 缺陷清单
    story.append(Paragraph("2. 缺陷清单", heading_style))

    defects = report_data.get("defects", [])
    if defects:
        defect_data = [["序号", "缺陷类型", "数量", "严重程度"]]

        for idx, defect in enumerate(defects, 1):
            defect_data.append([
                str(idx),
                defect.get("type", "未知"),
                str(defect.get("quantity", 0)),
                defect.get("severity", "未知")
            ])

        if FONT_AVAILABLE:
            defect_table = Table(defect_data, colWidths=[2 * cm, 5 * cm, 3 * cm, 4 * cm])
            defect_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
            ]))
        else:
            defect_table = Table(defect_data, colWidths=[2 * cm, 5 * cm, 3 * cm, 4 * cm])
            defect_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
            ]))

        story.append(defect_table)
    else:
        story.append(Paragraph("未发现明显缺陷", normal_style))

    story.append(Spacer(1, 0.5 * cm))

    # 照片附件
    story.append(Paragraph("3. 照片附件", heading_style))

    # 图片最大尺寸限制（预留一些边距）
    max_img_width = AVAILABLE_WIDTH
    max_img_height = AVAILABLE_HEIGHT * 0.7  # 图片最多占页面高度的70%

    if uploaded_files:
        for idx, file in enumerate(uploaded_files, 1):
            try:
                file.seek(0)
                img = PILImage.open(file)
                img_width, img_height = img.size

                # 使用自适应缩放函数
                new_width, new_height = resize_image_to_fit(
                    img_width, img_height,
                    max_img_width, max_img_height
                )

                img_buffer = BytesIO()

                # 处理 RGBA 模式图片（转换为 RGB）
                if img.mode == 'RGBA':
                    # 创建白色背景
                    background = PILImage.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])  # 使用 alpha 通道作为 mask
                    background.save(img_buffer, format="JPEG", quality=85)
                else:
                    img.save(img_buffer, format="JPEG", quality=85)

                img_buffer.seek(0)

                img_obj = Image(img_buffer, width=new_width, height=new_height)
                story.append(img_obj)
                story.append(Spacer(1, 0.3 * cm))

            except Exception as e:
                print(f"图片 {idx} 处理失败: {e}")
                # 添加错误提示到 PDF
                story.append(Paragraph(f"[图片 {idx} 处理失败]", normal_style))
                story.append(Spacer(1, 0.3 * cm))
                continue
    else:
        story.append(Paragraph("无照片附件", normal_style))

    # 生成 PDF（带水印）
    doc.build(
        story,
        onFirstPage=add_watermark,
        onLaterPages=add_watermark
    )

    buffer.seek(0)
    return buffer
