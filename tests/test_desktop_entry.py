from unittest.mock import Mock, patch

from desktop_entry import DesktopVoiceController


def test_remove_hotkey_artifact_uses_backspace():
    keyboard = Mock()

    with patch("pynput.keyboard.Controller", return_value=keyboard), patch("time.sleep", return_value=None):
        controller = DesktopVoiceController.__new__(DesktopVoiceController)
        controller.logger = Mock()
        controller._remove_hotkey_artifact()

    keyboard.press.assert_called_once()
    keyboard.release.assert_called_once()


def test_preload_runtime_uses_asr_preload_with_failure_details():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.logger = Mock()
    controller.config = {"offline_mode": False}
    controller.asr_engine = Mock()
    controller.asr_engine.model_path = "FunAudioLLM/Fun-ASR-Nano-2512"
    controller.asr_engine.vad_model_path = None
    controller.asr_engine.use_vad = False
    controller.asr_engine.last_error = None

    with patch("desktop_entry.preload_model_or_exit") as preload_mock:
        controller.preload_runtime()

    preload_mock.assert_called_once()
    assert preload_mock.call_args.args[0] is controller.asr_engine.preload


def test_toggle_recording_records_usage_stats_after_successful_paste():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.logger = Mock()
    controller.is_recording = True
    controller.preview = Mock()
    controller.recorder = Mock()
    controller.recorder.stop_recording.return_value = object()
    controller.processor = Mock()
    controller.asr_engine = Mock()
    controller.temp_audio_path = Mock()
    controller.language = "中文"
    controller._inference_lock = Mock()
    controller.usage_stats_store = Mock()
    controller.usage_stats_store.record_input.return_value = Mock(today_chars=10, total_chars=100)
    controller._paste_text = Mock(return_value=True)
    controller._remove_hotkey_artifact = Mock()

    with patch("desktop_entry.transcribe_recording_serialized", return_value="你好\n世界"), patch("time.sleep", return_value=None):
        controller.toggle_recording()

    controller.usage_stats_store.record_input.assert_called_once_with(4)
    controller.preview.update_text.assert_any_call("已粘贴  本次：4  今日：10  累计：100")
