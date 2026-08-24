import unittest
from pathlib import Path


class FrontendContractTests(unittest.TestCase):
    def test_financial_change_sections_and_period_toggle_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        company_analysis = (root / "app" / "analysis_company.py").read_text(encoding="utf-8")

        self.assertIn("chart-analysis-section-title", javascript)
        self.assertIn("analysis_section_title", javascript)
        self.assertIn(".chart-analysis-section", stylesheet)
        self.assertIn('"chart_toggle_label": "Yıllıklandırılmış"', company_analysis)
        self.assertIn('"chart_toggle_label": "Dönemsel"', company_analysis)
        self.assertIn('"chart_toggle_label": "Açıklanan Kümülatif"', company_analysis)
        self.assertIn('"chart_toggle_order": 3', company_analysis)
        self.assertIn("raw_cumulative_income_changes", company_analysis)
        self.assertIn('"analysis_section_title": "Bilanço Kalemleri"', company_analysis)

    def test_rule_based_guidance_and_larger_brand_title_are_present(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "templates" / "index.html").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("Senaryo tabanlı değerleme", page)
        self.assertNotIn("company-evds", page)
        self.assertNotIn("company-tufe", page)
        self.assertIn("font-size: 24px", stylesheet)
        self.assertIn(".hero-eyebrow", stylesheet)
        self.assertIn("font-size: 18px", stylesheet)
        self.assertIn("Kârlılık ve Satış Yapısı", javascript)
        self.assertIn("Likidite ve Borç Ödeme Gücü", javascript)

    def test_year_end_valuation_kpis_are_rendered_in_chart_mode(self):
        root = Path(__file__).resolve().parents[1]
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        company_analysis = (root / "app" / "analysis_company.py").read_text(encoding="utf-8")

        self.assertIn("renderValuationKpis", javascript)
        self.assertIn('category === "değerleme"', javascript)
        self.assertIn("İleri Değerleme Özeti", javascript)
        self.assertIn("Senaryo Aralığı", javascript)
        self.assertIn(".valuation-kpi-grid", stylesheet)
        self.assertIn('"yil_sonu_degerleme_kpi"', company_analysis)

    def test_insufficient_valuation_data_is_shown_without_failing_analysis(self):
        root = Path(__file__).resolve().parents[1]
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        company_analysis = (root / "app" / "analysis_company.py").read_text(encoding="utf-8")

        self.assertIn("renderValuationWarning", javascript)
        self.assertIn("degerleme_uyarisi", javascript)
        self.assertIn(".valuation-data-warning", stylesheet)
        self.assertIn("except InsufficientValuationDataError", company_analysis)
        self.assertIn('"degerleme_uyarisi": valuation_warning', company_analysis)

    def test_valuation_math_note_explains_formulas_and_weighting(self):
        root = Path(__file__).resolve().parents[1]
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("İleri değerleme matematiksel olarak nasıl hesaplanıyor?", javascript)
        self.assertIn("F/K hedefi =", javascript)
        self.assertIn("Ağırlıklı hedef fiyat = Σ", javascript)
        self.assertIn("gözlem sayısı %20", javascript)

    def test_company_summary_dashboard_uses_yoy_income_and_prior_balance(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        company_analysis = (root / "app" / "analysis_company.py").read_text(encoding="utf-8")

        self.assertIn('data-cat="özet"', page)
        self.assertIn("renderCompanySummary", javascript)
        self.assertIn("Özet Gelir Tablosu", javascript)
        self.assertIn("Özet Bilanço", javascript)
        self.assertIn("balance_comparison_period", javascript)
        self.assertIn("Çeyreklik Net Kâr", javascript)
        self.assertIn(".company-summary-dashboard", stylesheet)
        self.assertIn("latest_period.year - 1", company_analysis)
        self.assertIn("balance_comparison_period", company_analysis)
        self.assertIn('"sirket_ozeti"', company_analysis)
        self.assertLess(
            javascript.index("container.appendChild(dashboard)"),
            javascript.index('renderSummaryPlot(dashboard, summary.price_history'),
        )
        self.assertLess(
            javascript.index("dashboard.appendChild(charts)"),
            javascript.index('renderSummaryPlot(charts, summary.quarterly, "sales"'),
        )
        self.assertIn('return "NaN"', javascript)
        self.assertIn("row.inverse ? numericChange <= 0 : numericChange >= 0", javascript)


if __name__ == "__main__":
    unittest.main()
