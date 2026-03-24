"""命令行交互模块 - 键盘控制和终端展示。"""

import itertools
import logging
import multiprocessing
import shutil
import sys
import subprocess
import termios
import threading
import time
import tty
import unicodedata
from contextlib import contextmanager
from typing import Callable, List

logger = logging.getLogger(__name__)

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
WHITE = "\033[37m"
LIGHT_CYAN = "\033[96m"


def strip_ansi(text: str) -> str:
    """移除 ANSI 控制序列，便于计算展示宽度。"""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def visible_len(text: str) -> int:
    """计算去除 ANSI 后的可见长度。"""
    visible_text = strip_ansi(text)
    width = 0
    for char in visible_text:
        if unicodedata.east_asian_width(char) in ("F", "W"):
            width += 2
        else:
            width += 1
    return width


def color_text(text: str, color: str = "", bold: bool = False, dim: bool = False) -> str:
    """为文本添加 ANSI 样式。"""
    prefix = ""
    if bold:
        prefix += BOLD
    if dim:
        prefix += DIM
    if color:
        prefix += color
    if not prefix:
        return text
    return f"{prefix}{text}{RESET}"


def pad_visible(text: str, width: int) -> str:
    """按可见宽度右侧补空格。"""
    padding = max(width - visible_len(text), 0)
    return text + (" " * padding)


def wrap_visible_text(text: str, width: int) -> List[str]:
    """按终端可见宽度换行，避免长行撑破边框。"""
    if width <= 0:
        return [text]

    wrapped_lines: List[str] = []
    current = ""
    current_width = 0

    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
        if current and current_width + char_width > width:
            wrapped_lines.append(current)
            current = char
            current_width = char_width
            continue
        current += char
        current_width += char_width

    if current or not wrapped_lines:
        wrapped_lines.append(current)

    return wrapped_lines


def make_box(lines: List[str], title: str | None = None, color: str = BLUE, body_border_color: str | None = None) -> str:
    """生成简单终端边框面板。"""
    terminal_width = shutil.get_terminal_size((80, 24)).columns
    content_padding = 2
    border_color = body_border_color or color
    inner_width = min(
        max(max((visible_len(line) for line in lines), default=0), visible_len(title or "")) + (content_padding * 2),
        terminal_width - 2,
    )
    top_title = f" {title} " if title else ""
    top_fill = max(inner_width - visible_len(top_title), 0)
    top = color_text(f"╭{top_title}{'─' * top_fill}╮" if title else f"╭{'─' * inner_width}╮", color=color)
    body = []
    for line in lines:
        padded_line = pad_visible((" " * content_padding) + line, inner_width)
        left_border = color_text("│", color=border_color)
        right_border = color_text("│", color=border_color)
        body.append(f"{left_border}{padded_line}{right_border}")
    bottom = color_text(f"╰{'─' * inner_width}╯", color=border_color)
    return "\n".join([top, *body, bottom])


class KeyboardListener:
    """非阻塞键盘监听器"""

    def __init__(self):
        self._original_settings = None

    def _get_char(self) -> str:
        """获取单个按键字符"""
        fd = sys.stdin.fileno()
        self._original_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            char = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, self._original_settings)
        return char

    def listen(self, key_handler: Callable[[str], bool]):
        """
        监听键盘输入

        Args:
            key_handler: 按键处理函数，返回True继续监听，False退出
        """
        while True:
            char = self._get_char()
            if not key_handler(char):
                break


def copy_to_clipboard(text: str) -> bool:
    """
    复制文本到剪贴板
    """
    try:
        process = subprocess.Popen(
            ["pbcopy"],
            stdin=subprocess.PIPE,
            env={"LANG": "en_US.UTF-8"}
        )
        process.communicate(text.encode("utf-8"))
        return process.returncode == 0
    except Exception as e:
        logger.error(f"复制到剪贴板失败: {e}")
        return False


def _loading_spinner_worker(initial_text: str, stop_event, status_state=None):
    """在独立进程中刷新加载 spinner，避免被主进程长任务卡住。"""
    was_visible = True
    for frame in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
        if stop_event.is_set():
            break
        text = getattr(status_state, "text", initial_text) if status_state is not None else initial_text
        is_visible = getattr(status_state, "is_visible", True) if status_state is not None else True
        if not is_visible:
            if was_visible:
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
            was_visible = False
            time.sleep(0.1)
            continue
        sys.stdout.write(f"\r{color_text(frame, BLUE, bold=True)} {color_text(text, WHITE)}")
        sys.stdout.flush()
        was_visible = True
        time.sleep(0.1)


