"""模型下载进度辅助。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from funasr.download.name_maps_from_hub import name_maps_ms


@dataclass(frozen=True)
class DownloadProgressState:
    """单个文件下载进度快照。"""

    filename: str
    percent: int


def resolve_modelscope_model_id(model_name: str) -> str:
    """将 FunASR 简写模型名映射为 ModelScope 仓库名。"""
    path = Path(model_name)
    if len(path.parts) >= 3 and "models" in path.parts:
        models_index = path.parts.index("models")
        tail_parts = path.parts[models_index + 1 :]
        if len(tail_parts) >= 2:
            return f"{tail_parts[0]}/{tail_parts[1]}"
    return name_maps_ms.get(model_name, model_name)


def get_modelscope_cache_path(model_name: str) -> Path:
    """返回模型在 ModelScope 默认缓存目录中的路径。"""
    model_id = resolve_modelscope_model_id(model_name)
    cache_root = Path.home() / ".cache/modelscope/hub/models"
    return cache_root / model_id


def get_cached_model_path(model_name: str) -> Path | None:
    """如果模型已在 ModelScope 缓存中，返回缓存路径。"""
    cache_path = get_modelscope_cache_path(model_name)
    if cache_path.exists():
        return cache_path
    return None


def download_model_from_modelscope(model_name: str, status_callback=None, label: str = "模型") -> str:
    """从 ModelScope 下载模型，并在下载期间持续更新状态。"""
    from pathlib import Path

    from modelscope import snapshot_download
    from modelscope.hub.callback import ProgressCallback
    from modelscope.utils.constant import Invoke, ThirdParty

    model_id = resolve_modelscope_model_id(model_name)

    if status_callback:
        status_callback(f"正在连接 ModelScope，准备下载{label}...")

    def _short_name(filename: str) -> str:
        path = Path(filename)
        if len(path.parts) >= 2:
            return "/".join(path.parts[-2:])
        return path.name or filename

    class StatusProgressCallback(ProgressCallback):
        def __init__(self, filename: str, file_size: int):
            super().__init__(filename, file_size)
            self.downloaded = 0
            self.file_label = _short_name(filename)
            if status_callback:
                status_callback(f"正在下载{label}: {self.file_label}  0%")

        def update(self, size: int):
            self.downloaded += size
            percent = 0
            if self.file_size > 0:
                percent = int(min((self.downloaded / self.file_size) * 100, 100))
            if status_callback:
                status_callback(f"正在下载{label}: {self.file_label}  {percent}%")

        def end(self):
            if status_callback:
                status_callback(f"已下载{label}: {self.file_label}  100%")

    return snapshot_download(
        model_id,
        user_agent={Invoke.KEY: Invoke.PIPELINE, ThirdParty.KEY: "funasr"},
        progress_callbacks=[StatusProgressCallback],
    )
