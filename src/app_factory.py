"""应用启动时的配置与运行时对象构建。"""

from pathlib import Path
import yaml

DEFAULT_ASR_MODEL_ID = "FunAudioLLM/Fun-ASR-Nano-2512"


def load_config(config_path: Path) -> dict:
    """加载配置文件，兼容 JSON/YAML。"""
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def build_runtime(config: dict, project_root: Path, status_callback=None):
    """根据配置初始化运行时组件。"""
    if status_callback:
        status_callback("正在导入运行时模块...")
    from asr_engine import ASREngine
    from audio_processor import AudioProcessor
    from recorder import AudioRecorder

    def resolve_project_path(raw_path: str | None, default: Path | None = None) -> Path | None:
        if raw_path:
            candidate = Path(raw_path)
        elif default is not None:
            candidate = default
        else:
            return None

        if candidate.is_absolute():
            return candidate
        return project_root / candidate

    audio_config = config["audio"]
    if status_callback:
        status_callback("正在初始化录音器...")
    recorder = AudioRecorder(
        sample_rate=audio_config["input_sample_rate"],
        channels=audio_config["channels"],
        dtype=audio_config["dtype"],
    )

    if status_callback:
        status_callback("正在初始化音频处理器...")
    processor = AudioProcessor(
        input_sample_rate=audio_config["input_sample_rate"],
        target_sample_rate=audio_config["target_sample_rate"],
    )

    model_config = config["model"]
    model_path = resolve_project_path(model_config.get("path")) or DEFAULT_ASR_MODEL_ID
    vad_model_path = resolve_project_path(config.get("vad_model_path"))

    if status_callback:
        status_callback("正在初始化 ASR 引擎...")
    asr_engine = ASREngine(
        model_path=model_path,
        device=model_config["device"],
        default_language=model_config["default_language"],
        filler_words=config.get("filler_words", []),
        vocabulary_corrections=config.get("vocabulary_corrections", {}),
        vad_model_path=vad_model_path,
        offline_mode=config.get("offline_mode", False),
    )

    temp_config = config["temp"]
    if status_callback:
        status_callback("正在整理临时目录与语言配置...")
    temp_audio_path = project_root / temp_config["audio_dir"] / temp_config["audio_filename"]
    supported_languages = model_config["supported_languages"]
    return recorder, processor, asr_engine, temp_audio_path, supported_languages
