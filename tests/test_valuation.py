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
    ratios["FD/NS"] = np.linspace(1.1, 1.9, len(dates))
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
        self.assertEqual(result.summary.index[0], pd.Timestamp("2026-12-31"))
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

    def test_sales_method_uses_enterprise_value_to_sales_and_net_debt_bridge(self):
        statements, ratios = _frames("2025-09-01")
        result = build_rule_based_valuation(statements, ratios)

        self.assertIn("FD/NS", result.methods.index)
        self.assertNotIn("PD/NS", result.methods.index)
        base = result.projection.loc["Baz"]
        multiple = float(result.methods.loc["FD/NS", "Baz Çarpan"])
        shares = float(ratios.iloc[-1]["  Ödenmiş Sermaye"])
        expected = (float(base["Satış Gelirleri"]) * multiple - float(base["Net Borç"])) / shares
        self.assertAlmostEqual(float(result.methods.loc["FD/NS", "Baz Hedef"]), expected)

    def test_valuation_methods_use_only_company_history(self):
        statements, ratios = _frames("2025-09-01")
        result = build_rule_based_valuation(statements, ratios)

        self.assertNotIn("Sektör Medyanı", result.methods.columns)
        self.assertNotIn("Sektör Ağırlığı %", result.methods.columns)
        self.assertNotIn("Sektör Emsali", result.summary.columns)
        self.assertNotIn("Emsal Veri Tarihi", result.summary.columns)
        self.assertNotIn("Sektör çıpası", result.data_quality)

    def test_period_return_directly_drives_valuation_status(self):
        statements, ratios = _frames("2025-09-01")
        result = build_rule_based_valuation(
            statements,
            ratios,
            valuation_date=pd.Timestamp("2025-09-30"),
        )
        row = result.summary.iloc[0]
        self.assertIn("Hedef Dönem Getirisi %", row.index)
        self.assertNotIn("Yıllık Gerekli Getiri %", row.index)
        self.assertNotIn("Gerekli Dönem Getirisi %", row.index)
        self.assertNotIn("Gerekli Getiriye Göre Fark %", row.index)
        self.assertNotIn("Yıllıklandırılmış Hedef Fiyat Getirisi %", row.index)
        expected_target_return = (
            float(row["Ağırlıklı Hedef"]) / float(row["Güncel Fiyat"]) - 1.0
        ) * 100.0
        self.assertAlmostEqual(
            float(row["Hedef Dönem Getirisi %"]),
            expected_target_return,
        )
        target_period_return = expected_target_return / 100.0
        expected_status = (
            "iskontolu" if target_period_return >= 0.20 else
            "az değerli" if target_period_return >= 0.10 else
            "adil" if target_period_return >= -0.10 else
            "biraz yüksek" if target_period_return >= -0.20 else
            "pahalı"
        )
        self.assertEqual(row["Değerleme Görünümü"], expected_status)

    def test_confidence_exposes_historical_validation_metrics(self):
        statements, ratios = _frames("2025-12-01")
        result = build_rule_based_valuation(statements, ratios)
        row = result.summary.iloc[0]

        self.assertGreaterEqual(int(row["Backtest Örnek Sayısı"]), 1)
        self.assertTrue(np.isfinite(float(row["Backtest Medyan Mutlak Hata %"])))


if __name__ == "__main__":
    unittest.main()