class CLI:
    """终端界面控制器。"""

    def __init__(
        self,
        on_record_toggle: Callable[[], None],
        on_language_switch: Callable[[], str],
        on_stream_recognize: Callable[[], None],
        supported_languages: List[str]
    ):
        self.on_record_toggle = on_record_toggle
        self.on_language_switch = on_language_switch
        self.on_stream_recognize = on_stream_recognize
        self.supported_languages = supported_languages
        self.current_language_idx = 0
        self.keyboard = KeyboardListener()

        # UI 状态控制
        self.is_recording = False
        self.is_processing = False
        self.last_result = ""

    def print_welcome(self):
        """显示欢迎面板。"""
        content = [
            "[空格]     开始或停止录音",
            "[L]        循环切换识别语言",
            "[S]        识别当前 stream 缓存",
            "[Q]        退出程序",
        ]
        if self.last_result:
            preview = self.last_result.strip().replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:77] + "..."
            content.extend(["", color_text("最近一次识别:", GREEN, bold=True), preview])

        title = (
            f" 本地离线语音输入  当前语言 {self.get_current_language()} "
        )
        sys.stdout.write(make_box(content, title=title, color=BLUE))
        sys.stdout.write("\n")
        sys.stdout.flush()

    def _handle_key(self, char: str) -> bool:
        """处理按键"""
        char_lower = char.lower()

        # 当正在识别音频时，忽略大部分输入避免干扰UI
        if self.is_processing:
            return True

        if char_lower == 'q':
            sys.stdout.write("\n" + color_text("正在退出程序...", RED, bold=True) + "\n")
            sys.stdout.flush()
            return False

        elif char_lower == 'l':
            if not self.is_recording:
                new_lang = self.on_language_switch()
                self.print_welcome()
                self.show_notice(f"语言已切换为 {new_lang}", title="语言切换", style="cyan")

        elif char_lower == 's':
            if not self.is_recording:
                self.on_stream_recognize()

        elif char == ' ':
            self.on_record_toggle()

        return True

    def run(self):
        """运行CLI"""
        self.print_welcome()
        self.keyboard.listen(self._handle_key)

    def show_result(
        self,
        text: str,
        is_success: bool = True,
        status_note: str | None = None,
        status_details: List[str] | None = None,
    ):
        """显示识别结果。"""
        if is_success:
            self.last_result = text
            char_count = len(text.replace("\n", ""))
            terminal_width = shutil.get_terminal_size((80, 24)).columns
            result_content_width = max(10, terminal_width - 6)
            result_lines = []
            for raw_line in text.splitlines() or [""]:
                wrapped = wrap_visible_text(raw_line, result_content_width)
                result_lines.extend(color_text(line, YELLOW, bold=True) for line in wrapped)
            lines = [""] + result_lines
            status_parts = []
            if status_note:
                status_parts.append(status_note)
            if status_details:
                status_parts.extend(status_details)
            else:
                status_parts.append(f"{char_count} 字符")
            if status_parts:
                lines.extend(["", "  ".join(color_text(part, CYAN, dim=True) for part in status_parts)])
            else:
                lines.extend(["", color_text(f"{char_count} 字符", dim=True)])
            sys.stdout.write(make_box(lines, title=" 识别结果 ", color=GREEN) + "\n")
        else:
            self.show_notice(text, title="识别失败", style="red")
        sys.stdout.flush()

    @contextmanager
    def show_loading(self, text: str = "正在处理..."):
        """显示一个轻量级终端 spinner。"""
        stop_event = None
        spinner_runner = None
        manager = None
        status_state = None

        try:
            ctx = multiprocessing.get_context("spawn")
            stop_event = ctx.Event()
            manager = ctx.Manager()
            status_state = manager.Namespace()
            status_state.text = text
            status_state.is_visible = True
            spinner_runner = ctx.Process(
                target=_loading_spinner_worker,
                args=(text, stop_event, status_state),
                daemon=True,
            )
            spinner_runner.start()
        except Exception:
            stop_event = threading.Event()
            status_state = type("StatusState", (), {})()
            status_state.text = text
            status_state.is_visible = True

            def _spinner_thread():
                _loading_spinner_worker(text, stop_event, status_state)

            spinner_runner = threading.Thread(target=_spinner_thread, daemon=True)
            spinner_runner.start()

        def update_status(new_text: str):
            if status_state is not None:
                status_state.text = new_text
                status_state.is_visible = "正在尝试联网获取" not in new_text and "正在连接 ModelScope" not in new_text

        try:
            yield update_status
        finally:
            if stop_event is not None:
                stop_event.set()
            if spinner_runner is not None:
                spinner_runner.join(timeout=0.5)
            if manager is not None:
                manager.shutdown()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def show_notice(self, text: str, title: str = "提示", style: str = "blue"):
        """显示统一风格的提示面板。"""
        color_map = {
            "blue": BLUE,
            "cyan": CYAN,
            "green": GREEN,
            "yellow": YELLOW,
            "red": RED,
        }
        sys.stdout.write(make_box([text], title=f" {title} ", color=color_map.get(style, BLUE)) + "\n")
        sys.stdout.flush()

    def get_current_language(self) -> str:
        return self.supported_languages[self.current_language_idx]

    def switch_language(self) -> str:
        self.current_language_idx = (self.current_language_idx + 1) % len(self.supported_languages)
        return self.supported_languages[self.current_language_idx]
