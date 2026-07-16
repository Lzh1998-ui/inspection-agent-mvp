# app_pro 部署指南

## 方案一：独立 Streamlit Cloud 项目（推荐）

app_pro 与 app_free（根目录 app.py）共用同一 `core/` 内核，但独立部署、独立品牌。

### 步骤

**1. 推送代码到 GitHub（如尚未推送根目录 app.py）**

```bash
git add .
git commit -m "feat: app_pro 骨架"
git push origin main
```

**2. 在 Streamlit Cloud 创建新 App**

1. 登录 [share.streamlit.io](https://share.streamlit.io)
2. 点击 **New app**
3. 选择同一仓库 `Lzh1998-ui/inspection-agent-mvp`
4. **Branch**: `main`
5. **Main file path**: `app_pro/app.py` ← 关键
6. **Advanced settings → Secrets**: 配置与 app_free 相同的密钥
   ```
   [qwen]
   api_key = "sk-..."

   [supabase]
   url = "https://xxx.supabase.co"
   anon_key = "eyJ..."
   service_role_key = "eyJ..."
   ```
7. 点击 **Deploy!**

> ⚠️ Streamlit Cloud 的 `Main file path` 支持子目录文件，会把 `app_pro/` 作为工作目录启动，与根目录 app.py 完全独立。

---

## 方案二：分离两个 GitHub 仓库

如果希望两个产品完全隔离（独立迭代、独立 CI）：

1. **保留当前仓库** → app_free（根目录 app.py）
2. **Fork 或新建仓库** → app_pro，复制以下内容：
   ```
   app_pro/          ← 整个目录
   core/             ← 共享内核（定期同步 from app_free）
   fonts/            ← 字体
   auth_helper.py    ← 鉴权（可复用）
   requirements.txt  ← 基础依赖
   ```
3. 分别在 Streamlit Cloud 创建两个 App

---

## 独立 Supabase 项目（建议生产环境）

| 产品 | 用途 | Supabase 项目 |
|------|------|--------------|
| app_free | 免费体验，获客引流 | 现有项目 |
| app_pro | 付费专业版，商业数据 | **新建独立项目** |

### 新建 app_pro 的 Supabase 项目

1. 登录 [supabase.com](https://supabase.com)
2. 新建项目 `inspection-agent-pro`
3. 复制 URL + anon_key + service_role_key → Streamlit Cloud Secrets
4. 执行同一套 DDL 初始化表结构
5. **重要**：创建独立的 RLS 策略，禁止 app_free 访问 app_pro 数据

---

## app_pro 目录结构

```
app_pro/
├── __init__.py          空包标识
├── app.py               Streamlit 入口（聊天优先 UI）
├── agent_loop.py        Agent 主循环（function calling）
├── tools.py             工具注册表 + 实现
├── requirements_pro.txt 额外依赖
└── README.md             本文件

共享（位于仓库根目录）/
├── core/
│   ├── aql.py           AQL 引擎
│   ├── pdf.py           PDF 生成
│   └── ai.py            AI 客户端封装
├── auth_helper.py        鉴权（复用）
├── fonts/               字体文件
└── requirements.txt     基础依赖
```

---

## 开发调试（本地运行）

```bash
# 确保根目录依赖装好
pip install -r requirements.txt

# 安装 app_pro 额外依赖
pip install -r app_pro/requirements_pro.txt

# 运行 app_pro（从仓库根目录）
streamlit run app_pro/app.py
```

---

## 下一步（Agent 能力升级）

骨架搭好后，按 `AGENT_UPGRADE_ROADMAP.md` 推进：

- **阶段一**：增强多轮追问（Agent 会要求补图/补参数）
- **阶段二-P0**：AQL 工具 + 历史缺陷检索上线
- **阶段二-P1/P2**：标准知识库 + 产品档案工具
- **阶段三**：记忆层（工厂/产品档案持久化）
