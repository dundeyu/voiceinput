from unittest.mock import Mock, patch

from desktop_entry import DesktopVoiceController


def test_remove_hotkey_artifact_uses_backspace():
    keyboard = Mock()

    with patch("pynput.keyboard.Controller", return_value=keyboard), patch("time.sleep", return_value=None):
        controller = DesktopVoiceController.__new__(DesktopVoiceController)
        controller.logger = Mock()
        controller.config = {}
        controller._remove_hotkey_artifact()

    keyboard.press.assert_called_once()
    keyboard.release.assert_called_once()


def test_remove_hotkey_artifact_skips_backspace_when_intercept_enabled():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.logger = Mock()
    controller.config = {"hotkey": {"intercept": True}}

    with patch("pynput.keyboard.Controller") as controller_cls:
        controller._remove_hotkey_artifact()

    controller_cls.assert_not_called()


def test_toggle_recording_cleans_hotkey_artifact_when_stopping():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.logger = Mock()
    controller.config = {}
    controller.is_recording = True
    controller.preview = Mock()
    controller.recorder = Mock()
    controller.recorder.stop_recording.return_value = None
    controller._remove_hotkey_artifact = Mock()

    controller.toggle_recording()

    controller._remove_hotkey_artifact.assert_called_once_with()


def test_toggle_recording_cleans_hotkey_artifact_when_starting():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.logger = Mock()
    controller.config = {}
    controller.is_recording = False
    controller.preview = Mock()
    controller.recorder = Mock()
    controller.processor = Mock()
    controller.asr_engine = Mock()
    controller.temp_audio_path = Mock()
    controller.language = "中文"
    controller._inference_lock = Mock()
    controller._preview_generation = 0
    controller._applied_preview_generation = 0
    controller._remove_hotkey_artifact = Mock()

    with patch("threading.Thread") as thread_mock:
        controller.toggle_recording()

    controller._remove_hotkey_artifact.assert_called_once_with()
    thread_mock.assert_called_once()
    controller.preview.show.assert_called_once_with("正在聆听...")


def test_hotkey_intercept_enabled_reads_config():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.config = {"hotkey": {"intercept": True}}

    assert controller._hotkey_intercept_enabled() is True


def test_hotkey_intercept_disabled_by_default():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.config = {}

    assert controller._hotkey_intercept_enabled() is False


def test_desktop_controller_passes_intercept_flag_to_listener():
    config = {"model": {"default_language": "中文"}, "hotkey": {"intercept": True}}

    with patch("desktop_entry.load_runtime_config", return_value=(config, Mock(), False, Mock())), patch(
        "desktop_entry.setup_logging"
    ), patch("desktop_entry.build_runtime", return_value=(Mock(), Mock(), Mock(), Mock(), Mock())), patch(
        "desktop_entry.get_usage_stats_path", return_value=Mock()
    ), patch("desktop_entry.UsageStatsStore"), patch("desktop_entry.DesktopPreviewOverlay"), patch(
        "desktop_entry.GlobalHotkeyListener"
    ) as listener_cls:
        DesktopVoiceController()

    listener_cls.assert_called_once()
    assert listener_cls.call_args.kwargs["intercept"] is True


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


def test_apply_preview_result_ignores_stale_generation():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.is_recording = True
    controller.preview = Mock()
    controller.interim_text = ""
    controller._applied_preview_generation = 2

    controller._apply_preview_result("旧结果", generation=1)

    assert controller.interim_text == ""
    controller.preview.update_text.assert_not_called()


def test_apply_preview_result_ignores_result_after_recording_stops():
    controller = DesktopVoiceController.__new__(DesktopVoiceController)
    controller.is_recording = False
    controller.preview = Mock()
    controller.interim_text = ""
    controller._applied_preview_generation = 0

    controller._apply_preview_result("晚到结果", generation=1)

    assert controller.interim_text == ""
    controller.preview.update_text.assert_not_called()
