#!/usr/bin/env python3
"""
通过GitHub REST API推送代码（绕过Git命令行）
需要：GitHub Personal Access Token
"""

import base64
import json
import os
import requests

# 配置
GITHUB_TOKEN = input("请输入GitHub Token（ghp_xxx）: ").strip()
REPO_OWNER = "Lzh1998-ui"
REPO_NAME = "inspection-agent-mvp"
BRANCH = "main"

# GitHub API Headers
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def get_file_sha(file_path):
    """获取文件的当前SHA（需要更新时必须）"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    params = {"ref": BRANCH}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()["sha"]
    return None

def upload_file(file_path, local_path):
    """上传单个文件到GitHub"""
    print(f"📤 上传 {file_path}...")
    
    # 读取本地文件
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")
    
    # 获取当前SHA（如果需要更新）
    sha = get_file_sha(file_path)
    
    # 构建API请求
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    data = {
        "message": f"feat: 更新 {file_path} (通过API推送)",
        "content": content,
        "branch": BRANCH
    }
    if sha:
        data["sha"] = sha
    
    # 发送请求
    response = requests.put(url, headers=headers, data=json.dumps(data))
    
    if response.status_code in [200, 201]:
        print(f"✅ {file_path} 上传成功！")
        return True
    else:
        print(f"❌ {file_path} 上传失败：{response.json().get('message')}")
        return False

def main():
    print("🚀 开始通过GitHub API推送代码...")
    
    # 要推送的文件列表
    files_to_push = [
        ("app.py", "app.py"),
        (".streamlit/secrets.toml", ".streamlit/secrets.toml")
    ]
    
    success_count = 0
    for file_path, local_path in files_to_push:
        if os.path.exists(local_path):
            if upload_file(file_path, local_path):
                success_count += 1
        else:
            print(f"⚠️ 文件不存在：{local_path}")
    
    print(f"\n🎉 完成！成功上传 {success_count}/{len(files_to_push)} 个文件")
    print(f"⏱️ Streamlit Cloud将在1-2分钟内自动部署")

if __name__ == "__main__":
    main()
