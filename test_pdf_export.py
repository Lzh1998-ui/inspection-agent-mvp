"""
测试脚本：验证PDF导出功能
运行方式：streamlit run test_pdf_export.py
"""

import streamlit as st
from generate_pdf import generate_inspection_pdf, check_font_available
from datetime import datetime
from io import BytesIO

st.set_page_config(page_title="PDF导出测试", page_icon="🧪")

st.title("🧪 PDF导出功能测试")

# 测试数据
test_report = {
    "report_id": f"TEST-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    "product_name": "测试产品-不锈钢保温杯",
    "inspection_date": datetime.now().strftime("%Y-%m-%d"),
    "inspection_standard": "AQL 2.5",
    "order_quantity": 500,
    "sample_size": 50,
    "conclusion": "⚠️ 有条件通过（Minor Defects）",
    "defects": [
        {"type": "划痕", "quantity": 3, "severity": "轻微"},
        {"type": "标签错误", "quantity": 1, "severity": "中等"},
    ],
    "savings": 350
}

# 测试1：检查字体
st.subheader("测试1：中文字体检查")
font_available = check_font_available()

if font_available:
    st.success("✅ 中文字体已加载（SimHei.ttf）")
else:
    st.error("❌ 未找到中文字体文件")
    st.info("💡 请将 SimHei.ttf 放到 fonts/ 目录下")

st.markdown("---")

# 测试2：生成PDF
st.subheader("测试2：PDF生成测试")

if st.button("🚀 生成测试PDF", type="primary"):
    with st.spinner("正在生成PDF..."):
        try:
            # 模拟上传文件（使用空列表，不嵌入图片）
            pdf_buffer = generate_inspection_pdf(test_report, [])
            
            st.success("✅ PDF生成成功！")
            
            # 提供下载
            pdf_filename = f"测试报告_{test_report['product_name']}_{test_report['report_id']}.pdf"
            
            st.download_button(
                label="📥 下载测试PDF",
                data=pdf_buffer,
                file_name=pdf_filename,
                mime="application/pdf",
                use_container_width=True
            )
            
            # 显示报告数据
            st.markdown("### 📋 测试报告数据")
            st.json(test_report)
            
        except Exception as e:
            st.error(f"❌ PDF生成失败：{str(e)}")
            st.exception(e)

st.markdown("---")

# 测试3：检查依赖
st.subheader("测试3：依赖检查")

try:
    import reportlab
    st.success(f"✅ reportlab 已安装（版本：{reportlab.Version}）")
except ImportError:
    st.error("❌ reportlab 未安装，请运行：pip install reportlab")

try:
    from PIL import Image
    st.success("✅ Pillow 已安装")
except ImportError:
    st.error("❌ Pillow 未安装，请运行：pip install Pillow")

st.markdown("---")

# 使用说明
st.subheader("📖 使用说明")
st.info("""
1. 点击"生成测试PDF"按钮
2. 等待3-5秒，PDF将自动生成
3. 点击"下载测试PDF"保存到本地
4. 打开PDF检查：
   - ✅ 中文是否正常显示
   - ✅ 表格是否完整
   - ✅ 布局是否正确
""")

# 页脚
st.markdown("---")
st.caption("测试脚本 v1.0 | 用于验证 PDF 导出功能")
