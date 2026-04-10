from unittest.mock import Mock, patch

from desktop_hotkey import GlobalHotkeyListener, OptionSpaceDetector, _normalize_key_name


class FakeKey:
    def __init__(self, *, char=None, name=None):
        self.char = char
        self.name = name


def test_normalize_key_name_prefers_char():
    assert _normalize_key_name(FakeKey(char="F")) == "f"


def test_option_space_detector_triggers_once_per_combo_press():
    detector = OptionSpaceDetector(debounce_seconds=0)

    assert detector.on_press_name("alt_l", now=1.0).triggered is False
    assert detector.on_press_name("space", now=1.0).triggered is False
    assert detector.on_press_name("space", now=1.0).triggered is False
    assert detector.on_release_name("space").triggered is False
    assert detector.on_release_name("alt_l").triggered is True

    assert detector.on_press_name("alt_l", now=2.0).triggered is False
    assert detector.on_press_name("space", now=2.0).triggered is False
    assert detector.on_release_name("space").triggered is False
    assert detector.on_release_name("alt_l").triggered is True


def test_option_space_detector_respects_debounce():
    detector = OptionSpaceDetector(debounce_seconds=0.5)

    detector.on_press_name("alt_l", now=1.0)
    assert detector.on_press_name("space", now=1.0).triggered is False
    assert detector.on_release_name("space").triggered is False
    assert detector.on_release_name("alt_l").triggered is True
    detector.on_press_name("alt_l", now=1.2)
    assert detector.on_press_name("space", now=1.2).triggered is False
    assert detector.on_release_name("space").triggered is False
    assert detector.on_release_name("alt_l").triggered is False


def test_option_space_detector_only_triggers_after_option_release_even_if_space_releases_first():
    detector = OptionSpaceDetector(debounce_seconds=0)

    detector.on_press_name("alt_l", now=1.0)
    detector.on_press_name("space", now=1.0)

    assert detector.on_release_name("space").triggered is False
    assert detector.on_release_name("alt_l").triggered is True

    detector.on_press_name("alt_l", now=2.0)
    detector.on_press_name("space", now=2.0)

    assert detector.on_release_name("alt_l").triggered is True
    assert detector.on_release_name("space").triggered is False

    detector.on_release_name("alt_l")
    detector.on_release_name("space")

    assert detector.pending_trigger is False
    assert detector.combo_active is False
    assert detector.option_pressed is False
    assert detector.space_pressed is False
    assert detector.on_press_name("alt_l", now=3.0).triggered is False
    assert detector.on_press_name("space", now=3.0).triggered is False
    assert detector.on_release_name("space").triggered is False
    assert detector.on_release_name("alt_l").triggered is True


def test_global_hotkey_listener_uses_intercept_flag():
    listener = GlobalHotkeyListener(on_toggle=Mock(), intercept=True)

    assert listener.intercept is True


def test_quartz_listener_intercepts_space_keydown_when_option_is_pressed():
    listener = GlobalHotkeyListener(on_toggle=Mock(), intercept=True)
    listener.detector.option_pressed = True

    with (
        patch("Quartz.CGEventGetIntegerValueField", return_value=49),
        patch("Quartz.kCGEventFlagsChanged", 12),
        patch("Quartz.kCGEventKeyDown", 10),
        patch("Quartz.kCGEventKeyUp", 11),
        patch("Quartz.kCGKeyboardEventKeycode", 9),
    ):
        assert listener._handle_quartz_event(10, object()) is None


def test_quartz_listener_intercepts_space_keyup_when_pending_trigger_exists():
    listener = GlobalHotkeyListener(on_toggle=Mock(), intercept=True)
    listener.detector.option_pressed = True
    listener.detector.pending_trigger = True

    with (
        patch("Quartz.CGEventGetIntegerValueField", return_value=49),
        patch("Quartz.kCGEventFlagsChanged", 12),
        patch("Quartz.kCGEventKeyDown", 10),
        patch("Quartz.kCGEventKeyUp", 11),
        patch("Quartz.kCGKeyboardEventKeycode", 9),
    ):
        assert listener._handle_quartz_event(11, object()) is None


def test_quartz_listener_passes_through_unrelated_keycode():
    listener = GlobalHotkeyListener(on_toggle=Mock(), intercept=True)
    event = object()

    with (
        patch("Quartz.CGEventGetIntegerValueField", return_value=12),
        patch("Quartz.kCGEventFlagsChanged", 12),
        patch("Quartz.kCGEventKeyDown", 10),
        patch("Quartz.kCGEventKeyUp", 11),
        patch("Quartz.kCGKeyboardEventKeycode", 9),
    ):
        assert listener._handle_quartz_event(10, event) is event


def test_quartz_listener_triggers_toggle_on_option_release():
    on_toggle = Mock()
    listener = GlobalHotkeyListener(on_toggle=on_toggle, intercept=True, detector=OptionSpaceDetector(debounce_seconds=0))

    thread_instance = Mock()
    with (
        patch("desktop_hotkey.threading.Thread", return_value=thread_instance) as thread_cls,
        patch("Quartz.CGEventGetIntegerValueField", side_effect=[58, 49, 49, 58]),
        patch("Quartz.CGEventGetFlags", side_effect=[0x80000, 0, 0, 0]),
        patch("Quartz.kCGEventFlagMaskAlternate", 0x80000),
        patch("Quartz.kCGEventFlagsChanged", 12),
        patch("Quartz.kCGEventKeyDown", 10),
        patch("Quartz.kCGEventKeyUp", 11),
        patch("Quartz.kCGKeyboardEventKeycode", 9),
    ):
        listener._handle_quartz_event(12, object())
        listener._handle_quartz_event(10, object())
        listener._handle_quartz_event(11, object())
        listener._handle_quartz_event(12, object())

    thread_cls.assert_called_once_with(target=on_toggle, name="desktop-toggle-worker", daemon=True)
    thread_instance.start.assert_called_once_with()


def test_listen_forever_returns_when_tap_creation_fails():
    listener = GlobalHotkeyListener(on_toggle=Mock(), intercept=True)

    with patch("Quartz.CGEventTapCreate", return_value=None):
        listener.listen_forever()


def test_stop_calls_cfrunloop_stop_when_listener_is_running():
    listener = GlobalHotkeyListener(on_toggle=Mock(), intercept=True)
    listener._run_loop = object()

    with patch("CoreFoundation.CFRunLoopStop") as stop_mock:
        listener.stop()

    stop_mock.assert_called_once_with(listener._run_loop)
