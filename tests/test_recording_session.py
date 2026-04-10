import threading
from pathlib import Path
from unittest.mock import Mock, patch

from recording_session import (
    get_stream_audio_path,
    run_streaming_inference,
    should_trigger_preview,
    transcribe_recording,
    transcribe_recording_serialized,
    transcribe_stream_audio_path,
)


def test_should_trigger_preview_respects_interval():
    assert should_trigger_preview(10.0, 8.4) is True
    assert should_trigger_preview(10.0, 8.6) is False


def test_should_trigger_preview_waits_for_minimum_audio_duration():
    assert should_trigger_preview(10.0, 8.0, audio_duration_seconds=1.8) is False
    assert should_trigger_preview(10.0, 8.0, audio_duration_seconds=2.5) is True


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


def test_transcribe_recording_serialized_waits_for_existing_preview_inference():
    processor = Mock()
    processor.process.return_value = "processed"
    asr_engine = Mock()
    asr_engine.transcribe.return_value = "final text"
    inference_lock = threading.Lock()
    inference_lock.acquire()
    transcribe_started = threading.Event()
    transcribe_finished = threading.Event()
    result_holder = {}

    def worker():
        transcribe_started.set()
        result_holder["text"] = transcribe_recording_serialized(
            "audio",
            processor=processor,
            asr_engine=asr_engine,
            temp_audio_path=Path("/tmp/recording.wav"),
            language="中文",
            inference_lock=inference_lock,
        )
        transcribe_finished.set()

    with patch("recording_session.suppress_third_party_logs"):
        thread = threading.Thread(target=worker)
        thread.start()
        transcribe_started.wait(timeout=1)

        assert transcribe_finished.wait(timeout=0.1) is False
        asr_engine.transcribe.assert_not_called()

        inference_lock.release()
        thread.join(timeout=1)

    assert result_holder["text"] == "final text"
    asr_engine.transcribe.assert_called_once_with("/tmp/recording.wav", language="中文")


def test_transcribe_stream_audio_path_uses_existing_stream_file_with_lock():
    asr_engine = Mock()
    asr_engine.transcribe.return_value = "stream text"
    inference_lock = threading.Lock()

    with patch("recording_session.suppress_third_party_logs"):
        text = transcribe_stream_audio_path(
            Path("/tmp/stream_recording.wav"),
            asr_engine=asr_engine,
            language="中文",
            inference_lock=inference_lock,
        )

    assert text == "stream text"
    asr_engine.transcribe.assert_called_once_with("/tmp/stream_recording.wav", language="中文")
