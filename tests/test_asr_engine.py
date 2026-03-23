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


def test_load_model_prefers_cached_asr_model_when_available(tmp_path):
    fake_model = Mock()
    fake_model.eval = Mock()

    fake_funasr_nano = SimpleNamespace(
        from_pretrained=Mock(return_value=(fake_model, {})),
    )

    with patch("asr_engine._ensure_whisper_tokenizer_available"), patch(
        "asr_engine._ensure_funasr_nano_path"
    ), patch(
        "asr_engine.get_cached_model_path",
        return_value=tmp_path / ".cache/modelscope/hub/models/FunAudioLLM/Fun-ASR-Nano-2512",
    ), patch.dict(
        "sys.modules",
        {"funasr.models.fun_asr_nano.model": SimpleNamespace(FunASRNano=fake_funasr_nano)},
    ):
        engine = ASREngine(
            model_path="FunAudioLLM/Fun-ASR-Nano-2512",
            device="cpu",
            default_language="中文",
            use_vad=False,
        )

        status_callback = Mock()
        loaded = engine.load_model(status_callback=status_callback)

    assert loaded is True
    fake_funasr_nano.from_pretrained.assert_called_once()
    assert fake_funasr_nano.from_pretrained.call_args.kwargs["model"] == str(
        tmp_path / ".cache/modelscope/hub/models/FunAudioLLM/Fun-ASR-Nano-2512"
    )
    status_texts = [call.args[0] for call in status_callback.call_args_list]
    assert any("正在加载缓存 ASR 模型" in text for text in status_texts)


def test_load_model_keeps_modelscope_progress_without_custom_download_status(tmp_path):
    fake_model = Mock()
    fake_model.eval = Mock()

    fake_funasr_nano = SimpleNamespace(
        from_pretrained=Mock(return_value=(fake_model, {})),
    )
    download_model = Mock(return_value=str(tmp_path / ".cache/modelscope/hub/models/FunAudioLLM/Fun-ASR-Nano-2512"))

    with patch("asr_engine._ensure_whisper_tokenizer_available"), patch(
        "asr_engine._ensure_funasr_nano_path"
    ), patch(
        "asr_engine.get_cached_model_path",
        return_value=None,
    ), patch(
        "asr_engine.download_model_from_modelscope",
        download_model,
    ), patch.dict(
        "sys.modules",
        {"funasr.models.fun_asr_nano.model": SimpleNamespace(FunASRNano=fake_funasr_nano)},
    ):
        engine = ASREngine(
            model_path="FunAudioLLM/Fun-ASR-Nano-2512",
            device="cpu",
            default_language="中文",
            use_vad=False,
        )

        status_callback = Mock()
        loaded = engine.load_model(status_callback=status_callback)

    assert loaded is True
    download_model.assert_called_once_with(
        "FunAudioLLM/Fun-ASR-Nano-2512",
        label="ASR 模型",
    )
    status_texts = [call.args[0] for call in status_callback.call_args_list]
    assert any("未找到本地 ASR，正在尝试联网获取" in text for text in status_texts)
    assert not any("正在下载ASR 模型" in text for text in status_texts)
