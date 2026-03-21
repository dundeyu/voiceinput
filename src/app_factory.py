"""应用启动时的配置与运行时对象构建。"""

from pathlib import Path
import yaml

DEFAULT_VAD_MODEL_PATH = Path("models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch")


def load_config(config_path: Path) -> dict:
    """加载配置文件，兼容 JSON/YAML。"""
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def build_runtime(config: dict, project_root: Path):
    """根据配置初始化运行时组件。"""
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
    recorder = AudioRecorder(
        sample_rate=audio_config["input_sample_rate"],
        channels=audio_config["channels"],
        dtype=audio_config["dtype"],
    )

    processor = AudioProcessor(
        input_sample_rate=audio_config["input_sample_rate"],
        target_sample_rate=audio_config["target_sample_rate"],
    )

    model_config = config["model"]
    model_path = resolve_project_path(model_config["path"])
    vad_model_path = resolve_project_path(config.get("vad_model_path"), DEFAULT_VAD_MODEL_PATH)

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
    temp_audio_path = project_root / temp_config["audio_dir"] / temp_config["audio_filename"]
    supported_languages = model_config["supported_languages"]
    return recorder, processor, asr_engine, temp_audio_path, supported_languages
