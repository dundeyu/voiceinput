#!/bin/bash
# voiceinput 离线模式启动脚本
# 设置环境变量禁止网络访问

cd "$(dirname "$0")"

# 设置离线模式环境变量
export MODELSCOPE_OFFLINE=1
export HF_HUB_OFFLINE=1

# 激活虚拟环境并运行
source venv/bin/activate
python3 main.py
