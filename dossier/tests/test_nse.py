"""Run with: python -m unittest discover -s dossier/tests -t ."""
import gzip
import os
import tempfile
import unittest

import pandas as pd

from dossier.sources import nse


class ParseFactor(unittest.TestCase):
    def test_splits(self):
        self.assertEqual(nse.parse_factor(
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share"), 10)
        self.assertEqual(nse.parse_factor(
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"), 5)
        self.assertEqual(nse.parse_factor(
            "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share"), 2)

    def test_bonus_is_new_per_held(self):
        self.assertEqual(nse.parse_factor("Bonus 1:1"), 2)
        self.assertEqual(nse.parse_factor("Bonus 1:2"), 1.5)
        self.assertEqual(nse.parse_factor("Bonus 4:1"), 5)
        self.assertAlmostEqual(nse.parse_factor("Bonus 2:9"), 11 / 9)

    def test_ignores_other_actions(self):
        self.assertIsNone(nse.parse_factor("Interim Dividend - Rs 2 Per Share"))
        self.assertIsNone(nse.parse_factor("Annual General Meeting"))


class Adjust(unittest.TestCase):
    def test_e2e_style_split(self):
        # E2E, 1:10 split on 5 June 2026 (NSE figures).
        raw = pd.DataFrame(
            {"Open": [3990.0, 452.9], "High": [4313.6, 452.9], "Low": [3930.0, 452.9],
             "Close": [4313.6, 452.9], "Volume": [215019.0, 83746.0], "DelivQty": [111990.0, 83746.0]},
            index=pd.to_datetime(["2026-06-04", "2026-06-05"]))
        events = [{"ex_date": pd.Timestamp("2026-06-05"), "factor": 10.0, "subject": "split"}]
        adj, applied = nse.adjust(raw, events)
        self.assertAlmostEqual(adj.loc["2026-06-04", "Close"], 431.36)
        self.assertEqual(adj.loc["2026-06-04", "Volume"], 2150190)
        self.assertEqual(adj.loc["2026-06-05", "Close"], 452.9)
        self.assertTrue(applied[0]["consistent"])

    def test_event_outside_history_is_skipped(self):
        raw = pd.DataFrame({"Close": [100.0, 101.0], "Volume": [1.0, 1.0]},
                           index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        _, applied = nse.adjust(raw, [{"ex_date": pd.Timestamp("2020-01-01"), "factor": 2, "subject": "x"}])
        self.assertEqual(applied, [])

    def test_inconsistent_event_is_flagged(self):
        raw = pd.DataFrame({"Close": [100.0, 99.0], "Volume": [1.0, 1.0]},
                           index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        _, applied = nse.adjust(raw, [{"ex_date": pd.Timestamp("2026-01-02"), "factor": 2, "subject": "x"}])
        self.assertFalse(applied[0]["consistent"])


class ReadFiles(unittest.TestCase):
    BHAV = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
        "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        "NETWEB, EQ, 25-Sep-2026, 4661.50, 4675.00, 4710.00, 4522.00, 4559.00, 4545.00, 4603.94, "
        "696170, 32051.24, 63397, 189579, 27.23\n"
        "SOMEGS, GS, 25-Sep-2026, 100, 100, 100, 100, 100, 100, 100, 10, 1, 1, -, -\n"
    )
    INDEX = (
        "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
        "Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
        "Nifty 50,25-09-2026,23035,23162.7,23020.95,23140.5,77.4,.34,242720711,18949.25,19.56,2.8,1.22\n"
    )

    def _gz(self, text):
        fd, path = tempfile.mkstemp(suffix=".csv.gz")
        os.close(fd)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_read_bhav(self):
        df = nse.read_bhav(self._gz(self.BHAV))
        row = df[df["Symbol"] == "NETWEB"].iloc[0]
        self.assertEqual(row["Series"], "EQ")
        self.assertEqual(row["Date"], pd.Timestamp("2026-09-25"))
        self.assertEqual(row["Open"], 4675.0)
        self.assertEqual(row["DelivPct"], 27.23)
        self.assertTrue(pd.isna(df[df["Symbol"] == "SOMEGS"].iloc[0]["DelivQty"]))

    def test_read_index(self):
        df = nse.read_index(self._gz(self.INDEX))
        self.assertEqual(df.iloc[0]["Index"], "Nifty 50")
        self.assertEqual(df.iloc[0]["Close"], 23140.5)
        self.assertEqual(df.iloc[0]["PE"], 19.56)


if __name__ == "__main__":
    unittest.main()
