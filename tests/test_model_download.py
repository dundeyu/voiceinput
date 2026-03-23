from pathlib import Path

from model_download import get_cached_model_path, get_modelscope_cache_path, resolve_modelscope_model_id


def test_resolve_modelscope_model_id_keeps_unknown_id():
    assert resolve_modelscope_model_id("custom/model-id") == "custom/model-id"


def test_resolve_modelscope_model_id_maps_known_alias():
    assert resolve_modelscope_model_id("fsmn-vad") != "fsmn-vad"


def test_resolve_modelscope_model_id_extracts_repo_from_local_models_path():
    model_id = resolve_modelscope_model_id(
        "/private/tmp/voiceinput-fresh-test.GJnlHi/repo/models/FunAudioLLM/Fun-ASR-Nano-2512"
    )

    assert model_id == "FunAudioLLM/Fun-ASR-Nano-2512"


def test_get_modelscope_cache_path_uses_resolved_model_id():
    cache_path = get_modelscope_cache_path("fsmn-vad")

    assert cache_path.name == "speech_fsmn_vad_zh-cn-16k-common-pytorch"
    assert cache_path.parent.name == "iic"


def test_get_cached_model_path_returns_none_when_cache_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("model_download.Path.home", lambda: tmp_path)

    assert get_cached_model_path("FunAudioLLM/Fun-ASR-Nano-2512") is None
