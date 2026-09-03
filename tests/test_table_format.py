import unittest

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from app.table_format import dataframe_to_html, format_dataframe_for_display, write_formatted_excel


class TableFormatTests(unittest.TestCase):
    def test_count_and_year_columns_are_integers(self):
        frame = pd.DataFrame(
            {"Hedef Yıl": [2026], "Açıklanan Çeyrek": [2], "Güven Puanı": [61]}
        )
        formatted = format_dataframe_for_display(frame)
        self.assertEqual(formatted.iloc[0].tolist(), ["2026", "2", "61"])

    def test_turkish_number_and_date_formatting(self):
        frame = pd.DataFrame(
            {
                "Tutar": [1_234_567.89],
                "cari_oran": [1.2345],
                "Piotroski F-Skoru": [5.0],
                "Eksik": [np.nan],
            },
            index=pd.DatetimeIndex(["2026-03-01"]),
        )
        html = dataframe_to_html(frame)
        self.assertIn("1.234.568", html)
        self.assertIn("1,23", html)
        self.assertIn(">5<", html)
        self.assertIn("2026-03", html)
        self.assertIn("—", html)

    def test_text_cells_are_html_escaped(self):
        html = dataframe_to_html(pd.DataFrame({"Metin": ["<script>alert(1)</script>"]}))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_named_index_is_rendered_in_the_single_header_row(self):
        frame = pd.DataFrame(
            {"F/K": [5.83], "PD/DD": [0.65]},
            index=pd.Index(["ULKER"], name="Kod"),
        )

        html = dataframe_to_html(frame)
        table_head = html.split("<thead>", 1)[1].split("</thead>", 1)[0]
        self.assertEqual(table_head.count("<tr"), 1)
        self.assertIn("Kod", table_head)
        self.assertIn("F/K", table_head)
        self.assertIn("ULKER", html)

    def test_excel_uses_native_number_formats(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            path = Path(temp) / "formatted.xlsx"
            frame = pd.DataFrame(
                {"Tutar": [1_234_567.89], "cari_oran": [1.2345]},
                index=["AAA"],
            )
            write_formatted_excel(frame, path)
            workbook = load_workbook(path)
            worksheet = workbook["Analiz"]
            self.assertEqual(worksheet.freeze_panes, "B2")
            self.assertEqual(worksheet["B2"].number_format, "#,##0")
            self.assertEqual(worksheet["C2"].number_format, "#,##0.00")
            self.assertIsNotNone(worksheet.auto_filter.ref)


if __name__ == "__main__":
    unittest.main()
