from loading_status import format_loading_status


def test_format_loading_status_renders_progress_bar():
    assert format_loading_status(2, 4, "正在加载 VAD 模型...") == "[##--] 2/4 正在加载 VAD 模型..."


def test_format_loading_status_clamps_out_of_range_values():
    assert format_loading_status(9, 4, "完成") == "[####] 4/4 完成"
