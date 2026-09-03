import unittest
from pathlib import Path


class FrontendContractTests(unittest.TestCase):
    def test_vertical_analysis_uses_a_single_sticky_header_row(self):
        root = Path(__file__).resolve().parents[1]
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        company_analysis = (root / "app" / "analysis_company.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            ".data-table thead th {\n  position: sticky;\n  top: 0;",
            stylesheet,
        )
        self.assertIn("classes=\"data-table vertical-analysis-table\"", company_analysis)

        table_format = (root / "app" / "table_format.py").read_text(encoding="utf-8")
        self.assertIn("flattened.reset_index()", table_format)

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
        self.assertIn("Model Bazlı Değerleme Özeti", javascript)
        self.assertIn("Model Değerleme Aralığı", javascript)
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
        self.assertIn("F/K değeri =", javascript)
        self.assertIn("FD/NS değeri =", javascript)
        self.assertIn("Model değerleme ortalaması = Σ", javascript)
        self.assertIn("medyan mutlak hatası %35", javascript)
        self.assertIn("Piyasa Fiyatına Göre Model Farkı", javascript)
        self.assertNotIn('label: `Gerekli Dönem Getirisi', javascript)
        self.assertNotIn('label: "Gerekli Getiriye Göre Fark"', javascript)
        self.assertIn("sektör medyanı veya sektör çıpası kullanılmaz", javascript)
        self.assertNotIn('label: "Yıllıklandırılmış Hedef Fiyat Getirisi"', javascript)
        self.assertNotIn(
            "Hedef fiyat potansiyeli hedef vadesine göre yıllıklandırılır",
            javascript,
        )

        page = (root / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="company-required-return"', page)
        self.assertNotIn("Yıllık Gerekli Getiri (%)", page)
        self.assertNotIn("required_return_pct", javascript)

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

    def test_company_name_is_shown_as_an_optional_category_heading(self):
        root = Path(__file__).resolve().parents[1]
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        company_analysis = (root / "app" / "analysis_company.py").read_text(
            encoding="utf-8"
        )
        page = (root / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn("renderCompanyCategoryHeading", javascript)
        self.assertIn("meta?.sirket_adi", javascript)
        self.assertIn("if (!companyName) return", javascript)
        self.assertIn(".company-category-heading", stylesheet)
        self.assertIn('"sirket_adi": _lookup_company_name', company_analysis)
        self.assertIn("20260903-company-name", page)

    def test_vertical_balance_comparison_is_available_in_balance_category(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        company_analysis = (root / "app" / "analysis_company.py").read_text(encoding="utf-8")

        self.assertIn('"Dikey Gelir Tablosu Karşılaştırması"', javascript)
        self.assertIn("ilgili dönem tutarının o dönemin Toplam Varlıklar", javascript)
        self.assertIn('"name": "Dikey Bilanço Karşılaştırması"', company_analysis)
        self.assertIn('"name": "Dikey Gelir Tablosu Karşılaştırması"', company_analysis)
        self.assertIn("_build_vertical_balance_analysis(df_bilanco)", company_analysis)
        self.assertIn("_build_vertical_income_analysis(df_bilanco)", company_analysis)
        self.assertIn('data-cat="dikey">Dikey Analiz</button>', page)
        self.assertIn("20260903-company-name", page)
        self.assertIn('const isTableOnly = category === "dikey"', javascript)
        self.assertNotIn(".vertical-analysis-table td.change-positive", stylesheet)

    def test_valuation_dashboard_uses_sparse_readable_period_labels(self):
        import json

        root = Path(__file__).resolve().parents[1]
        notebook = json.loads((root / "Sirket Analiz.ipynb").read_text(encoding="utf-8"))
        notebook_source = "\n".join(
            "".join(cell.get("source", [])) for cell in notebook.get("cells", [])
        )

        self.assertIn("max_readable_ticks = 6", notebook_source)
        self.assertIn("readable_tick_indices = np.linspace", notebook_source)
        self.assertIn("num=max_readable_ticks, dtype=int", notebook_source)
        self.assertNotIn("readable_ticks.append(period_labels[-1])", notebook_source)
        self.assertIn('tickvals=readable_ticks', notebook_source)
        self.assertIn('ticktext=readable_ticks', notebook_source)
        self.assertIn('tickangle=0', notebook_source)
        self.assertIn('f"{period.year}/{period.month:02d}"', notebook_source)

        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('"tickmode", "tickvals", "ticktext"', javascript)

    def test_non_personalized_disclosure_and_report_metadata_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        company_analysis = (root / "app" / "analysis_company.py").read_text(encoding="utf-8")
        sector_analysis = (root / "app" / "analysis_sector.py").read_text(encoding="utf-8")

        self.assertIn('id="valuation-disclosure-dialog"', page)
        self.assertIn("kişiselleştirilmemiş bir finansal analiz aracıdır", page)
        self.assertIn("Yasal ve metodolojik bilgilendirme", page)
        self.assertIn("showSectorDisclosure", javascript)
        self.assertIn("valuationAcceptedReports", javascript)
        self.assertIn("renderReportMetadata", javascript)
        self.assertIn('"rapor_bilgisi"', company_analysis)
        self.assertIn('"rapor_bilgisi"', sector_analysis)
        self.assertIn("Model Değerleme Ortalaması", company_analysis)
        self.assertIn("Sektör Referanslı Model Değeri", sector_analysis)

    def test_heatmap_colour_logic_is_unchanged_by_compliance_ui(self):
        root = Path(__file__).resolve().parents[1]
        sector_analysis = (root / "app" / "analysis_sector.py").read_text(encoding="utf-8")
        plotly_theme = (root / "app" / "plotly_theme.py").read_text(encoding="utf-8")

        self.assertIn("COLORSCALE_HIGH_GOOD if col in _HIGH_IS_GOOD else COLORSCALE_LOW_GOOD", sector_analysis)
        self.assertIn("COLORSCALE_HIGH_GOOD", plotly_theme)
        self.assertIn("COLORSCALE_LOW_GOOD", plotly_theme)

    def test_requested_light_palette_is_used_across_web_and_plotly(self):
        root = Path(__file__).resolve().parents[1]
        stylesheet = (root / "static" / "app.css").read_text(encoding="utf-8")
        plotly_theme = (root / "app" / "plotly_theme.py").read_text(encoding="utf-8")

        for color in ("#0D6628", "#6EAD50", "#ECF1E5", "#FF0000"):
            self.assertIn(color, stylesheet)
            self.assertIn(color, plotly_theme)
        self.assertIn("--bg-dark:      #ECF1E5", stylesheet)
        self.assertIn('CARD_BG = "#FFFFFF"', plotly_theme)


if __name__ == "__main__":
    unittest.main()
