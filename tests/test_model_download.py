from model_download import resolve_modelscope_model_id


def test_resolve_modelscope_model_id_keeps_unknown_id():
    assert resolve_modelscope_model_id("custom/model-id") == "custom/model-id"


def test_resolve_modelscope_model_id_maps_known_alias():
    assert resolve_modelscope_model_id("fsmn-vad") != "fsmn-vad"
