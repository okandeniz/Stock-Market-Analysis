import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

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


if __name__ == "__main__":
    unittest.main()
