"""
PDF 生成模块 - 外贸验货报告
支持中文、图片嵌入、水印
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

# 尝试注册中文字体
FONT_AVAILABLE = False
FONT_PATHS = [
    "C:/Windows/Fonts/simhei.ttf",  # 黑体
    "C:/Windows/Fonts/simsun.ttc",  # 宋体
    "C:/Windows/Fonts/msyh.ttc",    # 微软雅黑
]

for path in FONT_PATHS:
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont("Chinese", path))
            FONT_AVAILABLE = True
            break
        except Exception:
            continue

def check_font_available():
    """检查中文字体是否可用"""
    return FONT_AVAILABLE

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
            canvas.setFont("Chinese", 60)
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
            fontName="Chinese",
            fontSize=18,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            "CustomHeading",
            parent=styles["Heading2"],
            fontName="Chinese",
            fontSize=14
        )
        
        normal_style = ParagraphStyle(
            "CustomNormal",
            parent=styles["Normal"],
            fontName="Chinese",
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
    
    if FONT_AVAILABLE:
        info_table = Table(info_data, colWidths=[4 * cm, 10 * cm])
        info_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Chinese"),
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
    
    conclusion = report_data.get("conclusion", "未知")
    conclusion_color = colors.black
    if "合格" in conclusion and "有条件" not in conclusion:
        conclusion_color = colors.green
    elif "不合格" in conclusion:
        conclusion_color = colors.red
    else:
        conclusion_color = colors.orange
    
    conclusion_para = Paragraph(f"<b>结论：</b>{conclusion}", normal_style)
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
                ("FONTNAME", (0, 0), (-1, -1), "Chinese"),
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
    
    if uploaded_files:
        for idx, file in enumerate(uploaded_files, 1):
            try:
                file.seek(0)
                img = PILImage.open(file)
                img_width, img_height = img.size
                max_width = 16 * cm
                ratio = max_width / img_width
                new_width = max_width
                new_height = img_height * ratio
                
                img_buffer = BytesIO()
                img.save(img_buffer, format="JPEG")
                img_buffer.seek(0)
                
                img_obj = Image(img_buffer, width=new_width, height=new_height)
                story.append(img_obj)
                story.append(Spacer(1, 0.3 * cm))
                
            except Exception as e:
                print(f"图片处理失败: {e}")
                continue
    
    # 生成 PDF（带水印）
    doc.build(
        story,
        onFirstPage=add_watermark,
        onLaterPages=add_watermark
    )
    
    buffer.seek(0)
    return buffer
