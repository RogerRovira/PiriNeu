from snowline import derive_snow_line

HEIGHTS = [110.0, 780.0, 1450.0, 3010.0]


def test_normal_crossing_is_interpolated():
    line, capped = derive_snow_line([5.0, 2.0, -1.0, -8.0], HEIGHTS)
    # crossing between 925 hPa (2 °C, 780 m) and 850 hPa (-1 °C, 1450 m)
    assert line == 780.0 + (1450.0 - 780.0) * (2.0 / 3.0)
    assert capped is False


def test_inversion_takes_lowest_crossing():
    line, capped = derive_snow_line([2.0, -1.0, 1.0, -3.0], HEIGHTS)
    # first crossing between 1000 hPa (2 °C) and 925 hPa (-1 °C) wins
    assert line == 110.0 + (780.0 - 110.0) * (2.0 / 3.0)
    assert capped is False


def test_whole_column_frozen_caps_at_lowest_level():
    line, capped = derive_snow_line([-1.0, -2.0, -5.0, -12.0], HEIGHTS)
    assert line == 110.0
    assert capped is True


def test_cold_bottom_with_warm_layer_aloft_caps_at_lowest_level():
    line, capped = derive_snow_line([-0.5, 3.0, -1.0, -6.0], HEIGHTS)
    assert line == 110.0
    assert capped is True


def test_whole_column_warm_returns_none():
    line, capped = derive_snow_line([12.0, 9.0, 5.0, 1.0], HEIGHTS)
    assert line is None
    assert capped is False


def test_missing_levels_are_skipped():
    line, capped = derive_snow_line([3.0, None, -1.0, -5.0],
                                    [110.0, None, 1450.0, 3010.0])
    # interpolates between 1000 hPa (3 °C) and 850 hPa (-1 °C)
    assert line == 110.0 + (1450.0 - 110.0) * (3.0 / 4.0)
    assert capped is False


def test_all_missing_returns_none():
    assert derive_snow_line([None] * 4, [None] * 4) == (None, False)
