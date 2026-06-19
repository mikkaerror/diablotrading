from __future__ import annotations

"""Small NYSE session-calendar helpers shared by desk scheduling modules."""

from datetime import date, timedelta
from functools import lru_cache

from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)


class NyseHolidayCalendar(AbstractHolidayCalendar):
    """NYSE full-day holidays used by the desk's next-session clocks."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday(
            "Juneteenth",
            month=6,
            day=19,
            start_date="2022-06-19",
            observance=nearest_workday,
        ),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


@lru_cache(maxsize=8)
def market_holidays(year: int) -> frozenset[date]:
    """Return observed NYSE full-day holidays around one calendar year."""
    values = NyseHolidayCalendar().holidays(
        start=f"{year - 1}-12-20",
        end=f"{year + 1}-01-10",
    )
    return frozenset(value.date() for value in values)


def is_market_session(value: date) -> bool:
    """Return whether ``value`` is a regular U.S. equity market session."""
    return value.weekday() < 5 and value not in market_holidays(value.year)


def next_market_session(value: date) -> date:
    """Return the first regular market session after ``value``."""
    candidate = value + timedelta(days=1)
    while not is_market_session(candidate):
        candidate += timedelta(days=1)
    return candidate
