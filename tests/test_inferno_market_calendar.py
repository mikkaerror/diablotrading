from __future__ import annotations

import unittest
from datetime import date

from inferno_market_calendar import is_market_session, next_market_session


class InfernoMarketCalendarTests(unittest.TestCase):
    def test_juneteenth_weekend_rolls_to_monday(self) -> None:
        self.assertFalse(is_market_session(date(2026, 6, 19)))
        self.assertEqual(next_market_session(date(2026, 6, 18)), date(2026, 6, 22))

    def test_independence_day_observed_rolls_to_monday(self) -> None:
        self.assertFalse(is_market_session(date(2026, 7, 3)))
        self.assertEqual(next_market_session(date(2026, 7, 2)), date(2026, 7, 6))

    def test_regular_weekday_is_a_session(self) -> None:
        self.assertTrue(is_market_session(date(2026, 6, 22)))
