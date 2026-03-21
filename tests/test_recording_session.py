from pathlib import Path
from unittest.mock import Mock, patch

from recording_session import (
    get_stream_audio_path,
    run_streaming_inference,
    should_trigger_preview,
    transcribe_recording,
)


def test_should_trigger_preview_respects_interval():
    assert should_trigger_preview(10.0, 8.4) is True
    assert should_trigger_preview(10.0, 8.6) is False


def test_get_stream_audio_path_uses_stream_prefix():
    path = get_stream_audio_path(Path("/tmp/recording.wav"))

    assert path == Path("/tmp/stream_recording.wav")


def test_run_streaming_inference_processes_saves_and_transcribes():
    processor = Mock()
    processor.process.return_value = "processed"
    asr_engine = Mock()
    asr_engine.transcribe.return_value = "preview text"

    with patch("recording_session.suppress_third_party_logs"):
        text = run_streaming_inference(
            "audio",
            processor=processor,
            asr_engine=asr_engine,
            temp_audio_path=Path("/tmp/recording.wav"),
            language="中文",
        )

    assert text == "preview text"
    processor.process.assert_called_once_with("audio")
    processor.save_wav.assert_called_once_with("processed", "/tmp/stream_recording.wav")
    asr_engine.transcribe.assert_called_once_with("/tmp/stream_recording.wav", language="中文")


def test_transcribe_recording_uses_final_temp_path():
    processor = Mock()
    processor.process.return_value = "processed"
    asr_engine = Mock()
    asr_engine.transcribe.return_value = "final text"

    with patch("recording_session.suppress_third_party_logs"):
        text = transcribe_recording(
            "audio",
            processor=processor,
            asr_engine=asr_engine,
            temp_audio_path=Path("/tmp/recording.wav"),
            language="英文",
        )

    assert text == "final text"
    processor.process.assert_called_once_with("audio")
    processor.save_wav.assert_called_once_with("processed", "/tmp/recording.wav")
    asr_engine.transcribe.assert_called_once_with("/tmp/recording.wav", language="英文")
