"""Run with: python -m unittest discover -s dossier/tests -t ."""
import unittest

import numpy as np
import pandas as pd

from dossier import agent as A


def _market(n=40, bad_on=None, growth=0.5):
    days = pd.bdate_range("2026-01-01", periods=n)
    px = pd.Series(np.linspace(100, 140, n), index=days)
    bars = pd.DataFrame({"Open": px * 0.99, "Close": px})
    known = pd.DataFrame(index=days)
    known["weak_results"] = False
    known["profit_decline"] = False
    known["note"] = ""
    if bad_on is not None:
        known.iloc[bad_on, known.columns.get_loc("weak_results")] = True
        known.iloc[bad_on, known.columns.get_loc("note")] = "test"
    known["revenue_yoy"] = growth
    known["growth_note"] = "test"
    known["vol63"] = 0.70
    return bars, known


class Policy(unittest.TestCase):
    def test_enters_at_next_open_with_vol_sizing(self):
        bars, known = _market()
        book, _ = A.simulate(A.CONFIGS[0], bars, known, bars.index[0])
        self.assertEqual(book.entry["time"], bars.index[1])            # decided day 0, filled day 1
        self.assertEqual(book.entry["price"], bars["Open"].iloc[1])
        self.assertAlmostEqual(book.entry["shares"] * book.entry["price"] / A.CAPITAL, 0.5, delta=0.01)  # 35% / 70%

    def test_bad_results_exit_and_cool_off(self):
        bars, known = _market(bad_on=10)
        book, _ = A.simulate(A.CONFIGS[0], bars, known, bars.index[0])
        self.assertEqual(book.trades[0]["exit_time"], bars.index[11])   # sold at the open after the signal
        reentry = book.entry["time"]
        self.assertGreater(bars.index.get_loc(reentry), 10 + A.COOL_OFF)

    def test_no_entry_when_not_growing(self):
        bars, known = _market(growth=-0.1)
        book, _ = A.simulate(A.CONFIGS[0], bars, known, bars.index[0])
        self.assertIsNone(book.entry)
        self.assertEqual(book.trades, [])

    def test_config_without_exits_ignores_bad_results(self):
        bars, known = _market(bad_on=10)
        book, _ = A.simulate(A.CONFIGS[2], bars, known, bars.index[0])
        self.assertEqual(book.trades, [])


class Charges(unittest.TestCase):
    def test_round_trip_matches_dashboard_cost_model(self):
        # Same schedule as the dashboard's existing research block (0.3854% at ₹1 lakh).
        self.assertAlmostEqual(A.round_trip_pct(1e5), 0.3854, places=3)


if __name__ == "__main__":
    unittest.main()
