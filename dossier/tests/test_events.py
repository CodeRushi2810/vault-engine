"""Run with: python -m unittest discover -s dossier/tests -t ."""
import unittest
from unittest import mock

import pandas as pd

from dossier import events as E

SESSIONS = pd.DatetimeIndex(["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03"])


class ReactionSession(unittest.TestCase):
    def test_during_market_reacts_same_day(self):
        self.assertEqual(E.reaction_session(pd.Timestamp("2026-07-28 11:00"), SESSIONS), pd.Timestamp("2026-07-28"))

    def test_after_close_reacts_next_session(self):
        self.assertEqual(E.reaction_session(pd.Timestamp("2026-07-28 16:10"), SESSIONS), pd.Timestamp("2026-07-29"))

    def test_weekend_filing_reacts_monday(self):
        self.assertEqual(E.reaction_session(pd.Timestamp("2026-08-01 10:00"), SESSIONS), pd.Timestamp("2026-08-03"))

    def test_closing_half_hour_reacts_next_session(self):
        self.assertEqual(E.reaction_session(pd.Timestamp("2026-07-28 15:18"), SESSIONS), pd.Timestamp("2026-07-29"))

    def test_before_open_reacts_same_day(self):
        self.assertEqual(E.reaction_session(pd.Timestamp("2026-07-29 08:30"), SESSIONS), pd.Timestamp("2026-07-29"))


class Deals(unittest.TestCase):
    def _run(self, rows):
        df = pd.DataFrame(rows, columns=["Date", "Symbol", "ClientName", "Side", "Qty", "Price", "Kind"])
        df["Date"] = pd.to_datetime(df["Date"])
        with mock.patch.object(E.nse_api, "deals", return_value=df):
            ev, _ = E.deals_for(["NETWEB"], "2026-01-01")
        return ev

    def test_round_trippers_are_dropped(self):
        ev = self._run([
            ("2026-07-28", "NETWEB", "GRAVITON RESEARCH CAPITAL LLP", "BUY", 1000, 4500, "bulk"),
            ("2026-07-28", "NETWEB", "GRAVITON RESEARCH CAPITAL LLP", "SELL", 1000, 4510, "bulk"),
        ])
        self.assertTrue(ev.empty)

    def test_institution_and_other_are_separated(self):
        ev = self._run([
            ("2026-07-28", "NETWEB", "ICICI PRUDENTIAL MUTUAL FUND", "BUY", 1000, 4500, "block"),
            ("2026-07-28", "NETWEB", "SOME PERSON", "SELL", 500, 4500, "bulk"),
        ])
        self.assertEqual(set(ev["cond"]), {"inst_deal_buy", "deal_net_sell"})

    def test_arbitrage_desk_is_not_directional(self):
        ev = self._run([("2026-07-28", "NETWEB", "BNP PARIBAS ARBITRAGE", "BUY", 1000, 4500, "bulk")])
        self.assertTrue(ev.empty)


class Holdings(unittest.TestCase):
    def test_promoter_cut_detected(self):
        rows = [
            {"date": "31-DEC-2025", "broadcastDate": "16-JAN-2026 15:51:48", "pr_and_prgrp": "71"},
            {"date": "31-MAR-2026", "broadcastDate": "09-APR-2026 16:28:04", "pr_and_prgrp": "66.98"},
        ]
        with mock.patch.object(E.nse_api, "company", return_value=rows):
            out = E.holdings_for("NETWEB")
        self.assertEqual(list(out["cond"]), ["promoter_cut"])
        self.assertAlmostEqual(out["change_pp"].iloc[0], -4.02)


if __name__ == "__main__":
    unittest.main()
