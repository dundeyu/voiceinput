from desktop_preview import (
    _compute_overlay_origin,
    _find_screen_frame_for_anchor,
    _find_screen_frame_for_point,
)


def test_compute_overlay_origin_falls_back_to_top_center_without_anchor():
    x, y = _compute_overlay_origin((0, 0, 1440, 900), 300, 60, None)

    assert x == 570
    assert y == 420


def test_compute_overlay_origin_prefers_position_below_anchor():
    x, y = _compute_overlay_origin((0, 0, 1440, 900), 320, 60, (200, 500, 400, 40))

    assert x == 200
    assert y == 434


def test_compute_overlay_origin_moves_above_anchor_when_bottom_space_is_small():
    x, y = _compute_overlay_origin((0, 0, 1440, 900), 320, 60, (200, 40, 400, 30))

    assert x == 200
    assert y == 76


def test_compute_overlay_origin_clamps_to_screen_bounds():
    x, y = _compute_overlay_origin((0, 0, 1000, 700), 320, 60, (900, 300, 100, 40))

    assert x == 670
    assert y == 234


def test_find_screen_frame_for_anchor_uses_matching_external_display():
    screens = [(0, 0, 1512, 982), (1512, 0, 1920, 1080)]

    screen = _find_screen_frame_for_anchor(screens, (1800, 400, 200, 40))

    assert screen == (1512, 0, 1920, 1080)


def test_find_screen_frame_for_point_uses_mouse_location_when_no_anchor():
    screens = [(0, 0, 1512, 982), (1512, 0, 1920, 1080)]

    screen = _find_screen_frame_for_point(screens, (2000, 300))

    assert screen == (1512, 0, 1920, 1080)


def test_compute_overlay_origin_can_force_screen_center():
    x, y = _compute_overlay_origin((1512, -938, 1080, 1920), 320, 60, (1800, 200, 400, 40), center_on_screen=True)

    assert x == 1892
    assert y == -8
