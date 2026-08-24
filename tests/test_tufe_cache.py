import unittest

import numpy as np
import pandas as pd

from app.tufe_cache import (
    TUFE_CHANGE_COLUMN,
    TufeForecastError,
    calculate_annual_inflation_projection,
    complete_tufe_history,
    forecast_log_tufe_exog_path,
    has_complete_tufe_history,
    prepare_tufe_log_changes,
    quarterly_tufe_levels,
    reconstruct_tufe_levels,
    select_future_tufe,
)


class TufeCacheTests(unittest.TestCase):
    def test_missing_period_is_rejected(self):
        frame = pd.DataFrame(
            {"Log TUFE Tahmin": [8.1], "TUFE Tahmin": [3300.0]},
            index=pd.to_datetime(["2026-12-01"]),
        )
        with self.assertRaises(TufeForecastError):
            select_future_tufe(frame, last_financial_date=pd.Timestamp("2026-06-01"), steps=2)

    def test_longer_bridge_forecast_is_trimmed_to_financial_horizon(self):
        frame = pd.DataFrame(
            {
                "Log TUFE Tahmin": [7.9, 8.0, 8.1, 8.2],
                "TUFE Tahmin": [2900.0, 3100.0, 3300.0, 3600.0],
            },
            index=pd.date_range("2026-03-01", periods=4, freq="QS-MAR"),
        )

        selected = select_future_tufe(
            frame,
            last_financial_date=pd.Timestamp("2026-06-01"),
            steps=2,
        )

        self.assertEqual(
            list(selected.index),
            list(pd.to_datetime(["2026-09-01", "2026-12-01"])),
        )
        self.assertEqual(list(selected["TUFE Tahmin"]), [3300.0, 3600.0])

    def test_bridge_forecast_completes_missing_historical_exog(self):
        index = pd.date_range("2025-09-01", periods=4, freq="QS-MAR")
        history = pd.DataFrame(
            {
                "TUFE": [2800.0, 2900.0, float("nan"), float("nan")],
                "log_TUFE": [7.94, 7.97, float("nan"), float("nan")],
            },
            index=index,
        )
        bridge = pd.DataFrame(
            {
                "Log TUFE Tahmin": [8.01, 8.05, 8.10, 8.20],
                "TUFE Tahmin": [3000.0, 3150.0, 3300.0, 3600.0],
            },
            index=pd.date_range("2026-03-01", periods=4, freq="QS-MAR"),
        )

        completed = complete_tufe_history(history, bridge)

        self.assertTrue(has_complete_tufe_history(completed))
        self.assertEqual(list(completed["TUFE"]), [2800.0, 2900.0, 3000.0, 3150.0])

    def test_incomplete_historical_exog_can_be_detected_for_strict_rejection(self):
        history = pd.DataFrame(
            {"TUFE": [2800.0, float("nan")], "log_TUFE": [7.94, float("nan")]}
        )
        self.assertFalse(has_complete_tufe_history(history))

    def test_log_change_forecast_is_reconstructed_to_cpi_level(self):
        index = pd.date_range("2024-03-01", periods=8, freq="QS-MAR")
        history = pd.DataFrame({"TUFE": 100.0 * (1.05 ** pd.Series(range(8)).to_numpy())}, index=index)
        changes = prepare_tufe_log_changes(history)
        self.assertEqual(list(changes.columns), [TUFE_CHANGE_COLUMN])
        future_index = pd.date_range(index[-1], periods=3, freq="QS-MAR")[1:]
        prefix = TUFE_CHANGE_COLUMN
        change_result = {
            "future_forecast": pd.DataFrame(
                {
                    f"{prefix} Tahmin": [0.05, 0.04],
                    f"{prefix} Alt %80": [0.03, 0.02],
                    f"{prefix} Üst %80": [0.07, 0.06],
                    f"{prefix} Alt %95": [0.01, 0.00],
                    f"{prefix} Üst %95": [0.09, 0.08],
                },
                index=future_index,
            ),
            "cv_predictions": pd.DataFrame(),
        }

        projection, _ = reconstruct_tufe_levels(history, change_result)

        self.assertGreater(projection["TUFE Tahmin"].iloc[0], history["TUFE"].iloc[-1])
        self.assertGreater(projection["TUFE Tahmin"].iloc[1], projection["TUFE Tahmin"].iloc[0])
        self.assertIn("TUFE Üst %95", projection.columns)

    def test_monthly_evds_data_becomes_true_quarterly_log_changes(self):
        monthly_index = pd.date_range("2025-01-01", periods=12, freq="MS")
        history = pd.DataFrame(
            {"TUFE": [100.0 + 10.0 * period for period in range(12)]},
            index=monthly_index,
        )

        quarterly = quarterly_tufe_levels(history)
        changes = prepare_tufe_log_changes(history)

        self.assertEqual(list(quarterly.index.month), [3, 6, 9, 12])
        self.assertEqual(list(changes.index.month), [6, 9, 12])
        self.assertAlmostEqual(
            changes.loc["2025-06-01", TUFE_CHANGE_COLUMN],
            float(np.log(quarterly.loc["2025-06-01"] / quarterly.loc["2025-03-01"])),
        )

    def test_annual_inflation_projection_uses_previous_year_index(self):
        history_index = pd.date_range("2025-03-01", periods=4, freq="QS-MAR")
        history = pd.DataFrame({"TUFE": [100.0, 105.0, 110.0, 120.0]}, index=history_index)
        future_index = pd.date_range("2026-03-01", periods=4, freq="QS-MAR")
        projection = pd.DataFrame(
            {
                "TUFE Tahmin": [130.0, 140.0, 150.0, 160.0],
                "TUFE Alt %80": [128.0, 138.0, 148.0, 158.0],
                "TUFE Üst %80": [132.0, 142.0, 152.0, 162.0],
                "TUFE Alt %95": [126.0, 136.0, 146.0, 156.0],
                "TUFE Üst %95": [134.0, 144.0, 154.0, 164.0],
            },
            index=future_index,
        )

        annual = calculate_annual_inflation_projection(history, projection)

        self.assertAlmostEqual(annual.loc["2026-03-01", "Yıllık Enflasyon Tahmini"], 30.0)
        self.assertAlmostEqual(
            annual.loc["2026-12-01", "Yıllık Enflasyon Tahmini"],
            (160.0 / 120.0 - 1) * 100,
        )
        self.assertLess(
            annual.loc["2026-12-01", "Yıllık Enflasyon Alt %80"],
            annual.loc["2026-12-01", "Yıllık Enflasyon Tahmini"],
        )
        self.assertGreater(
            annual.loc["2026-12-01", "Yıllık Enflasyon Üst %80"],
            annual.loc["2026-12-01", "Yıllık Enflasyon Tahmini"],
        )

    def test_cv_tufe_path_uses_only_training_history(self):
        index = pd.date_range("2021-03-01", periods=16, freq="QS-MAR")
        history = pd.DataFrame(
            {"log_TUFE": 7.0 + np.arange(len(index)) * 0.05},
            index=index,
        )
        future_index = pd.date_range(index[-1], periods=3, freq="QS-MAR")[1:]
        calls = []

        def fake_forecast(**kwargs):
            calls.append(kwargs)
            self.assertLess(kwargs["df"].index[-1], kwargs["future_index"][0])
            point = f"{TUFE_CHANGE_COLUMN} Tahmin"
            return {
                "future_forecast": pd.DataFrame(
                    {point: [0.04, 0.03]},
                    index=kwargs["future_index"],
                )
            }

        result = forecast_log_tufe_exog_path(history, future_index, fake_forecast)

        self.assertEqual(len(calls), 1)
        self.assertEqual(list(result.index), list(future_index))
        self.assertAlmostEqual(result["log_TUFE"].iloc[0], history["log_TUFE"].iloc[-1] + 0.04)
        self.assertAlmostEqual(result["log_TUFE"].iloc[1], history["log_TUFE"].iloc[-1] + 0.07)


if __name__ == "__main__":
    unittest.main()
