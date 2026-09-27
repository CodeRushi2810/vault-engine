"""Run with: python -m unittest discover -s dossier/tests -t .

Texts below are shortened from real NETWEB / peer filings."""
import unittest

from dossier import filings as F
from dossier.sources import financials


class Boxes(unittest.TestCase):
    def test_label_first_layout(self):
        f = {x["kind"]: x["value"] for x in F.business_facts(
            ["plan to setup service network Order Book ₹ 994 Mn L1# ₹ 5,392 Mn Pipeline# ₹ 22,845 Mn Strong"])}
        self.assertEqual(f["order_book"], 994e6)
        self.assertEqual(f["l1_position"], 5392e6)
        self.assertEqual(f["pipeline"], 22845e6)

    def test_value_first_layout(self):
        f = {x["kind"]: x["value"] for x in F.business_facts(
            ["Our order book stood at ₹25,069.35 million as of 30th June'26. Strong Business Visibility "
             "₹104,100.00 Mn Pipeline* ₹8,480.47 Mn L1* ₹25,069.35 Mn Order Book Strong business pipeline"])}
        self.assertAlmostEqual(f["pipeline"], 104100e6, delta=1)
        self.assertAlmostEqual(f["l1_position"], 8480.47e6, delta=1)
        self.assertAlmostEqual(f["order_book"], 25069.35e6, delta=1)

    def test_pipeline_label_does_not_steal_order_book(self):
        f = {x["kind"]: x["value"] for x in F.business_facts(
            ["Strong Order Pipeline: Order book - ₹3,603 Mn; L1 ₹3,481 Mn; Pipeline ₹38,149 Mn."])}
        self.assertEqual(f["pipeline"], 38149e6)

    def test_transcripts_give_no_amounts(self):
        f = F.business_facts(["the order book is INR400 crores last quarter"], amounts=False)
        self.assertEqual([x for x in f if x["kind"] == "order_book"], [])


class Guidance(unittest.TestCase):
    def test_ebitda_guidance(self):
        f = F.business_facts(["But still I'm very confident of maintaining a 14% EBITDA, which I have always guided 13% to 14%."], amounts=False)
        self.assertIn({"kind": "margin_guidance", "value": [13.0, 14.0]}, [{k: x[k] for k in ("kind", "value")} for x in f])

    def test_pat_margin_is_not_ebitda_guidance(self):
        f = F.business_facts(["you've given revenue guidance of 35% to 40% year-on-year and EBITDA margin of 14% "
                              "and PAT margin guide is of 10% to 10.5%, so after these orders"], amounts=False)
        self.assertEqual([x for x in f if x["kind"] == "margin_guidance"], [])

    def test_revenue_growth_guidance(self):
        f = F.business_facts(["Backed by this momentum, we are confident in achieving a 35% to 40% CAGR in top line growth."], amounts=False)
        self.assertEqual([x["value"] for x in f if x["kind"] == "revenue_growth_guidance"], [[35.0, 40.0]])


class Ratings(unittest.TestCase):
    def test_upgrade_beats_reaffirm(self):
        f = F.rating_facts(["CRISIL Ratings Limited has upgraded its Long-term rating to 'Crisil A+ / Stable'; short-term rating reaffirmed."])
        self.assertEqual((f[0]["value"], f[0]["agency"]), ("upgrade", "CRISIL"))

    def test_reaffirm(self):
        f = F.rating_facts(["The Rating Committee of ICRA, after due consideration has reaffirmed the ratings."])
        self.assertEqual((f[0]["value"], f[0]["agency"]), ("reaffirm", "ICRA"))


class Orders(unittest.TestCase):
    def test_crore_amount(self):
        f = F.order_facts(["received the Purchase order for the supply of servers. The estimated order value (excluding GST) "
                           "is approximately Rs. 1,734 Crores (Rupees One Thousand Seven Hundred and Thirty -Four Crores Only)"])
        self.assertEqual(f[0]["value"], 1734e7)

    def test_indian_digit_grouping_in_rupees(self):
        f = F.order_facts(["The value of the said order is approximately Rs. 8,48,84,610/- (exclusive of applicable taxes)"])
        self.assertEqual(f[0]["value"], 84884610)


class Financials(unittest.TestCase):
    def test_negative_in_brackets(self):
        self.assertEqual(financials._num("(9,703.90)"), -9703.90)
        self.assertEqual(financials._num("81,968.60"), 81968.60)
        self.assertIsNone(financials._num("null"))


if __name__ == "__main__":
    unittest.main()
