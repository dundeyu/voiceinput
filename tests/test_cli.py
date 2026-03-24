import io

from cli import (
    CLI,
    GREEN,
    LIGHT_CYAN,
    _loading_spinner_worker,
    make_box,
    strip_ansi,
    visible_len,
    wrap_visible_text,
)


def test_visible_len_counts_wide_characters_and_ignores_ansi():
    assert visible_len("abc") == 3
    assert visible_len("中文a") == 5
    assert visible_len("\033[31m中文\033[0m") == 4


def test_make_box_pads_body_to_consistent_width():
    panel = strip_ansi(make_box(["本地离线语音输入", "当前语言 中文"], title=" voiceinput "))
    lines = panel.splitlines()
    body_widths = [visible_len(line) for line in lines]

    assert len(set(body_widths)) == 1


def test_make_box_uses_unified_border_color_by_default():
    panel = make_box(["正文"], title=" 标题 ", color=GREEN)

    assert GREEN in panel
    assert LIGHT_CYAN not in panel


def test_make_box_supports_custom_body_border_color():
    panel = make_box(["正文"], title=" 标题 ", color=GREEN, body_border_color=LIGHT_CYAN)

    assert GREEN in panel
    assert LIGHT_CYAN in panel


def test_print_welcome_includes_stream_recognize_shortcut(capsys):
    cli = CLI(
        on_record_toggle=lambda: None,
        on_language_switch=lambda: "中文",
        on_stream_recognize=lambda: None,
        supported_languages=["中文"],
    )

    cli.print_welcome()

    output = strip_ansi(capsys.readouterr().out)

    assert "[S]        识别当前 stream 缓存" in output


def test_wrap_visible_text_wraps_wide_text_without_overflow():
    wrapped = wrap_visible_text("现在正在测试语音的输入。" * 3, 20)

    assert len(wrapped) > 1
    assert all(visible_len(line) <= 20 for line in wrapped)


def test_show_result_appends_usage_stats_to_status_line(capsys):
    cli = CLI(
        on_record_toggle=lambda: None,
        on_language_switch=lambda: "中文",
        on_stream_recognize=lambda: None,
        supported_languages=["中文"],
    )

    cli.show_result(
        "你好世界",
        status_note="已复制到剪贴板",
        status_details=["本次：4", "今日：4", "累计：40"],
    )

    output = strip_ansi(capsys.readouterr().out)

    assert "已复制到剪贴板  本次：4  今日：4  累计：40" in output


def test_loading_spinner_worker_clears_line_when_status_is_hidden(monkeypatch):
    class FakeEvent:
        def __init__(self):
            self._set = False

        def is_set(self):
            return self._set

        def set(self):
            self._set = True

    class FakeState:
        text = "未找到本地 ASR，正在尝试联网获取..."
        is_visible = False

    stop_event = FakeEvent()
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)

    def fake_sleep(_seconds):
        stop_event.set()

    monkeypatch.setattr("time.sleep", fake_sleep)

    _loading_spinner_worker("正在处理...", stop_event, FakeState())

    assert "\r\033[K" in output.getvalue()


def test_handle_key_triggers_stream_recognize_when_idle():
    called = []
    cli = CLI(
        on_record_toggle=lambda: None,
        on_language_switch=lambda: "中文",
        on_stream_recognize=lambda: called.append("stream"),
        supported_languages=["中文"],
    )

    assert cli._handle_key("s") is True
    assert called == ["stream"]
