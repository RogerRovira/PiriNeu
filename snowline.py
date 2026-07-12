"""Derive the snow line from pressure-level temperatures.

`freezing_level_height` on meteofrance_seamless returns null (see CLAUDE.md
gotchas), so the snow line is DERIVED by scanning 1000/925/850/700 hPa
temperatures for the 0 °C crossing, interpolated with the real
geopotential heights.
"""
from typing import Optional, Sequence, Tuple

# Ordered from the lowest level (1000 hPa) to the highest (700 hPa).
PRESSURE_LEVELS = ("1000hPa", "925hPa", "850hPa", "700hPa")


def derive_snow_line(temps_c: Sequence[Optional[float]],
                     heights_m: Sequence[Optional[float]]) -> Tuple[Optional[float], bool]:
    """Return (snow_line_m, capped) for one column, ordered low -> high.

    - Normal profile: linear interpolation at the lowest 0 °C crossing.
      Inversions can produce several crossings; the LOWEST wins
      (conservative — snow may reach lower).
    - Column cold from the lowest level up (including whole column <= 0 °C):
      the crossing lies at or below the data floor -> lowest level height
      with capped=True.
    - Whole column > 0 °C: snow line above the column top -> (None, False).
    - Levels with a missing temperature or height are skipped.
    """
    column = [(t, h) for t, h in zip(temps_c, heights_m)
              if t is not None and h is not None]
    if not column:
        return None, False
    if column[0][0] <= 0.0:
        return column[0][1], True
    for (t_lo, h_lo), (t_hi, h_hi) in zip(column, column[1:]):
        if t_lo > 0.0 >= t_hi:
            fraction = t_lo / (t_lo - t_hi)
            return h_lo + (h_hi - h_lo) * fraction, False
    return None, False
