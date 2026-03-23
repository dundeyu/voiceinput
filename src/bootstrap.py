"""启动阶段的轻量 helper，便于独立测试。"""

import os
import sys
from pathlib import Path
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
    failure_details: list[str] | None = None,
):
    """预加载模型，失败则直接退出。"""
    logger.info("预加载模型...")
    if status_callback:
        status_callback("正在预加载模型...")
    if preload(status_callback=status_callback):
        return

    logger.error("模型预加载失败，请检查模型路径、离线资源和VAD配置。")
    print("模型预加载失败，请检查 config/settings.json 中的模型路径与离线资源后重试。")
    for detail in failure_details or []:
        print(detail)
    sys.exit(1)


def build_preload_failure_details(
    offline_mode: bool,
    model_path: str | Path | None,
    vad_model_path: str | Path | None = None,
    use_vad: bool = True,
    last_error: str | None = None,
) -> list[str]:
    """生成更具体的模型预加载失败提示。"""
    details = [f"当前离线模式: {'开启' if offline_mode else '关闭'}"]

    if model_path is not None:
        model_path = Path(model_path)
        details.append(f"ASR 模型路径: {model_path} ({'存在' if model_path.exists() else '不存在'})")

    if use_vad and vad_model_path is not None:
        vad_model_path = Path(vad_model_path)
        details.append(f"VAD 模型路径: {vad_model_path} ({'存在' if vad_model_path.exists() else '不存在'})")

    if last_error:
        details.append(f"最后错误: {last_error}")

    if offline_mode:
        details.append("离线模式下不会自动下载模型；如果路径不存在，需要先手动准备本地模型。")
    else:
        details.append("如果本地路径不存在，程序会尝试联网获取模型；请检查网络或仓库权限。")

    return details
