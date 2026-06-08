# 中文字体目录

## 用途
存放PDF生成所需的中文字体文件（TTF格式）。

## 使用方法

1. **下载中文字体**（任选其一）：
   - SimHei（黑体）：[下载链接](https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf)
   - Noto Sans CJK：[Google Fonts](https://github.com/googlefonts/noto-cjk)
   - WenQuanYi Micro Hei：[开源字体](http://wenq.org/)

2. **放置字体文件**：
   将下载的 `.ttf` 文件重命名为 `SimHei.ttf`，放到本目录。

3. **重新部署**：
   推送到 GitHub 后，Streamlit Cloud 会自动重新部署，PDF即可支持中文。

## 字体文件要求
- 格式：`.ttf` 或 `.otf`
- 大小：通常 3-10 MB
- 编码：必须包含中文字符集（GB2312 或 Unicode）

## 临时方案（无中文字体）
如果未添加字体文件，PDF将：
- 使用系统默认字体（通常是英文）
- 中文字符显示为 `.` 或乱码
- 功能仍可正常使用

## 检查方法
应用启动时会自动检测字体文件。如果检测到，PDF将自动使用中文渲染。

---

**注意**：不要提交过大的字体文件到 Git（超过 100MB 会被拒绝）。建议将 `.ttf` 添加到 `.gitignore`，或使用时下。
