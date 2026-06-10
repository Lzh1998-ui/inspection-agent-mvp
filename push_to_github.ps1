# 推送到GitHub的脚本
# 使用方法：
# 1. 右键点击此文件 → "使用PowerShell运行"
# 2. 首次运行会提示输入用户名和密码（Token）
# 3. 之后会自动记住凭据，无需再次输入

Write-Output "🚀 开始推送到GitHub..."

# 切换到项目目录
Set-Location "C:\Users\pc\.openclaw\workspace\inspection_agent_mvp"

# 配置Git凭据存储（永久保存）
git config --global credential.helper store

# 推送到GitHub
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Output "✅ 推送成功！代码已上传到GitHub。"
    Write-Output "⏱️ Streamlit Cloud将在1-2分钟内自动部署新版本。"
} else {
    Write-Output "❌ 推送失败，请检查错误信息。"
}

# 暂停，让你看到结果
Read-Host -Prompt "按Enter键退出"