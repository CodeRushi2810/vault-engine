"""Power check for the condition study: it must find a planted edge and must
not find a random one. Needs the local NSE archive (`python -m dossier.run
sync`); skipped otherwise. Takes ~20 seconds."""
import os
import unittest

import numpy as np
import pandas as pd

from dossier.sources import nse


@unittest.skipUnless(os.path.isdir(nse.BHAV_DIR) and os.listdir(nse.BHAV_DIR), "NSE archive not synced")
class PlantedSignals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dossier import conditions as C
        from dossier.data import load_index_closes

        m = load_index_closes()["SMALLCAP"]["Close"]

        def future_outperformance(f, b):
            # Look-ahead on purpose: the stock beats Smallcap 250 by 3%+ over
            # the next month, diluted by a coin flip to make it weak.
            mm = m.reindex(b.index)
            stock = b["Close"].shift(-21) / b["Open"].shift(-1) - 1
            index = mm.shift(-21) / mm.shift(-1) - 1
            coin = pd.Series(np.random.default_rng(1).random(len(b)) < 0.5, index=b.index)
            return ((stock - index) > 0.03) & coin

        def coin_flip(f, b):
            return pd.Series(np.random.default_rng(len(b)).random(len(b)) < 0.03, index=b.index)

        saved = dict(C.CONDITIONS)
        C.CONDITIONS.clear()
        C.CONDITIONS.update({
            "planted": ("planted", ("sma50",), future_outperformance),
            "random": ("random", ("sma50",), coin_flip),
            **{k: saved[k] for k in list(saved)[:5]},   # realistic multiple-testing load
        })
        try:
            cls.res = {(r["condition"], r["horizon"]): r for r in C.study()["results"]}
        finally:
            C.CONDITIONS.clear()
            C.CONDITIONS.update(saved)

    def test_finds_planted_edge(self):
        self.assertEqual(self.res[("planted", "1m")]["verdict"], "validated")

    def test_rejects_random(self):
        for h in ("1w", "1m", "3m"):
            self.assertNotEqual(self.res[("random", h)]["verdict"], "validated")


if __name__ == "__main__":
    unittest.main()
