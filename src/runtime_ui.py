"""录音态终端 UI 的纯格式化 helper。"""

import shutil
import unicodedata


RESET = "\033[0m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"


def normalize_volume_for_display(volume: float) -> float:
    """将原始音量映射到更适合终端展示的范围。"""
    clamped = max(0.0, min(1.0, volume))
    boosted = min(1.0, clamped * 6.0)
    return boosted ** 0.8


def get_audio_volume_bar(volume: float, bar_length: int = 20) -> str:
    """将音量转换为字符串进度条。"""
    normalized_volume = normalize_volume_for_display(volume)
    filled = min(bar_length, int(normalized_volume * bar_length))
    color = get_volume_color(volume)
    filled_bar = color + ("█" * filled) + RESET if filled else ""
    empty_bar = DIM + ("░" * (bar_length - filled)) + RESET
    return filled_bar + empty_bar


def get_display_width(text: str) -> int:
    """按终端展示宽度计算字符串长度。"""
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ("F", "W", "A"):
            width += 2
        else:
            width += 1
    return width


def truncate_terminal_text(text: str, max_width: int) -> str:
    """从尾部保留文本，超长时前置省略号。"""
    current_width = get_display_width(text)
    if current_width <= max_width:
        return text

    truncated = ""
    current_width = 3
    for char in reversed(text):
        char_width = 2 if unicodedata.east_asian_width(char) in ("F", "W", "A") else 1
        if current_width + char_width > max_width:
            break
        truncated = char + truncated
        current_width += char_width
    return "..." + truncated


def format_recording_status_line(dot: str, volume_bar: str) -> str:
    """格式化第一行状态文字。"""
    return f"\r\033[K{dot} 正在全神贯注倾听... (按空格键结束)  音量: {volume_bar}"


def get_volume_color(volume: float) -> str:
    """根据音量返回 ANSI 颜色。"""
    display_volume = normalize_volume_for_display(volume)
    if display_volume < 0.3:
        return GREEN
    if display_volume < 0.65:
        return YELLOW
    return RED


def format_recording_header(dot: str, language: str, volume_bar: str) -> str:
    """格式化录音时的主状态行。"""
    return (
        f"\r\033[K{dot} 录音中  "
        f"[{language}]  "
        f"音量: {volume_bar}  "
        f"[空格结束 / L切换语言 / Q退出]"
    )


def format_interim_text_block(interim_text: str, terminal_width: int | None = None) -> str:
    """格式化实时识别文本显示块。"""
    prefix = "实时: "
    if terminal_width is None:
        terminal_width = shutil.get_terminal_size((80, 24)).columns

    safe_max_width = max(10, terminal_width - 6 - 8)
    show_text = truncate_terminal_text(interim_text, safe_max_width)
    return f"\n\r\033[K\033[93m{prefix}{show_text}\033[0m\033[A\r"


def format_idle_preview(language: str) -> str:
    """格式化未识别到实时文本时的提示。"""
    return f"\n\r\033[K\033[2m实时转写待命中 · 当前语言 {language}\033[0m\033[A\r"
