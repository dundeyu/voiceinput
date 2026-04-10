"""全局热键监听，当前用于 macOS 下的 Option+Space 语音输入。"""

from __future__ import annotations

import logging
import threading
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
        self.pending_trigger = False
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
            self.pending_trigger = True
            self.last_trigger_time = now

        return HotkeyMatchResult(triggered=False)

    def on_release_name(self, key_name: str | None) -> HotkeyMatchResult:
        """处理释放事件。"""
        should_trigger = False
        if key_name in {"alt", "alt_l", "alt_r", "option"}:
            self.option_pressed = False
            should_trigger = self.pending_trigger
            self.pending_trigger = False
        elif key_name == "space":
            self.space_pressed = False

        if not self.option_pressed or not self.space_pressed:
            self.combo_active = False

        return HotkeyMatchResult(triggered=should_trigger)


class GlobalHotkeyListener:
    """基于 Quartz HID event tap 的全局热键监听器。"""

    _SPACE_KEYCODE = 49
    _OPTION_KEYCODES = {58: "alt_l", 61: "alt_r"}

    def __init__(
        self,
        on_toggle: Callable[[], None],
        detector: OptionSpaceDetector | None = None,
        intercept: bool = False,
    ):
        self.on_toggle = on_toggle
        self.detector = detector or OptionSpaceDetector()
        self.intercept = intercept
        self._run_loop = None
        self._tap = None
        self._run_loop_source = None
        self._lock = threading.Lock()

    def _emit_toggle(self) -> None:
        logger.info("检测到全局热键 Option+Space")
        threading.Thread(target=self.on_toggle, name="desktop-toggle-worker", daemon=True).start()

    def _handle_press_name(self, key_name: str | None) -> None:
        self.detector.on_press_name(key_name)

    def _handle_release_name(self, key_name: str | None) -> None:
        result = self.detector.on_release_name(key_name)
        if result.triggered:
            self._emit_toggle()

    def _should_intercept_space_event(self) -> bool:
        if not self.intercept:
            return False
        return self.detector.option_pressed or self.detector.pending_trigger

    def _handle_quartz_event(self, event_type, event):
        from Quartz import (
            CGEventGetFlags,
            CGEventGetIntegerValueField,
            kCGEventFlagMaskAlternate,
            kCGEventFlagsChanged,
            kCGEventKeyDown,
            kCGEventKeyUp,
            kCGKeyboardEventKeycode,
        )

        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)

        if event_type == kCGEventFlagsChanged and keycode in self._OPTION_KEYCODES:
            key_name = self._OPTION_KEYCODES[keycode]
            flags = CGEventGetFlags(event)
            if flags & kCGEventFlagMaskAlternate:
                self._handle_press_name(key_name)
            else:
                self._handle_release_name(key_name)
            return event

        if keycode != self._SPACE_KEYCODE:
            return event

        if event_type == kCGEventKeyDown:
            self._handle_press_name("space")
            if self._should_intercept_space_event():
                return None
            return event

        if event_type == kCGEventKeyUp:
            self._handle_release_name("space")
            if self._should_intercept_space_event():
                return None
            return event

        return event

    def _quartz_callback(self, _proxy, event_type, event, _refcon):
        return self._handle_quartz_event(event_type, event)

    def listen_forever(self) -> None:
        """阻塞式开启全局监听。"""
        from CoreFoundation import (
            CFMachPortCreateRunLoopSource,
            CFRunLoopAddSource,
            CFRunLoopGetCurrent,
            CFRunLoopRemoveSource,
            CFRunLoopRun,
            kCFRunLoopDefaultMode,
        )
        from Quartz import (
            CGEventMaskBit,
            CGEventTapCreate,
            CGEventTapEnable,
            kCGEventFlagsChanged,
            kCGEventKeyDown,
            kCGEventKeyUp,
            kCGEventTapOptionDefault,
            kCGHIDEventTap,
            kCGHeadInsertEventTap,
        )

        event_mask = (
            CGEventMaskBit(kCGEventKeyDown)
            | CGEventMaskBit(kCGEventKeyUp)
            | CGEventMaskBit(kCGEventFlagsChanged)
        )
        tap = CGEventTapCreate(
            kCGHIDEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            event_mask,
            self._quartz_callback,
            None,
        )
        if tap is None:
            logger.error("创建 Quartz 热键监听失败，请检查辅助功能权限")
            return

        run_loop_source = CFMachPortCreateRunLoopSource(None, tap, 0)
        run_loop = CFRunLoopGetCurrent()

        with self._lock:
            self._tap = tap
            self._run_loop_source = run_loop_source
            self._run_loop = run_loop

        try:
            CFRunLoopAddSource(run_loop, run_loop_source, kCFRunLoopDefaultMode)
            CGEventTapEnable(tap, True)
            CFRunLoopRun()
        finally:
            with self._lock:
                current_run_loop = self._run_loop
                current_source = self._run_loop_source
                self._run_loop = None
                self._run_loop_source = None
                self._tap = None
            if current_run_loop is not None and current_source is not None:
                CFRunLoopRemoveSource(current_run_loop, current_source, kCFRunLoopDefaultMode)

    def stop(self) -> None:
        from CoreFoundation import CFRunLoopStop

        with self._lock:
            run_loop = self._run_loop

        if run_loop is not None:
            CFRunLoopStop(run_loop)
