import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from app.analysis_sector import _build_sector_financial_history
from app.notebook_runtime import NotebookRuntime


def _company_row(symbol, *, operating_profit, net_income, ebitda):
    return pd.DataFrame(
        {
            "  Ana Ortaklığa Ait Özkaynaklar": [100.0],
            "  Ödenmiş Sermaye": [10.0],
            "net_borc": [0.0],
            "duzeltilmis_fiyat": [10.0],
            "PD": [100.0],
            "FD": [100.0],
            "Satış Gelirleri": [100.0],
            "Net Faaliyet Kar/Zararı": [operating_profit],
            "FAVÖK": [ebitda],
            "Ana Ortaklık Payları": [net_income],
            "F/K": [100.0 / net_income],
            "FD/FAVÖK": [100.0 / ebitda],
            "FD/NS": [1.0],
            "PD/DD": [1.0],
            "NFK/PD_%": [operating_profit],
            "brüt_kar_marjı_%": [40.0],
            "net_kar_marjı_%": [net_income],
            "aktif_devir_hizi": [1.0],
            "ozkaynak_carpani": [2.0],
            "roe_dupont_%": [20.0],
            "faiz_karsilama": [ebitda / 5.0],
            "ihracat_oranı_%": [40.0],
            "Piotroski F-Skoru": [np.nan],
        },
        index=[symbol],
    )


class SectorNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.tempdir = tempfile.TemporaryDirectory(dir=cls.root)
        runtime = NotebookRuntime(
            cls.root / "Sektor Analizi.ipynb",
            project_root=cls.root,
            outputs_dir=Path(cls.tempdir.name),
        )
        cls.module = runtime.module()

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    def test_sector_percentage_scale_and_discount_direction(self):
        rows = {
            "AAA": _company_row("AAA", operating_profit=20.0, net_income=10.0, ebitda=25.0),
            "BBB": _company_row("BBB", operating_profit=5.0, net_income=5.0, ebitda=20.0),
        }
        original = self.module._tek_hisse_analizi
        self.module._tek_hisse_analizi = lambda symbol, _piotroski=True: rows[symbol].copy()
        try:
            overview = pd.DataFrame({"Kod": ["AAA", "BBB"], "Sektör": ["Test", "Test"]})
            result = self.module.sektor_analizi(
                ["AAA", "BBB"], "TOPLAM", overview, max_workers=1, piotroski_hesapla=False
            )
        finally:
            self.module._tek_hisse_analizi = original

        self.assertAlmostEqual(result.loc["SEKTÖR TOPLAM", "NFK/PD_%"], 12.5)
        self.assertAlmostEqual(result.loc["SEKTÖR TOPLAM", "faiz_karsilama"], 4.5)
        self.assertAlmostEqual(result.loc["SEKTÖR TOPLAM", "ihracat_oranı_%"], 40.0)
        self.assertGreater(result.loc["AAA", "iskonto_%"], 0)
        self.assertEqual(result.attrs["successful_count"], 2)
        self.assertEqual(result.attrs["failed_symbols"], {})

    def test_partial_failures_are_reported(self):
        original = self.module._tek_hisse_analizi

        def analyze(symbol, _piotroski=True):
            if symbol == "BBB":
                raise RuntimeError("kaynak hatası")
            return _company_row("AAA", operating_profit=20.0, net_income=10.0, ebitda=25.0)

        self.module._tek_hisse_analizi = analyze
        try:
            overview = pd.DataFrame({"Kod": ["AAA", "BBB"], "Sektör": ["Test", "Test"]})
            result = self.module.sektor_analizi(
                ["AAA", "BBB"], "TOPLAM", overview, max_workers=1, piotroski_hesapla=False
            )
        finally:
            self.module._tek_hisse_analizi = original

        self.assertEqual(result.attrs["successful_count"], 1)
        self.assertIn("BBB", result.attrs["failed_symbols"])

    def test_sector_history_uses_fixed_latest_reporting_cohort(self):
        dates = pd.date_range("2025-03-01", "2026-06-01", freq="QS-MAR")

        def history(scale):
            sales = pd.Series(np.arange(100.0, 100.0 + len(dates) * 10.0, 10.0), index=dates) * scale
            return pd.DataFrame(
                {
                    "Satış Gelirleri": sales,
                    "BRÜT KAR (ZARAR)": sales * 0.40,
                    "Net Faaliyet Kar/Zararı": sales * 0.20,
                    "FAVÖK": sales * 0.25,
                    "Ana Ortaklık Payları": sales * 0.12,
                },
                index=dates,
            )

        histories = {
            "AAA": history(1.0),
            "BBB": history(2.0),
            "CCC": history(3.0),
            # DDD son dönemi açıklamadı ve çok büyük; eski dönemde toplamda
            # bırakılırsa 2026/6'da sahte bir sektör düşüşü oluşturur.
            "DDD": history(100.0).iloc[:-1],
        }
        histories["CCC"].loc["2026-06-01", "FAVÖK"] = np.nan
        latest = {
            "AAA": pd.Timestamp("2026-06-01"),
            "BBB": pd.Timestamp("2026-06-01"),
            "CCC": pd.Timestamp("2026-06-01"),
            "DDD": pd.Timestamp("2026-03-01"),
        }

        bundle = _build_sector_financial_history(
            histories,
            latest,
            requested_symbols=list(histories),
        )

        self.assertIsNotNone(bundle)
        coverage = bundle["coverage"]
        self.assertEqual(coverage["reference_period"], "2026/6")
        self.assertEqual(coverage["reference_count"], 3)
        self.assertEqual(coverage["observed_latest_missing"], {"DDD": "2026/3"})
        expected_previous = sum(histories[s].loc["2026-03-01", "Satış Gelirleri"] for s in ("AAA", "BBB", "CCC"))
        expected_latest = sum(histories[s].loc["2026-06-01", "Satış Gelirleri"] for s in ("AAA", "BBB", "CCC"))
        self.assertAlmostEqual(
            bundle["totals"].loc["2026-03-01", "Satış Gelirleri"],
            expected_previous,
        )
        self.assertAlmostEqual(
            bundle["differences"].loc["2026-06-01", "Satış Gelirleri"],
            expected_latest - expected_previous,
        )
        self.assertAlmostEqual(
            bundle["margins"].loc["2026-06-01", "FAVÖK Marjı %"],
            25.0,
        )
        self.assertEqual(coverage["margin_coverage"]["FAVÖK Marjı %"], 2)

    def test_sector_history_keeps_older_periods_with_pairwise_comparable_companies(self):
        dates = pd.date_range("2024-03-01", "2026-06-01", freq="QS-MAR")
        aaa_sales = pd.Series(np.arange(100.0, 100.0 + len(dates) * 10.0, 10.0), index=dates)
        bbb_sales = pd.Series([1_000.0, 1_100.0], index=dates[-2:])

        def frame(sales):
            return pd.DataFrame(
                {
                    "Satış Gelirleri": sales,
                    "BRÜT KAR (ZARAR)": sales * 0.40,
                    "Net Faaliyet Kar/Zararı": sales * 0.20,
                    "FAVÖK": sales * 0.25,
                    "Ana Ortaklık Payları": sales * 0.12,
                }
            )

        bundle = _build_sector_financial_history(
            {"AAA": frame(aaa_sales), "BBB": frame(bbb_sales)},
            {"AAA": dates[-1], "BBB": dates[-1]},
            requested_symbols=["AAA", "BBB"],
        )

        self.assertIsNotNone(bundle)
        self.assertEqual(len(bundle["totals"]["Satış Gelirleri"].dropna()), len(dates))
        self.assertEqual(len(bundle["differences"]["Satış Gelirleri"].dropna()), len(dates) - 1)

        # BBB'nin ilk göründüğü dönemdeki yüksek tutarı sektör artışı gibi
        # yazma; değişimi yalnız iki dönemde de bulunan AAA üzerinden hesapla.
        bbb_first_period = dates[-2]
        expected_aaa_change = aaa_sales.loc[bbb_first_period] - aaa_sales.loc[dates[-3]]
        self.assertAlmostEqual(
            bundle["differences"].loc[bbb_first_period, "Satış Gelirleri"],
            expected_aaa_change,
        )
        self.assertEqual(
            bundle["coverage"]["metric_change_coverage"]["Satış Gelirleri"][
                "2026/3"
            ],
            1,
        )
        self.assertEqual(
            bundle["coverage"]["metric_change_coverage"]["Satış Gelirleri"][
                "2026/6"
            ],
            2,
        )


if __name__ == "__main__":
    unittest.main()
