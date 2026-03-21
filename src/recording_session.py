"""录音会话辅助逻辑。"""

import logging
from contextlib import contextmanager
from pathlib import Path


PREVIEW_INTERVAL_SECONDS = 1.5


def should_trigger_preview(now: float, last_inference_time: float, interval: float = PREVIEW_INTERVAL_SECONDS) -> bool:
    """判断是否应该触发下一次流式预览识别。"""
    return now - last_inference_time >= interval


def get_stream_audio_path(temp_audio_path: Path) -> Path:
    """获取流式预览使用的临时音频路径。"""
    return temp_audio_path.parent / f"stream_{temp_audio_path.name}"


@contextmanager
def suppress_third_party_logs():
    """临时压低三方 logger 级别。"""
    root_logger = logging.getLogger()
    previous_root_level = root_logger.level
    third_party_loggers = []
    try:
        root_logger.setLevel(logging.CRITICAL)
        for logger_name in logging.root.manager.loggerDict:
            if "funasr" in logger_name or "modelscope" in logger_name:
                target_logger = logging.getLogger(logger_name)
                third_party_loggers.append((target_logger, target_logger.level))
                target_logger.setLevel(logging.CRITICAL)
        yield
    finally:
        root_logger.setLevel(previous_root_level)
        for target_logger, previous_level in third_party_loggers:
            target_logger.setLevel(previous_level)


def run_streaming_inference(audio_data, processor, asr_engine, temp_audio_path: Path, language: str):
    """执行一次录音中的流式预览识别。"""
    processed = processor.process(audio_data)
    stream_audio_path = get_stream_audio_path(temp_audio_path)
    processor.save_wav(processed, str(stream_audio_path))
    with suppress_third_party_logs():
        return asr_engine.transcribe(str(stream_audio_path), language=language)


def transcribe_recording(audio_data, processor, asr_engine, temp_audio_path: Path, language: str):
    """对最终录音进行处理并转写。"""
    processed = processor.process(audio_data)
    processor.save_wav(processed, str(temp_audio_path))
    with suppress_third_party_logs():
        return asr_engine.transcribe(str(temp_audio_path), language=language)
