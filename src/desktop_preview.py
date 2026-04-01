"""桌面模式的原生悬浮预览。"""

from __future__ import annotations

import os
from typing import Tuple


def _compute_overlay_origin(
    screen_frame: tuple[float, float, float, float],
    panel_width: float,
    panel_height: float,
    anchor_rect: Tuple[float, float, float, float] | None,
    *,
    center_on_screen: bool = False,
) -> tuple[float, float]:
    """根据焦点输入框位置计算浮窗坐标。"""
    screen_x, screen_y, screen_width, screen_height = screen_frame
    if center_on_screen or anchor_rect is None:
        return (
            screen_x + (screen_width - panel_width) / 2,
            screen_y + (screen_height - panel_height) / 2,
        )

    anchor_x, anchor_y, anchor_width, anchor_height = anchor_rect
    new_x = anchor_x
    new_y = anchor_y - panel_height - 6

    if new_y < screen_y + 50:
        new_y = anchor_y + anchor_height + 6

    if new_x + panel_width > screen_x + screen_width - 10:
        new_x = screen_x + screen_width - panel_width - 10
    if new_x < screen_x + 10:
        new_x = screen_x + 10

    return (new_x, new_y)


def _screen_frame_to_tuple(screen_frame) -> tuple[float, float, float, float]:
    """将 NSScreen.frame() 统一转换成可测试的元组。"""
    return (
        float(screen_frame.origin.x),
        float(screen_frame.origin.y),
        float(screen_frame.size.width),
        float(screen_frame.size.height),
    )


def _global_top_y(screen_frames: list[tuple[float, float, float, float]]) -> float:
    """返回多屏全局坐标系的顶部 y。"""
    return max((screen_y + screen_height for _, screen_y, _, screen_height in screen_frames), default=0.0)


