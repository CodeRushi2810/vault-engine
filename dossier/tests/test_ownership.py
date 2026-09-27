"""Shareholding-pattern XBRL parsing, both NSE layouts, and filing dates."""
import unittest

import pandas as pd

from dossier.sources import ownership as O


def _ctx(cid, member, value, typed=False):
    typed_xml = '<xbrldi:typedMember dimension="x">1</xbrldi:typedMember>' if typed else ""
    return (f'<xbrli:context id="{cid}"><xbrli:scenario>'
            f'<xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">in-bse-shp:{member}Member</xbrldi:explicitMember>'
            f'{typed_xml}</xbrli:scenario></xbrli:context>'
            f'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="{cid}" unitRef="pure">{value}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>')


class ParseTest(unittest.TestCase):
    def test_old_layout_percent(self):
        xml = "".join([_ctx("ShareholdingOfPromoterAndPromoterGroupI", "ShareholdingOfPromoterAndPromoterGroup", "37.26"),
                       _ctx("InstitutionsForeignI", "InstitutionsForeign", "11.02"),
                       _ctx("InstitutionsDomesticI", "InstitutionsDomestic", "18.98"),
                       _ctx("MutualFundsOrUtiI", "MutualFundsOrUti", "18.21"),
                       _ctx("PublicShareholdingI", "PublicShareholding", "62.74"),
                       _ctx("MutualFundsOrUti_Holder1", "MutualFundsOrUti", "9.9", typed=True)])
        out = O.parse(xml)
        self.assertEqual((out["promoter"], out["fii"], out["dii"], out["mutual_funds"]), (37.26, 11.02, 18.98, 18.21))

    def test_new_layout_fraction(self):
        xml = "".join([_ctx("ShareholdingOfPromoterAndPromoterGroup_ContextI", "ShareholdingOfPromoterAndPromoterGroup", "0.2936"),
                       _ctx("InstitutionsForeign_ContextI", "InstitutionsForeign", "0.2479"),
                       _ctx("InstitutionsDomestic_ContextI", "InstitutionsDomestic", "0.2235"),
                       _ctx("PublicShareholding_ContextI", "PublicShareholding", "0.7064")])
        out = O.parse(xml)
        self.assertEqual((out["promoter"], out["fii"], out["dii"]), (29.36, 24.79, 22.35))

    def test_missing_totals_rejected(self):
        with self.assertRaises(ValueError):
            O.parse(_ctx("InstitutionsForeignI", "InstitutionsForeign", "11"))


class DatingTest(unittest.TestCase):
    def test_same_day_uses_broadcast_time(self):
        r = {"broadcastDate": "17-JUL-2026 17:44:04", "xbrl": "x/SHP_1695497_17072026054400_WEB.xml"}
        self.assertEqual(O._published(r), pd.Timestamp("2026-07-17 17:44:04"))

    def test_refiled_quarter_uses_original_day(self):
        r = {"broadcastDate": "23-JUL-2024 15:58:36", "xbrl": "x/SHP_182727_963409_20102023051219_WEB.xml"}
        self.assertEqual(O._published(r), pd.Timestamp("2023-10-20 23:59"))


if __name__ == "__main__":
    unittest.main()
