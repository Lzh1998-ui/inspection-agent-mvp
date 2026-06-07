# 📦 外贸验货AI Agent - MVP

一个基于AI的外贸验货报告生成工具（MVP版本）

## 🎯 功能介绍

**核心功能：** 上传产品照片 → AI自动分析 → 生成专业验货报告

**适用人群：** 外贸业务员、质检员、采购商

**MVP状态：** 当前版本为功能验证版，用于收集用户反馈

---

## 🚀 在线体验

**Streamlit Cloud版本（推荐）：**
👉 [点击这里体验](https://待部署后生成链接)

**本地运行版本：**
见下方「本地运行」章节

---

## 📱 使用流程

1. **输入OpenAI API Key**（从 https://platform.openai.com/api-keys 获取）
2. **上传产品照片**（3-10张，不同角度）
3. **填写基本信息**（产品名称、验货标准、订单数量）
4. **点击生成报告** → AI自动分析并生成验货报告PDF

---

## 🔧 本地运行（开发者/内测用户）

### 环境要求
- Python 3.8+
- OpenAI API Key

### 安装步骤

1. **克隆仓库**
```bash
git clone https://github.com/你的用户名/inspection-agent-mvp.git
cd inspection-agent-mvp
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置API Key**
创建 `.streamlit/secrets.toml` 文件：
```toml
OPENAI_API_KEY = "sk-your-api-key-here"
```

4. **运行应用**
```bash
streamlit run app.py
```

5. **打开浏览器**
访问：http://localhost:8501

---

## 🌐 部署到Streamlit Cloud（公开访问）

### 步骤1：Fork或创建GitHub仓库
1. 访问 https://github.com/new
2. 创建公开仓库（如 `inspection-agent-mvp`）
3. 推送代码：
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/你的用户名/inspection-agent-mvp.git
git push -u origin main
```

### 步骤2：连接Streamlit Cloud
1. 访问 https://streamlit.io/cloud
2. 点击「New app」
3. 选择你的GitHub仓库
4. 设置主文件路径：`app.py`
5. 点击「Deploy」

### 步骤3：获取访问链接
部署完成后，你会得到一个公开链接，如：
```
https://你的用户名-inspection-agent-mvp.streamlit.app
```

将这个链接分享给任何人，他们都能直接使用（需自己提供OpenAI API Key）

---

## 📁 项目结构

```
inspection-agent-mvp/
├── app.py                    # 主界面（Streamlit）
├── inspector.py              # AI分析逻辑（待实现）
├── report_generator.py       # PDF报告生成（待实现）
├── requirements.txt          # 依赖列表
├── .gitignore               # Git忽略文件
├── .streamlit/
│   └── secrets.toml        # API Key配置（本地开发用，不提交）
├── example_images/          # 示例图片
└── README.md               # 本文件
```

---

## ⚠️ 免责声明

**本工具为AI辅助工具，生成结果仅供参考，不构成专业验货意见。**

- AI分析结果可能存在误差
- 重要决策前请务必由专业验货员复核
- 开发者不对使用本工具产生的任何损失负责

---

## 📊 MVP验证目标

- [ ] 收集10个以上真实用户反馈
- [ ] 生成50份以上验货报告
- [ ] 验证用户付费意愿
- [ ] 优化AI Prompt提高准确率

---

## 📞 联系开发者

- GitHub Issues：https://github.com/你的用户名/inspection-agent-mvp/issues
- 邮箱：待添加

---

## 📝 更新日志

### v0.1.0 (2026-06-07)
- ✅ 实现基础界面（图片上传 + 信息填写）
- ✅ 支持用户自己输入OpenAI API Key
- 🚧 AI分析功能开发中（预计Day 3完成）
- 🚧 PDF报告生成开发中（预计Day 5完成）

---

**MIT License** - 开源项目，欢迎贡献代码和反馈！
