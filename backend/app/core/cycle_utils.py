from __future__ import annotations

import re
from datetime import date


def get_cycle_year(d: date, reset_month: int, reset_day: int) -> int:
    """Return the start year of the cycle that contains date d.

    A cycle starts the day after (reset_month, reset_day) and ends on the
    reset date of the following year.  Example: reset_month=7, reset_day=31
    means the cycle runs 01 Aug – 31 Jul.  A date of 2025-08-01 returns 2025;
    a date of 2025-07-31 returns 2024.
    """
    try:
        boundary = date(d.year, reset_month, reset_day)
    except ValueError:
        # Invalid day for month (e.g. Feb 31) – clamp to last valid day
        import calendar
        last_day = calendar.monthrange(d.year, reset_month)[1]
        boundary = date(d.year, reset_month, min(reset_day, last_day))

    return d.year if d > boundary else d.year - 1


def format_cycle_name(pattern: str | None, cycle_year: int) -> str:
    """Format a cycle name from the given pattern and cycle_year.

    Placeholders:
      [cy]     – cycle start year  (e.g. 2025)
      [cy_end] – cycle end year    (e.g. 2026)
    Both square-bracket and curly-bracket variants are accepted.
    """
    if not pattern:
        return f"{cycle_year}/{cycle_year + 1}"
    result = pattern
    for placeholder, value in (
        ("[cy_end]", str(cycle_year + 1)),
        ("{cy_end}", str(cycle_year + 1)),
        ("[cy]", str(cycle_year)),
        ("{cy}", str(cycle_year)),
    ):
        result = result.replace(placeholder, value)
    return result
