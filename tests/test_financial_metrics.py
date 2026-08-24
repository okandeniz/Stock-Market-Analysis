import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import app.financial_metrics as financial_metrics

from app.financial_metrics import (
    calculate_coverage_and_export_ratios,
    prepare_quarterly_financial_flows,
    prepare_split_consistent_prices,
    quarter_steps_to_year_end,
    reconcile_year_end_flow,
    relative_discount_pct,
    select_column_occurrence,
    split_adjusted_paid_capital,
)


class FinancialMetricTests(unittest.TestCase):
    def tearDown(self):
        financial_metrics.clear_yf_cache()

    def test_yfinance_download_is_cached_and_returns_independent_frames(self):
        source = pd.DataFrame(
            {"Close": [100.0], "Adj Close": [99.0]},
            index=[pd.Timestamp("2026-08-04")],
        )
        with patch.object(financial_metrics.yf, "download", return_value=source) as download:
            first = financial_metrics.yf_download_safe(
                "TEST.IS", period="1d", progress=False, retries=1
            )
            first.iloc[0, 0] = -1.0
            second = financial_metrics.yf_download_safe(
                "TEST.IS", period="1d", progress=False, retries=1
            )

        self.assertEqual(download.call_count, 1)
        self.assertEqual(second.iloc[0]["Close"], 100.0)

    def test_split_adjusts_pre_event_capital_to_same_basis_as_close(self):
        capital = pd.Series(
            [254.37, 254.37, 2_798.07, 2_798.07],
            index=pd.to_datetime(["2024-03-01", "2024-06-01", "2024-09-01", "2024-12-01"]),
        )
        splits = pd.Series([11.0], index=pd.to_datetime(["2024-08-13"]))

        adjusted, factors = split_adjusted_paid_capital(capital, splits)

        self.assertAlmostEqual(adjusted.loc["2024-06-01"], 2_798.07)
        self.assertEqual(factors.loc["2024-06-01"], 11.0)
        self.assertEqual(factors.loc["2024-09-01"], 1.0)

    def test_already_restated_capital_is_not_adjusted_twice(self):
        capital = pd.Series(
            [2_798.07, 2_798.07],
            index=pd.to_datetime(["2024-06-01", "2024-09-01"]),
        )
        splits = pd.Series([11.0], index=pd.to_datetime(["2024-08-13"]))

        adjusted, factors = split_adjusted_paid_capital(capital, splits)

        self.assertTrue(adjusted.equals(capital))
        self.assertTrue((factors == 1.0).all())

    def test_split_after_latest_statement_adjusts_latest_capital(self):
        capital = pd.Series([254.37], index=pd.to_datetime(["2024-06-01"]))
        splits = pd.Series([11.0], index=pd.to_datetime(["2024-08-13"]))

        adjusted, _ = split_adjusted_paid_capital(capital, splits)

        self.assertAlmostEqual(adjusted.iloc[-1], 2_798.07)

    def test_capital_transition_before_yahoo_event_is_not_adjusted_twice(self):
        capital = pd.Series(
            [21_750_121.0, 891_754_961.0, 891_754_961.0],
            index=pd.to_datetime(["2025-09-01", "2025-12-01", "2026-03-01"]),
        )
        splits = pd.Series([41.0], index=pd.to_datetime(["2026-03-16"]))

        adjusted, factors = split_adjusted_paid_capital(capital, splits)

        self.assertAlmostEqual(adjusted.loc["2025-09-01"], 891_754_961.0)
        self.assertEqual(adjusted.loc["2025-12-01"], 891_754_961.0)
        self.assertEqual(adjusted.loc["2026-03-01"], 891_754_961.0)
        self.assertEqual(factors.loc["2025-09-01"], 41.0)
        self.assertEqual(factors.loc["2025-12-01"], 1.0)

    def test_valuation_price_excludes_dividend_adjustment(self):
        raw = pd.DataFrame(
            {"Close": [69.35], "Adj Close": [66.80]},
            index=pd.to_datetime(["2024-08-13"]),
        )

        prices = prepare_split_consistent_prices(raw)

        self.assertEqual(prices.iloc[0]["duzeltilmis_fiyat"], 69.35)
        self.assertEqual(prices.iloc[0]["toplam_getiri_fiyati"], 66.80)

    def test_incomplete_intraday_row_is_not_used_as_current_close(self):
        raw = pd.DataFrame(
            {
                "Close": [6.05, np.nan],
                "Adj Close": [6.05, np.nan],
                "Stock Splits": [0.0, 0.0],
                "Volume": [1_000_000, 2_000_000],
            },
            index=pd.to_datetime(["2026-08-04", "2026-08-05"]),
        )

        prices = prepare_split_consistent_prices(raw)

        self.assertEqual(prices.index[-1], pd.Timestamp("2026-08-04"))
        self.assertEqual(float(prices.iloc[-1]["duzeltilmis_fiyat"]), 6.05)

    def test_raw_pre_split_price_is_brought_to_current_share_basis(self):
        raw = pd.DataFrame(
            {
                "Close": [761.50, 69.35],
                "Adj Close": [733.54, 66.80],
                "Stock Splits": [0.0, 11.0],
            },
            index=pd.to_datetime(["2024-08-12", "2024-08-13"]),
        )

        prices = prepare_split_consistent_prices(raw)

        self.assertAlmostEqual(prices.iloc[0]["duzeltilmis_fiyat"], 761.50 / 11.0)
        self.assertEqual(prices.iloc[0]["fiyat_duzeltme_katsayisi"], 11.0)
        self.assertEqual(prices.iloc[1]["fiyat_duzeltme_katsayisi"], 1.0)

    def test_yahoo_price_already_on_split_basis_is_not_adjusted_twice(self):
        raw = pd.DataFrame(
            {
                "Close": [69.14, 69.35],
                "Adj Close": [66.60, 66.80],
                "Stock Splits": [0.0, 11.0],
            },
            index=pd.to_datetime(["2024-08-12", "2024-08-13"]),
        )

        prices = prepare_split_consistent_prices(raw)

        self.assertEqual(prices.iloc[0]["duzeltilmis_fiyat"], 69.14)
        self.assertTrue((prices["fiyat_duzeltme_katsayisi"] == 1.0).all())

    def test_price_jump_before_announced_split_date_is_detected(self):
        raw = pd.DataFrame(
            {
                "Close": [846.0, 78.272728, 69.35],
                "Adj Close": [814.94, 75.40, 66.80],
                "Stock Splits": [0.0, 0.0, 11.0],
            },
            index=pd.to_datetime(["2024-07-31", "2024-08-01", "2024-08-13"]),
        )

        prices = prepare_split_consistent_prices(raw)

        self.assertAlmostEqual(prices.loc["2024-07-31", "duzeltilmis_fiyat"], 846.0 / 11.0)
        self.assertEqual(prices.loc["2024-07-31", "fiyat_duzeltme_katsayisi"], 11.0)
        self.assertEqual(prices.loc["2024-08-01", "fiyat_duzeltme_katsayisi"], 1.0)

    def test_interest_coverage_and_export_share_are_calculated(self):
        frame = pd.DataFrame(
            {
                "FAVÖK": [400.0],
                "Finansman Giderleri": [-100.0],
                "Yurtiçi Satışlar": [700.0],
                "Yurtdışı Satışlar": [300.0],
            }
        )

        result = calculate_coverage_and_export_ratios(frame)

        self.assertAlmostEqual(result.loc[0, "faiz_karsilama"], 4.0)
        self.assertAlmostEqual(result.loc[0, "ihracat_oranı_%"], 30.0)

    def test_new_ratios_keep_zero_denominators_missing(self):
        frame = pd.DataFrame(
            {
                "FAVÖK": [100.0],
                "Finansman Giderleri": [0.0],
                "Yurtiçi Satışlar": [0.0],
                "Yurtdışı Satışlar": [0.0],
            }
        )

        result = calculate_coverage_and_export_ratios(frame)

        self.assertTrue(pd.isna(result.loc[0, "faiz_karsilama"]))
        self.assertTrue(pd.isna(result.loc[0, "ihracat_oranı_%"]))

    def test_discount_is_positive_when_fair_value_exceeds_market(self):
        self.assertAlmostEqual(relative_discount_pct(120.0, 100.0), 20.0)

    def test_discount_handles_series_and_zero_market_value(self):
        result = relative_discount_pct(pd.Series([120.0, 80.0]), pd.Series([100.0, 0.0]))
        self.assertAlmostEqual(result.iloc[0], 20.0)
        self.assertTrue(pd.isna(result.iloc[1]))

    def test_duplicate_column_is_selected_by_occurrence(self):
        frame = pd.DataFrame([[10, 20]], columns=["Borç", "Borç"])
        self.assertEqual(select_column_occurrence(frame, "Borç", 1).iloc[0], 20)

    def test_missing_optional_duplicate_defaults_to_zero(self):
        frame = pd.DataFrame({"Borç": [10]}, index=[pd.Timestamp("2026-03-01")])
        result = select_column_occurrence(frame, "Borç", 1, default=0.0)
        self.assertEqual(result.iloc[0], 0.0)

    def test_forecast_horizon_includes_year_difference(self):
        as_of = pd.Timestamp("2026-08-04")
        self.assertEqual(quarter_steps_to_year_end("2026-03-01", as_of=as_of), 3)
        self.assertEqual(quarter_steps_to_year_end("2026-06-01", as_of=as_of), 2)
        self.assertEqual(quarter_steps_to_year_end("2026-09-01", as_of=as_of), 1)
        self.assertEqual(quarter_steps_to_year_end("2025-12-01", as_of=as_of), 4)
        self.assertEqual(quarter_steps_to_year_end("2026-12-01", as_of=as_of), 4)

    def test_forecast_horizon_rejects_non_financial_month(self):
        with self.assertRaises(ValueError):
            quarter_steps_to_year_end("2026-05-01", as_of="2026-08-04")

    def test_year_end_flow_adds_reported_and_missing_quarters(self):
        actual = pd.Series(
            [90.0, 110.0], index=pd.to_datetime(["2026-03-01", "2026-06-01"])
        )
        forecast = pd.DataFrame(
            {
                "Satış Tahmin": [120.0, 130.0],
                "Satış Alt %80": [100.0, 105.0],
                "Satış Üst %80": [140.0, 155.0],
                "Satış Alt %95": [90.0, 95.0],
                "Satış Üst %95": [150.0, 165.0],
            },
            index=pd.to_datetime(["2026-09-01", "2026-12-01"]),
        )

        result = reconcile_year_end_flow(actual, forecast, "Satış")

        self.assertEqual(result["reported_quarters"], 2)
        self.assertEqual(result["forecast_quarters"], 2)
        self.assertEqual(result["reported_total"], 200.0)
        self.assertEqual(result["future_total"], 250.0)
        self.assertEqual(result["point"], 450.0)
        self.assertEqual(result["lower_80"], 405.0)
        self.assertEqual(result["upper_80"], 495.0)
        self.assertEqual(result["interval_method"], "summed_quarter_bounds_fallback")

    def test_cumulative_income_statement_becomes_true_quarter_flows(self):
        index = pd.date_range("2024-03-01", periods=6, freq="QS-MAR")
        cumulative = pd.DataFrame(
            {
                "Satış": [100.0, 220.0, 360.0, 500.0, 150.0, 320.0],
                "Net Kâr": [10.0, 25.0, 45.0, 70.0, 12.0, 30.0],
            },
            index=index,
        )

        quarterly = prepare_quarterly_financial_flows(cumulative, ["Satış", "Net Kâr"])

        self.assertEqual(list(quarterly["Satış"]), [100.0, 120.0, 140.0, 140.0, 150.0, 170.0])
        self.assertEqual(list(quarterly["Net Kâr"]), [10.0, 15.0, 20.0, 25.0, 12.0, 18.0])
        self.assertIn("kontrolleri geçti", quarterly.attrs["data_quality_status"])

    def test_missing_interim_quarter_is_rejected(self):
        frame = pd.DataFrame(
            {"Satış": [100.0, 360.0, 500.0]},
            index=pd.to_datetime(["2024-03-01", "2024-09-01", "2024-12-01"]),
        )

        with self.assertRaisesRegex(ValueError, "ardışık değil"):
            prepare_quarterly_financial_flows(frame, ["Satış"])

    def test_missing_financial_value_is_rejected_instead_of_becoming_zero(self):
        frame = pd.DataFrame(
            {"Satış": [100.0, float("nan"), 360.0, 500.0]},
            index=pd.date_range("2024-03-01", periods=4, freq="QS-MAR"),
        )

        with self.assertRaisesRegex(ValueError, "eksik/sayısal olmayan"):
            prepare_quarterly_financial_flows(frame, ["Satış"])

    def test_year_end_interval_uses_joint_cv_error_paths(self):
        actual = pd.Series(
            [90.0, 110.0], index=pd.to_datetime(["2026-03-01", "2026-06-01"])
        )
        future_index = pd.to_datetime(["2026-09-01", "2026-12-01"])
        forecast = pd.DataFrame(
            {
                "Satış Tahmin": [120.0, 130.0],
                "Satış Alt %80": [100.0, 105.0],
                "Satış Üst %80": [140.0, 155.0],
                "Satış Alt %95": [90.0, 95.0],
                "Satış Üst %95": [150.0, 165.0],
            },
            index=future_index,
        )
        cv = pd.DataFrame(
            {
                "actual": [110.0, 120.0, 90.0, 100.0, 105.0, 115.0],
                "prediction": [100.0, 110.0, 100.0, 110.0, 100.0, 110.0],
                "fold": [1, 1, 2, 2, 3, 3],
            },
            index=list(future_index) * 3,
        )

        result = reconcile_year_end_flow(
            actual,
            forecast,
            "Satış",
            cv_predictions=cv,
        )

        self.assertEqual(result["interval_method"], "joint_cv_path_conformal")
        self.assertEqual(result["lower_80"], 430.0)
        self.assertEqual(result["upper_80"], 470.0)


if __name__ == "__main__":
    unittest.main()