def _find_screen_frame_for_anchor(
    screen_frames: list[tuple[float, float, float, float]],
    anchor_rect: Tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    """找到锚点所在的屏幕 frame。"""
    if not screen_frames:
        return None
    if anchor_rect is None:
        return screen_frames[0]

    anchor_x, anchor_y, anchor_width, anchor_height = anchor_rect
    center_x = anchor_x + (anchor_width / 2)
    center_y = anchor_y + (anchor_height / 2)
    for screen_frame in screen_frames:
        screen_x, screen_y, screen_width, screen_height = screen_frame
        if (
            screen_x <= center_x <= screen_x + screen_width
            and screen_y <= center_y <= screen_y + screen_height
        ):
            return screen_frame

    return screen_frames[0]


def _find_screen_frame_for_point(
    screen_frames: list[tuple[float, float, float, float]],
    point: tuple[float, float] | None,
) -> tuple[float, float, float, float] | None:
    """根据某个点找到对应屏幕。"""
    if not screen_frames:
        return None
    if point is None:
        return screen_frames[0]

    point_x, point_y = point
    for screen_frame in screen_frames:
        screen_x, screen_y, screen_width, screen_height = screen_frame
        if (
            screen_x <= point_x <= screen_x + screen_width
            and screen_y <= point_y <= screen_y + screen_height
        ):
            return screen_frame

    return screen_frames[0]


def _rect_within_window(
    rect: tuple[float, float, float, float] | None,
    window_rect: tuple[float, float, float, float] | None,
    *,
    tolerance: float = 32.0,
) -> bool:
    """判断焦点元素矩形是否合理地落在当前窗口范围内。"""
    if rect is None or window_rect is None:
        return False

    rect_x, rect_y, rect_width, rect_height = rect
    window_x, window_y, window_width, window_height = window_rect

    rect_left = rect_x
    rect_right = rect_x + rect_width
    rect_bottom = rect_y
    rect_top = rect_y + rect_height

    window_left = window_x - tolerance
    window_right = window_x + window_width + tolerance
    window_bottom = window_y - tolerance
    window_top = window_y + window_height + tolerance

    return (
        window_left <= rect_left <= window_right
        and window_left <= rect_right <= window_right
        and window_bottom <= rect_bottom <= window_top
        and window_bottom <= rect_top <= window_top
    )


class DesktopPreviewOverlay:
    """使用 macOS 原生 NSPanel 显示录音预览。"""

    def __init__(self, debug: bool = False):
        self._started = False
        self._call_after = None
        self._panel = None
        self._text_field = None
        self._padding_h = 14
        self._padding_v = 10
        self._max_width = 680
        self._font_size = 21.0
        self._text_vertical_shift = -3.0
        self._debug = debug or os.getenv("VOICE_DESKTOP_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

    def _get_mouse_location(self) -> tuple[float, float] | None:
        """获取当前鼠标全局位置，用于无法读取输入锚点时的回退。"""
        try:
            from AppKit import NSEvent
        except Exception:
            return None

        point = NSEvent.mouseLocation()
        return (float(point.x), float(point.y))

    def _get_all_screen_frames(self) -> list[tuple[float, float, float, float]]:
        """获取所有显示器的 frame。"""
        try:
            from AppKit import NSScreen
        except Exception:
            return []

        return [_screen_frame_to_tuple(screen.frame()) for screen in NSScreen.screens()]

    def _get_focus_anchor_rect(self) -> Tuple[float, float, float, float] | None:
        """优先获取光标/选区位置，失败再回退到焦点输入区域。"""
        try:
            from AppKit import NSWorkspace
            from ApplicationServices import (
                AXUIElementCopyAttributeValue,
                AXUIElementCopyParameterizedAttributeValue,
                AXUIElementCreateApplication,
                AXValueGetValue,
                kAXBoundsForRangeParameterizedAttribute,
                kAXFocusedUIElementAttribute,
                kAXFocusedWindowAttribute,
                kAXPositionAttribute,
                kAXSelectedTextRangeAttribute,
                kAXSizeAttribute,
                kAXValueTypeCGPoint,
                kAXValueTypeCGRect,
                kAXValueTypeCGSize,
            )
        except Exception:
            return None

        workspace = NSWorkspace.sharedWorkspace()
        front_app = workspace.frontmostApplication()
        if front_app is None:
            return None

        screen_frames = self._get_all_screen_frames()
        global_top = _global_top_y(screen_frames)

        app_element = AXUIElementCreateApplication(front_app.processIdentifier())
        if app_element is None:
            return None

        err, focused_element = AXUIElementCopyAttributeValue(app_element, kAXFocusedUIElementAttribute, None)
        if err != 0 or focused_element is None:
            return None

        # 先尝试获取当前选区/光标位置，更贴近真实插入点。
        try:
            err, selected_range = AXUIElementCopyAttributeValue(
                focused_element,
                kAXSelectedTextRangeAttribute,
                None,
            )
            if err == 0 and selected_range is not None:
                err, caret_bounds_value = AXUIElementCopyParameterizedAttributeValue(
                    focused_element,
                    kAXBoundsForRangeParameterizedAttribute,
                    selected_range,
                    None,
                )
                if err == 0 and caret_bounds_value is not None:
                    success, rect = AXValueGetValue(caret_bounds_value, kAXValueTypeCGRect, None)
                    if success:
                        width = max(rect.size.width, 1)
                        height = max(rect.size.height, 1)
                        return (
                            float(rect.origin.x),
                            float(global_top - rect.origin.y - rect.size.height),
                            float(width),
                            float(height),
                        )
        except Exception:
            pass

        err, position_value = AXUIElementCopyAttributeValue(focused_element, kAXPositionAttribute, None)
        if err != 0 or position_value is None:
            return None

        err, size_value = AXUIElementCopyAttributeValue(focused_element, kAXSizeAttribute, None)
        if err != 0 or size_value is None:
            return None

        success, point = AXValueGetValue(position_value, kAXValueTypeCGPoint, None)
        if not success:
            return None

        success, size = AXValueGetValue(size_value, kAXValueTypeCGSize, None)
        if not success:
            return None

        return (
            float(point.x),
            float(global_top - point.y - size.height),
            float(size.width),
            float(size.height),
        )

        # Unreachable kept for clarity.

    def _get_focused_window_rect(self) -> Tuple[float, float, float, float] | None:
        """回退获取当前焦点窗口位置。"""
        try:
            from AppKit import NSWorkspace
            from ApplicationServices import (
                AXUIElementCopyAttributeValue,
                AXUIElementCreateApplication,
                AXValueGetValue,
                kAXFocusedWindowAttribute,
                kAXPositionAttribute,
                kAXSizeAttribute,
                kAXValueTypeCGPoint,
                kAXValueTypeCGSize,
            )
        except Exception:
            return None

        workspace = NSWorkspace.sharedWorkspace()
        front_app = workspace.frontmostApplication()
        if front_app is None:
            return None

        screen_frames = self._get_all_screen_frames()
        global_top = _global_top_y(screen_frames)

        app_element = AXUIElementCreateApplication(front_app.processIdentifier())
        if app_element is None:
            return None

        err, focused_window = AXUIElementCopyAttributeValue(app_element, kAXFocusedWindowAttribute, None)
        if err != 0 or focused_window is None:
            return None

        err, position_value = AXUIElementCopyAttributeValue(focused_window, kAXPositionAttribute, None)
        if err != 0 or position_value is None:
            return None

        err, size_value = AXUIElementCopyAttributeValue(focused_window, kAXSizeAttribute, None)
        if err != 0 or size_value is None:
            return None

        success, point = AXValueGetValue(position_value, kAXValueTypeCGPoint, None)
        if not success:
            return None

        success, size = AXValueGetValue(size_value, kAXValueTypeCGSize, None)
        if not success:
            return None

        return (
            float(point.x),
            float(global_top - point.y - size.height),
            float(size.width),
            float(size.height),
        )

    def _resolve_anchor_rect(self) -> tuple[str, tuple[float, float, float, float] | None]:
        """返回当前命中的定位来源与锚点矩形。"""
        caret_or_element = self._get_focus_anchor_rect()
        focused_window = self._get_focused_window_rect()

        if caret_or_element is not None and _rect_within_window(caret_or_element, focused_window):
            return ("focused-element", caret_or_element)

        if focused_window is not None:
            return ("focused-window", focused_window)

        return ("mouse-screen", None)

    def start(self) -> None:
        """在主线程初始化预览窗口。"""
        if self._started:
            return
        self._started = True

        from AppKit import (
            NSApplication,
            NSBackingStoreBuffered,
            NSColor,
            NSFloatingWindowLevel,
            NSFont,
            NSMakeRect,
            NSPanel,
            NSScreen,
            NSTextAlignmentLeft,
            NSTextField,
            NSWindowStyleMaskBorderless,
            NSWindowStyleMaskNonactivatingPanel,
        )
        from PyObjCTools import AppHelper

        NSApplication.sharedApplication()
        self._call_after = AppHelper.callAfter

        screen = NSScreen.mainScreen()
        screen_frame = _screen_frame_to_tuple(screen.frame())
        width = 360
        height = 64
        x = screen_frame[0] + (screen_frame[2] - width) / 2
        y = screen_frame[1] + screen_frame[3] - 118

        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setHasShadow_(True)
        panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.03, 0.16, 0.2, 0.92))
        panel.setMovableByWindowBackground_(True)

        content_view = panel.contentView()
        content_view.setWantsLayer_(True)
        layer = content_view.layer()
        layer.setCornerRadius_(0.0)
        layer.setMasksToBounds_(True)
        layer.setBorderWidth_(1.0)
        layer.setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.07, 0.54, 0.95, 0.55).CGColor())

        text_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                self._padding_h,
                self._padding_v + self._text_vertical_shift,
                width - self._padding_h * 2,
                height - self._padding_v * 2,
            )
        )
        text_field.setStringValue_("正在聆听...")
        text_field.setBezeled_(False)
        text_field.setDrawsBackground_(False)
        text_field.setEditable_(False)
        text_field.setSelectable_(False)
        text_field.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.85, 0.96, 0.98, 1.0))
        text_field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(self._font_size, 0.0))
        text_field.setAlignment_(NSTextAlignmentLeft)
        text_field.cell().setWraps_(True)
        text_field.cell().setLineBreakMode_(0)
        content_view.addSubview_(text_field)

        self._panel = panel
        self._text_field = text_field

    def show(self, text: str = "正在聆听...") -> None:
        self.start()
        self._call_after(self._show_internal, text)

    def update_text(self, text: str) -> None:
        self.start()
        self._call_after(self._update_internal, text)

    def hide(self) -> None:
        if self._started:
            self._call_after(self._hide_internal)

    def run_event_loop(self) -> None:
        """在主线程运行 AppKit event loop。"""
        self.start()
        from PyObjCTools import AppHelper

        AppHelper.runConsoleEventLoop(installInterrupt=True)

    def _coerce_display_text(self, text: str) -> str:
        display_text = text.strip() or "正在聆听..."
        if len(display_text) > 140:
            display_text = "..." + display_text[-137:]
        return display_text

    def _show_internal(self, text: str) -> None:
        self._update_internal(text)
        if self._panel is not None:
            self._panel.orderFrontRegardless()

    def _update_internal(self, text: str) -> None:
        if self._panel is None or self._text_field is None:
            return

        from AppKit import NSMakeRect, NSScreen

        display_text = self._coerce_display_text(text)
        self._text_field.setStringValue_(display_text)

        cell = self._text_field.cell()
        max_text_width = self._max_width - self._padding_h * 2
        text_size = cell.cellSizeForBounds_(NSMakeRect(0, 0, max_text_width, 10000))
        width = min(max(text_size.width + self._padding_h * 2 + 20, 280), self._max_width)
        height = min(max(text_size.height + self._padding_v * 2 + 6, 56), 190)

        anchor_source, anchor_rect = self._resolve_anchor_rect()
        screen_frames = self._get_all_screen_frames()
        if anchor_rect is not None:
            screen_frame = _find_screen_frame_for_anchor(screen_frames, anchor_rect)
        else:
            screen_frame = _find_screen_frame_for_point(screen_frames, self._get_mouse_location())
        if screen_frame is None:
            return
        effective_anchor = anchor_rect
        center_on_screen = False
        if anchor_source == "focused-window" and anchor_rect is not None:
            center_on_screen = True
            effective_anchor = None
        elif anchor_source == "mouse-screen":
            center_on_screen = True
        x, y = _compute_overlay_origin(
            screen_frame,
            width,
            height,
            effective_anchor,
            center_on_screen=center_on_screen,
        )
        self._panel.setFrame_display_(NSMakeRect(x, y, width, height), True)
        self._text_field.setFrame_(
            NSMakeRect(
                self._padding_h,
                self._padding_v + self._text_vertical_shift,
                width - self._padding_h * 2,
                height - self._padding_v * 2,
            )
        )

    def _hide_internal(self) -> None:
        if self._panel is not None:
            self._panel.orderOut_(None)
