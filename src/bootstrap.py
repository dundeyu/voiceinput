"""启动阶段的轻量 helper，便于独立测试。"""

import os
import sys
from typing import Callable


def apply_offline_env(config: dict):
    """根据配置设置离线环境变量。"""
    if config.get("offline_mode", False):
        os.environ["MODELSCOPE_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"


def preload_model_or_exit(
    preload: Callable[..., bool],
    logger,
    status_callback: Callable[[str], None] | None = None,
):
    """预加载模型，失败则直接退出。"""
    logger.info("预加载模型...")
    if status_callback:
        status_callback("正在预加载模型...")
    if preload(status_callback=status_callback):
        return

    logger.error("模型预加载失败，请检查模型路径、离线资源和VAD配置。")
    print("模型预加载失败，请检查 config/settings.json 中的模型路径与离线资源后重试。")
    sys.exit(1)
