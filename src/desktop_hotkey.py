"""全局热键监听，当前用于 macOS 下的 Option+Space 语音输入。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


def _normalize_key_name(key) -> str | None:
    """把 pynput key 对象规整成稳定的字符串名。"""
    if hasattr(key, "char") and key.char is not None:
        return key.char.lower()

    key_name = getattr(key, "name", None)
    if isinstance(key_name, str):
        return key_name.lower()

    return None


@dataclass
class HotkeyMatchResult:
    """单次按键处理结果。"""

    triggered: bool = False


class OptionSpaceDetector:
    """检测 Option+Space 组合键，避免重复触发。"""

    def __init__(self, debounce_seconds: float = 0.25):
        self.debounce_seconds = debounce_seconds
        self.option_pressed = False
        self.space_pressed = False
        self.combo_active = False
        self.last_trigger_time = 0.0

    def on_press_name(self, key_name: str | None, now: float | None = None) -> HotkeyMatchResult:
        """处理按下事件。"""
        if key_name in {"alt", "alt_l", "alt_r", "option"}:
            self.option_pressed = True
        elif key_name == "space":
            self.space_pressed = True

        now = time.time() if now is None else now
        if (
            self.option_pressed
            and self.space_pressed
            and not self.combo_active
            and now - self.last_trigger_time >= self.debounce_seconds
        ):
            self.combo_active = True
            self.last_trigger_time = now
            return HotkeyMatchResult(triggered=True)

        return HotkeyMatchResult(triggered=False)

    def on_release_name(self, key_name: str | None) -> None:
        """处理释放事件。"""
        if key_name in {"alt", "alt_l", "alt_r", "option"}:
            self.option_pressed = False
        elif key_name == "space":
            self.space_pressed = False

        if not self.option_pressed or not self.space_pressed:
            self.combo_active = False


class GlobalHotkeyListener:
    """基于 pynput 的全局热键监听器。"""

    def __init__(self, on_toggle: Callable[[], None], detector: OptionSpaceDetector | None = None):
        self.on_toggle = on_toggle
        self.detector = detector or OptionSpaceDetector()

    def _on_press(self, key) -> None:
        key_name = _normalize_key_name(key)
        result = self.detector.on_press_name(key_name)
        if result.triggered:
            logger.info("检测到全局热键 Option+Space")
            self.on_toggle()

    def _on_release(self, key) -> None:
        key_name = _normalize_key_name(key)
        self.detector.on_release_name(key_name)

    def listen_forever(self) -> None:
        """阻塞式开启全局监听。"""
        from pynput.keyboard import Listener

        with Listener(on_press=self._on_press, on_release=self._on_release) as listener:
            listener.join()

