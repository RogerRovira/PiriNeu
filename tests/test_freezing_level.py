from freezing_level import derive_freezing_level

HEIGHTS = [110.0, 780.0, 1450.0, 3010.0]


def test_normal_crossing_is_interpolated():
    fl = derive_freezing_level([5.0, 2.0, -1.0, -8.0], HEIGHTS)
    # crossing between 925 hPa (2 °C, 780 m) and 850 hPa (-1 °C, 1450 m)
    assert fl.height_m == 780.0 + (1450.0 - 780.0) * (2.0 / 3.0)
    assert fl.capped is False
    assert fl.n_crossings == 1


def test_inversion_takes_lowest_crossing():
    fl = derive_freezing_level([2.0, -1.0, 1.0, -3.0], HEIGHTS)
    # three sign changes; the lowest crossing (1000->925 hPa) wins
    assert fl.height_m == 110.0 + (780.0 - 110.0) * (2.0 / 3.0)
    assert fl.n_crossings == 3
    assert fl.capped is False


def test_whole_column_frozen_caps_at_lowest_level():
    fl = derive_freezing_level([-1.0, -2.0, -5.0, -12.0], HEIGHTS)
    assert fl.height_m == 110.0
    assert fl.capped is True


def test_cold_bottom_with_warm_layer_takes_lowest_crossing():
    # NOT capped: the handoff semantics interpolate the lowest sign change
    fl = derive_freezing_level([-0.5, 3.0, -1.0, -6.0], HEIGHTS)
    expected = 110.0 + (780.0 - 110.0) * (-0.5 / (-0.5 - 3.0))
    assert fl.height_m == expected
    assert fl.capped is False
    assert fl.n_crossings == 2


def test_whole_column_warm_returns_none():
    fl = derive_freezing_level([12.0, 9.0, 5.0, 1.0], HEIGHTS)
    assert fl.height_m is None
    assert fl.capped is False


def test_missing_levels_are_skipped():
    fl = derive_freezing_level([3.0, None, -1.0, -5.0],
                               [110.0, None, 1450.0, 3010.0])
    # interpolates between 1000 hPa (3 °C) and 850 hPa (-1 °C)
    assert fl.height_m == 110.0 + (1450.0 - 110.0) * (3.0 / 4.0)


def test_fewer_than_two_valid_levels_returns_none():
    fl = derive_freezing_level([-3.0, None, None, None],
                               [110.0, None, None, None])
    assert fl.height_m is None
    assert fl.capped is False
