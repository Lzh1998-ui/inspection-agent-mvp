# 中文字体目录

此目录用于存放 PDF 生成所需的中文字体文件。

## 推荐字体

### 1. 思源黑体 Source Han Sans（强烈推荐）
- **下载地址**: https://github.com/adobe-fonts/source-han-sans/releases
- **推荐文件**: `SourceHanSansCN-Regular.otf`（简体中文常规）
- **优点**: Adobe 开源、字形优美、覆盖完整

### 2. Google Noto Sans CJK
- **下载地址**: https://fonts.google.com/noto/fonts?noto.query=chinese
- **推荐文件**: `NotoSansCJK-Regular.ttc`
- **优点**: Google 开源、多语言支持

### 3. 文泉驿微米黑
- **下载地址**: https://sourceforge.net/projects/wqy/files/wqy-microhei/
- **推荐文件**: `wqy-microhei.ttc`
- **优点**: 开源、轻量

## 使用方法

1. 下载上述任意一种字体的 `.ttf` 或 `.otf` 或 `.ttc` 文件
2. 将字体文件放入此 `fonts/` 目录
3. 重新部署到 Streamlit Cloud
4. 部署后 PDF 即可正常显示中文

## 支持的字体文件名

code 会自动检测以下文件名：
- `NotoSansCJK-Regular.ttc`
- `NotoSansCJK-Regular.otf`
- `SourceHanSansCN-Regular.otf`
- `SourceHanSansCN-Regular.ttf`
- `wqy-microhei.ttc`
- `wqy-zenhei.ttc`
- `simhei.ttf`
- `simsun.ttc`

**注意**: 文件名必须完全匹配，区分大小写。
