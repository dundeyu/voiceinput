from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asr_engine import ASREngine


def test_load_model_skips_missing_vad_in_offline_mode(tmp_path):
    model_dir = tmp_path / "asr-model"
    model_dir.mkdir()

    fake_model = Mock()
    fake_model.eval = Mock()

    fake_funasr_nano = SimpleNamespace(
        from_pretrained=Mock(return_value=(fake_model, {})),
    )

    with patch("asr_engine.LEGACY_VAD_MODEL_PATH", str(tmp_path / "legacy-missing-vad")), patch(
        "asr_engine._ensure_funasr_nano_path"
    ), patch(
        "asr_engine._ensure_whisper_tokenizer_available"
    ), patch(
        "asr_engine._get_auto_model", return_value=Mock()
    ), patch.dict(
        "sys.modules",
        {"funasr.models.fun_asr_nano.model": SimpleNamespace(FunASRNano=fake_funasr_nano)},
    ):
        engine = ASREngine(
            model_path=model_dir,
            device="cpu",
            default_language="中文",
            vad_model_path=str(tmp_path / "missing-vad"),
            offline_mode=True,
        )

        status_callback = Mock()
        loaded = engine.load_model(status_callback=status_callback)

    assert loaded is True
    assert engine.use_vad is False
    fake_funasr_nano.from_pretrained.assert_called_once()
    status_texts = [call.args[0] for call in status_callback.call_args_list]
    assert any("离线模式下将跳过长音频分段" in text for text in status_texts)


def test_load_model_reports_missing_openai_whisper_dependency(tmp_path):
    model_dir = tmp_path / "asr-model"
    model_dir.mkdir()

    engine = ASREngine(
        model_path=model_dir,
        device="cpu",
        default_language="中文",
        use_vad=False,
    )

    with patch(
        "asr_engine._ensure_whisper_tokenizer_available",
        side_effect=ModuleNotFoundError("缺少 openai-whisper 依赖，请先安装 openai-whisper 后再启动 voice。"),
    ), patch("asr_engine._ensure_funasr_nano_path"):
        loaded = engine.load_model()

    assert loaded is False
    assert engine.last_error == "缺少 openai-whisper 依赖，请先安装 openai-whisper 后再启动 voice。"
