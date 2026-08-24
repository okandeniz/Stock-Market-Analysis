import unittest

import pandas as pd

from app.analysis_company import (
    _build_company_summary,
    _plot_rule_based_valuation,
    _valuation_kpi_summary,
)
from app.valuation import ValuationResult


class CompanyAnalysisHelperTests(unittest.TestCase):
    def test_weighted_target_label_is_fixed_to_plot_top_right(self):
        class DummyModule:
            figure = None

            def show(self, figure):
                self.figure = figure

        result = ValuationResult(
            summary=pd.DataFrame(
                {
                    "Değerleme Ufku": ["Cari yıl sonu değerlemesi"],
                    "Temkinli Hedef": [50.0],
                    "Ağırlıklı Hedef": [62.46],
                    "İyimser Hedef": [75.0],
                    "Veri Güveni": ["Yüksek"],
                    "Güven Puanı": [75],
                },
                index=[pd.Timestamp("2026-12-01")],
            ),
            methods=pd.DataFrame(
                {
                    "Baz Hedef": [54.48, 68.95],
                    "Güven Ağırlığı %": [40.0, 60.0],
                },
                index=["F/K", "FD/FAVÖK"],
            ),
            assumptions=pd.DataFrame(),
            projection=pd.DataFrame(),
            data_quality="—",
        )
        module = DummyModule()

        _plot_rule_based_valuation(module, result)

        target_note = next(
            annotation
            for annotation in module.figure.layout.annotations
            if "Ağırlıklı hedef fiyat" in annotation.text
        )
        self.assertEqual(target_note.xref, "paper")
        self.assertEqual(target_note.yref, "paper")
        self.assertEqual(target_note.xanchor, "right")
        self.assertEqual(target_note.yanchor, "top")

    def test_valuation_kpi_summary_exposes_decision_fields(self):
        valuation = pd.DataFrame(
            {
                "Değerleme Ufku": ["12 aylık ileri değerleme"],
                "Güncel Fiyat": [44.54],
                "Ağırlıklı Hedef": [51.31],
                "Temkinli Hedef": [46.94],
                "İyimser Hedef": [55.77],
                "Hedef Potansiyeli %": [15.19],
                "Veri Güveni": ["Orta"],
                "Güven Puanı": [68],
                "Değerleme Görünümü": ["az değerli"],
            },
            index=["2026-12"],
        )

        summary = _valuation_kpi_summary(valuation)

        self.assertEqual(summary["period"], "2026-12")
        self.assertEqual(summary["current_price"], 44.54)
        self.assertEqual(summary["average_target"], 51.31)
        self.assertEqual(summary["upside_pct"], 15.19)
        self.assertEqual(summary["scenario_low"], 46.94)
        self.assertEqual(summary["confidence"], "Orta")
        self.assertEqual(summary["status"], "az değerli")

    def test_valuation_kpi_summary_handles_missing_output(self):
        self.assertIsNone(_valuation_kpi_summary(None))
        self.assertIsNone(_valuation_kpi_summary(pd.DataFrame()))

    def test_valuation_kpi_summary_formats_timestamp_as_quarter_period(self):
        valuation = pd.DataFrame(
            {"fiyat": [44.54], "durum": ["adil"]},
            index=[pd.Timestamp("2026-12-01")],
        )

        self.assertEqual(_valuation_kpi_summary(valuation)["period"], "2026-12")

    def test_company_summary_compares_income_yoy_and_balance_prior_period(self):
        index = pd.to_datetime(
            ["2025-03-01", "2025-06-01", "2025-09-01", "2025-12-01", "2026-03-01", "2026-06-01"]
        )
        raw = pd.DataFrame(
            {
                "Satış Gelirleri": [100, 200, 300, 400, 900, 300],
                "BRÜT KAR (ZARAR)": [20, 40, 60, 80, 180, 60],
                "FAVÖK": [10, 20, 30, 40, 90, 30],
                "Ana Ortaklık Payları": [5, 10, 15, 20, 45, 15],
                "Dönen Varlıklar": [50, 60, 70, 80, 90, 75],
                "Duran Varlıklar": [100, 110, 120, 130, 140, 132],
                "TOPLAM VARLIKLAR": [150, 170, 190, 210, 230, 207],
                "Özkaynaklar": [80, 90, 100, 110, 120, 108],
            },
            index=index,
        )
        ratios = pd.DataFrame(
            {
                "duzeltilmis_fiyat": [10, 11, 12, 13, 14, 15],
                "PD": [1000, 1100, 1200, 1300, 1400, 1500],
                "F/K": [5, 5, 5, 5, 5, 5],
                "PD/DD": [1, 1, 1, 1, 1, 1],
                "FD/FAVÖK": [7, 7, 7, 7, 7, 7],
                "net_borc": [30, 40, 50, 60, 70, 50],
            },
            index=index,
        )
        quarterly = raw[["Satış Gelirleri", "FAVÖK", "Ana Ortaklık Payları"]].copy()

        summary = _build_company_summary("THYAO", raw, ratios, quarterly)

        self.assertEqual(summary["latest_period"], "2026/6")
        self.assertEqual(summary["comparison_period"], "2025/6")
        self.assertEqual(summary["balance_comparison_period"], "2026/3")
        sales = next(row for row in summary["income_rows"] if row["label"] == "Satışlar")
        self.assertEqual(sales["current"], 300)
        self.assertEqual(sales["previous"], 200)
        self.assertEqual(sales["change_pct"], 50)
        net_debt = next(row for row in summary["balance_rows"] if row["label"] == "Net Borç")
        self.assertEqual(net_debt["previous"], 70)
        self.assertTrue(net_debt["inverse"])
        self.assertAlmostEqual(net_debt["change_pct"], (50 - 70) / 70 * 100)
        assets = next(row for row in summary["balance_rows"] if row["label"] == "Toplam Varlıklar")
        self.assertEqual(assets["previous"], 230)
        self.assertAlmostEqual(assets["change_pct"], (207 / 230 - 1) * 100)
        self.assertEqual([point["period"] for point in summary["quarterly"]], [
            "2025/6", "2025/9", "2025/12", "2026/3", "2026/6"
        ])

    def test_company_summary_uses_march_for_march_comparison(self):
        index = pd.to_datetime(["2025-03-01", "2025-06-01", "2025-09-01", "2025-12-01", "2026-03-01"])
        raw = pd.DataFrame({"Satış Gelirleri": [100, 200, 300, 400, 130]}, index=index)
        ratios = pd.DataFrame({"fiyat": [10, 11, 12, 13, 14]}, index=index)

        summary = _build_company_summary("TEST", raw, ratios, raw)

        self.assertEqual(summary["latest_period"], "2026/3")
        self.assertEqual(summary["comparison_period"], "2025/3")
        self.assertEqual(summary["income_rows"][0]["previous"], 100)

    def test_company_summary_marks_negative_to_positive_change_as_nan(self):
        index = pd.to_datetime(["2025-03-01", "2026-03-01"])
        raw = pd.DataFrame(
            {
                "Satış Gelirleri": [100, 120],
                "Ana Ortaklık Payları": [-143_079_000, 254_230_000],
            },
            index=index,
        )
        ratios = pd.DataFrame({"fiyat": [10, 12], "net_borc": [20, 18]}, index=index)

        summary = _build_company_summary("TEST", raw, ratios, raw)
        net_income = next(
            row for row in summary["income_rows"] if row["label"] == "Net Dönem Kârı"
        )

        self.assertIsNone(net_income["change_pct"])

    def test_company_summary_net_debt_sign_uses_absolute_debt_magnitude(self):
        index = pd.to_datetime(["2025-03-01", "2026-03-01"])
        raw = pd.DataFrame({"Satış Gelirleri": [100, 120]}, index=index)
        ratios = pd.DataFrame(
            {"fiyat": [10, 12], "net_borc": [-13_208_797_000, -23_125_380_000]},
            index=index,
        )

        summary = _build_company_summary("TEST", raw, ratios, raw)
        net_debt = next(row for row in summary["balance_rows"] if row["label"] == "Net Borç")

        self.assertAlmostEqual(net_debt["change_pct"], -75.0756, places=3)

        ratios.loc[pd.Timestamp("2025-03-01"), "net_borc"] = 40_000_000_000
        ratios.loc[pd.Timestamp("2026-03-01"), "net_borc"] = 30_000_000_000
        reduced = _build_company_summary("TEST", raw, ratios, raw)
        reduced_net_debt = next(
            row for row in reduced["balance_rows"] if row["label"] == "Net Borç"
        )
        self.assertEqual(reduced_net_debt["change_pct"], -25)

    def test_company_summary_net_debt_crossing_from_cash_to_debt_is_not_nan(self):
        index = pd.to_datetime(["2025-03-01", "2026-03-01"])
        raw = pd.DataFrame({"Satış Gelirleri": [100, 120]}, index=index)
        ratios = pd.DataFrame(
            {"fiyat": [10, 12], "net_borc": [-10_000_000_000, 5_000_000_000]},
            index=index,
        )

        summary = _build_company_summary("TEST", raw, ratios, raw)
        net_debt = next(row for row in summary["balance_rows"] if row["label"] == "Net Borç")

        self.assertEqual(net_debt["change_pct"], 150)


if __name__ == "__main__":
    unittest.main()
