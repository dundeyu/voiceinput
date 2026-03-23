#!/bin/bash
# voiceinput 离线模式启动脚本
# 设置环境变量禁止网络访问

cd "$(dirname "$0")"

# 设置离线模式环境变量
export MODELSCOPE_OFFLINE=1
export HF_HUB_OFFLINE=1

# 直接执行项目虚拟环境中的解释器，避免目录重命名后 activate 内部路径失效
exec ./venv/bin/python ./main.py
