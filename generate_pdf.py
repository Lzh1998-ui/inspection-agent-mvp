"""
PDF报告生成模块
使用reportlab生成专业验货报告，支持中文字体
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import os
from datetime import datetime

# ===== 注册中文字体 =====
def register_chinese_font():
    """注册中文字体，如果不存在则使用默认字体"""
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "SimHei.ttf")
    
    try:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont("SimHei", font_path))
            return "SimHei"
        else:
            # 尝试使用系统字体（Linux/Mac）
            system_fonts = [
                "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",  # Linux
                "/System/Library/Fonts/PingFang.ttc",  # Mac
                "C:\\Windows\\Fonts\\simhei.ttf",  # Windows
            ]
            for font in system_fonts:
                if os.path.exists(font):
                    pdfmetrics.registerFont(TTFont("Chinese", font))
                    return "Chinese"
            
            # 如果都没有，返回None（后续用ASCII替代）
            return None
    except Exception as e:
        print(f"字体加载失败: {e}")
        return None

# ===== 生成PDF报告 =====
def generate_inspection_pdf(report_data, uploaded_files):
    """
    生成验货报告PDF
    
    Args:
        report_data: dict，包含报告信息
        uploaded_files: list，上传的图片文件列表
    
    Returns:
        BytesIO: PDF文件的二进制流
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    # 注册字体
    chinese_font = register_chinese_font()
    font_name = chinese_font if chinese_font else "Helvetica"
    
    # 样式
    styles = getSampleStyleSheet()
    
    # 自定义样式（支持中文）
    title_style = ParagraphStyle(
        'ChineseTitle',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=18,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    
    heading_style = ParagraphStyle(
        'ChineseHeading',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=14,
        spaceAfter=6,
    )
    
    normal_style = ParagraphStyle(
        'ChineseNormal',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        spaceAfter=6,
    )
    
    # 故事（内容列表）
    story = []
    
    # ===== 第1页：标题 + 结论 =====
    # 标题
    title_text = "外贸验货报告" if chinese_font else "Inspection Report"
    story.append(Paragraph(title_text, title_style))
    story.append(Spacer(1, 0.5*cm))
    
    # 基本信息表格
    info_data = [
        ["报告编号", report_data.get("report_id", "N/A")],
        ["验货日期", report_data.get("inspection_date", "N/A")],
        ["产品名称", report_data.get("product_name", "N/A")],
        ["验货标准", report_data.get("inspection_standard", "N/A")],
        ["订单数量", str(report_data.get("order_quantity", "N/A"))],
        ["抽样数量", str(report_data.get("sample_size", "N/A"))],
    ]
    
    info_table = Table(info_data, colWidths=[4*cm, 8*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (0, -1), colors.grey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.lightgrey]),
    ]))
    
    story.append(info_table)
    story.append(Spacer(1, 0.5*cm))
    
    # 结论
    conclusion_text = f"验货结论：{report_data.get('conclusion', 'N/A')}"
    story.append(Paragraph(conclusion_text, heading_style))
    
    suggestion_text = "建议：接受该批次，但要求供应商改进包装，避免运输过程中产生划痕。标签错误需在出货前更正。"
    if not chinese_font:
        suggestion_text = "Suggestion: Accept the batch, but require supplier to improve packaging."
    
    story.append(Paragraph(suggestion_text, normal_style))
    story.append(Spacer(1, 1*cm))
    
    # ===== 第2页：缺陷清单 =====
    story.append(Paragraph("缺陷清单", heading_style))
    
    if report_data.get("defects"):
        defect_data = [["缺陷类型", "数量", "严重程度"]]
        for defect in report_data["defects"]:
            defect_data.append([
                defect.get("type", "N/A"),
                str(defect.get("quantity", "N/A")),
                defect.get("severity", "N/A")
            ])
        
        defect_table = Table(defect_data, colWidths=[4*cm, 3*cm, 3*cm])
        defect_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        
        story.append(defect_table)
    
    story.append(Spacer(1, 1*cm))
    
    # ===== 第3页：照片附件 =====
    story.append(Paragraph("照片附件", heading_style))
    
    # 插入图片（最多6张）
    if uploaded_files:
        img_count = 0
        img_row = []
        
        for img_file in uploaded_files[:6]:  # 最多6张
            try:
                img_file.seek(0)
                img = Image(img_file, width=5*cm, height=3.75*cm)  # 4:3比例
                img_row.append(img)
                img_count += 1
                
                if img_count % 2 == 0 or img_count == len(uploaded_files[:6]):
                    # 每行2张图片
                    img_table = Table([img_row], colWidths=[6*cm, 6*cm])
                    img_table.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ]))
                    story.append(img_table)
                    story.append(Spacer(1, 0.3*cm))
                    img_row = []
            except Exception as e:
                print(f"图片插入失败: {e}")
                continue
    
    # ===== 页脚 =====
    story.append(Spacer(1, 1*cm))
    footer_text = f"报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    if not chinese_font:
        footer_text = f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.grey,
    )
    story.append(Paragraph(footer_text, footer_style))
    
    # 生成PDF
    doc.build(story)
    buffer.seek(0)
    
    return buffer

# ===== 如果字体不存在，下载提示 =====
def check_font_available():
    """检查中文字体是否可用"""
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "SimHei.ttf")
    return os.path.exists(font_path)

if __name__ == "__main__":
    # 测试
    test_data = {
        "report_id": "RPT-20240609-012345",
        "product_name": "不锈钢保温杯",
        "inspection_date": "2024-06-09",
        "inspection_standard": "AQL 2.5",
        "order_quantity": 500,
        "sample_size": 50,
        "conclusion": "⚠️ 有条件通过（Minor Defects）",
        "defects": [
            {"type": "划痕", "quantity": 3, "severity": "轻微"},
            {"type": "标签错误", "quantity": 1, "severity": "中等"},
        ]
    }
    
    pdf_buffer = generate_inspection_pdf(test_data, [])
    
    with open("test_report.pdf", "wb") as f:
        f.write(pdf_buffer.read())
    
    print("测试PDF已生成：test_report.pdf")
