import unittest

import numpy as np
import pandas as pd

from app.valuation import InsufficientValuationDataError, build_rule_based_valuation


def _frames(last_period: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2021-03-01", pd.Timestamp(last_period), freq="QS-MAR")
    quarterly_rows = []
    for date in dates:
        quarter = date.month // 3
        year_scale = 1.0 + (date.year - 2021) * 0.12
        sales = [100.0, 120.0, 140.0, 240.0][quarter - 1] * year_scale
        quarterly_rows.append(
            {
                "Satış Gelirleri": sales,
                "Ana Ortaklık Payları": sales * 0.12,
                "FAVÖK": sales * 0.22,
            }
        )
    quarterly = pd.DataFrame(quarterly_rows, index=dates)
    cumulative = quarterly.groupby(quarterly.index.year).cumsum()

    ratios = pd.DataFrame(index=dates)
    ratios["  Ana Ortaklığa Ait Özkaynaklar"] = np.linspace(500.0, 1100.0, len(dates))
    ratios["  Ödenmiş Sermaye"] = 100.0
    ratios["duzeltilmis_fiyat"] = 20.0
    ratios["net_borc/FAVOK"] = np.linspace(0.8, 0.4, len(dates))
    ratios["F/K"] = np.linspace(8.0, 12.0, len(dates))
    ratios["PD/DD"] = np.linspace(1.2, 2.0, len(dates))
    ratios["FD/FAVÖK"] = np.linspace(5.0, 8.0, len(dates))
    ratios["PD/NS"] = np.linspace(1.0, 1.8, len(dates))
    return cumulative, ratios


class RuleBasedValuationTests(unittest.TestCase):
    def test_new_listing_with_short_history_returns_expected_data_error(self):
        for last_period in ("2022-09-01", "2022-12-01"):
            with self.subTest(last_period=last_period):
                statements, ratios = _frames(last_period)
                with self.assertRaisesRegex(
                    InsufficientValuationDataError,
                    "en az iki tamamlanmış geçmiş mali yıl",
                ):
                    build_rule_based_valuation(statements, ratios)

    def test_interim_period_uses_seasonality_and_only_adds_missing_profit_to_equity(self):
        statements, ratios = _frames("2025-09-01")
        result = build_rule_based_valuation(statements, ratios)

        self.assertEqual(result.summary.iloc[0]["Değerleme Ufku"], "Cari yıl sonu değerlemesi")
        self.assertEqual(int(result.summary.iloc[0]["Açıklanan Çeyrek"]), 3)
        self.assertEqual(int(result.summary.iloc[0]["Tahmin Edilen Çeyrek"]), 1)
        projected_equity = float(result.projection.loc["Baz", "Özkaynak"])
        projected_profit = float(result.projection.loc["Baz", "Net Kâr"])
        reported_profit = float(
            (statements.loc["2025-09-01", "Ana Ortaklık Payları"])
        )
        self.assertAlmostEqual(
            projected_equity,
            float(ratios.iloc[-1]["  Ana Ortaklığa Ait Özkaynaklar"])
            + projected_profit - reported_profit,
        )
        self.assertAlmostEqual(float(result.methods["Güven Ağırlığı %"].sum()), 100.0)

    def test_december_statement_targets_next_year_end(self):
        statements, ratios = _frames("2025-12-01")
        result = build_rule_based_valuation(statements, ratios)

        row = result.summary.iloc[0]
        self.assertEqual(row["Değerleme Ufku"], "12 aylık ileri değerleme")
        self.assertEqual(int(row["Hedef Yıl"]), 2026)
        self.assertEqual(int(row["Açıklanan Çeyrek"]), 0)
        self.assertEqual(int(row["Tahmin Edilen Çeyrek"]), 4)
        self.assertEqual(result.summary.index[0], pd.Timestamp("2026-12-01"))
        self.assertLessEqual(float(row["Temkinli Hedef"]), float(row["Ağırlıklı Hedef"]))
        self.assertGreaterEqual(float(row["İyimser Hedef"]), float(row["Ağırlıklı Hedef"]))

    def test_loss_making_company_excludes_fk_from_weight(self):
        statements, ratios = _frames("2025-09-01")
        statements["Ana Ortaklık Payları"] = -statements["Ana Ortaklık Payları"].abs()
        result = build_rule_based_valuation(statements, ratios)
        self.assertEqual(float(result.methods.loc["F/K", "Güven Ağırlığı %"]), 0.0)
        self.assertTrue(np.isnan(result.methods.loc["F/K", "Baz Hedef"]))

    def test_stale_extreme_multiples_do_not_dominate_current_regime(self):
        statements, ratios = _frames("2025-09-01")
        # Uzak geçmişteki aşırı çarpanlar, son dönem makul rejimini ve hedef
        # fiyatı yukarı sürüklememeli.
        ratios.loc[ratios.index[:-6], "F/K"] = 400.0
        ratios.loc[ratios.index[-6:], "F/K"] = [28.0, 24.0, 21.0, 18.0, 14.0, 11.0]

        result = build_rule_based_valuation(statements, ratios)

        self.assertLess(float(result.methods.loc["F/K", "Baz Çarpan"]), 20.0)
        self.assertLess(float(result.methods.loc["F/K", "Çarpan Üst"]), 25.0)
        self.assertEqual(int(result.methods.loc["F/K", "Örnek Sayısı"]), 6)


if __name__ == "__main__":
    unittest.main()
