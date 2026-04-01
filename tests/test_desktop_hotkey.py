from desktop_hotkey import OptionSpaceDetector, _normalize_key_name


class FakeKey:
    def __init__(self, *, char=None, name=None):
        self.char = char
        self.name = name


def test_normalize_key_name_prefers_char():
    assert _normalize_key_name(FakeKey(char="F")) == "f"


def test_option_space_detector_triggers_once_per_combo_press():
    detector = OptionSpaceDetector(debounce_seconds=0)

    assert detector.on_press_name("alt_l", now=1.0).triggered is False
    assert detector.on_press_name("space", now=1.0).triggered is True
    assert detector.on_press_name("space", now=1.0).triggered is False

    detector.on_release_name("space")
    detector.on_release_name("alt_l")

    assert detector.on_press_name("alt_l", now=2.0).triggered is False
    assert detector.on_press_name("space", now=2.0).triggered is True


def test_option_space_detector_respects_debounce():
    detector = OptionSpaceDetector(debounce_seconds=0.5)

    detector.on_press_name("alt_l", now=1.0)
    assert detector.on_press_name("space", now=1.0).triggered is True
    detector.on_release_name("space")
    detector.on_release_name("alt_l")
    detector.on_press_name("alt_l", now=1.2)
    assert detector.on_press_name("space", now=1.2).triggered is False
