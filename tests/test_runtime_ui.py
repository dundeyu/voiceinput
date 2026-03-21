from runtime_ui import (
    format_interim_text_block,
    format_idle_preview,
    format_recording_header,
    format_recording_status_line,
    get_audio_volume_bar,
    get_display_width,
    normalize_volume_for_display,
    truncate_terminal_text,
)


def test_get_audio_volume_bar_caps_to_bar_length():
    assert "█" in get_audio_volume_bar(0.1)
    assert "░" in get_audio_volume_bar(0.1)
    assert "░" in get_audio_volume_bar(0.0)


def test_normalize_volume_for_display_boosts_small_signals():
    assert normalize_volume_for_display(0.0) == 0.0
    assert normalize_volume_for_display(0.02) > 0.02
    assert normalize_volume_for_display(1.0) == 1.0


def test_get_display_width_counts_wide_characters():
    assert get_display_width("abc") == 3
    assert get_display_width("中文a") == 5


def test_truncate_terminal_text_keeps_tail_when_too_long():
    assert truncate_terminal_text("abcdefghijklmnopqrstuvwxyz", 10) == "...tuvwxyz"


def test_format_recording_status_line_contains_prompt_and_volume():
    line = format_recording_status_line("🔴", "██░░")

    assert "按空格键结束" in line
    assert "██░░" in line


def test_format_interim_text_block_truncates_by_terminal_width():
    block = format_interim_text_block("0123456789abcdefghijk", terminal_width=20)

    assert "实时: " in block
    assert "..." in block


def test_format_recording_header_contains_language_and_shortcuts():
    header = format_recording_header("🔴", "中文", "██░░")

    assert "[中文]" in header
    assert "空格结束" in header
    assert "音量:" in header


def test_format_idle_preview_mentions_language():
    preview = format_idle_preview("英文")

    assert "当前语言 英文" in preview
