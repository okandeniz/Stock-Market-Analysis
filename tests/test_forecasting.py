import unittest

import numpy as np
import pandas as pd

from app.forecasting import (
    forecast_model_secici,
)


class ForecastingTests(unittest.TestCase):
    def test_expanding_window_forecast_returns_expected_horizon(self):
        index = pd.date_range("2021-03-01", periods=22, freq="QS-MAR")
        figures = []
        frame = pd.DataFrame(
            {"Satış": 100 + np.arange(len(index)) * 5 + np.sin(np.arange(len(index)))},
            index=index,
        )
        result = forecast_model_secici(
            frame,
            "Satış",
            log=True,
            plot=True,
            trend_options=("t",),
            show_func=figures.append,
        )
        self.assertEqual(result["validation"], "horizon_matched_expanding_window_cv")
        self.assertGreaterEqual(result["cv_folds"], 2)
        self.assertEqual(len(result["future_forecast"]), 2)
        self.assertFalse(result["mae_results"].empty)
        self.assertIn("mase", result["mae_results"].columns)
        self.assertIn("Satış Alt %80", result["future_forecast"].columns)
        self.assertIn("Satış Üst %95", result["future_forecast"].columns)
        self.assertIn(result["model_confidence"], {"Düşük", "Orta", "Yüksek"})
        self.assertGreaterEqual(result["confidence_score"], 0)
        self.assertLessEqual(result["confidence_score"], 100)
        self.assertTrue(result["confidence_components"])
        self.assertTrue(result["confidence_reasons"])
        self.assertNotIn("naive_models_tested", result)
        self.assertNotIn("ensemble_components", result)
        self.assertNotIn("hybrid_applied", result)
        self.assertEqual(result["selection_metric"], "mase")
        self.assertTrue(
            set(result["mae_results"]["model"]).issubset(
                {"ETS", "ARIMA", "SARIMA", "SARIMAX_EXOG"}
            )
        )
        self.assertGreater(result["mae_results"].groupby("model").size().max(), 1)
        selected = result["family_best_results"].sort_values(
            ["mase", "mae", "mae_std", "model"]
        ).iloc[0]
        self.assertEqual(result["best_model_name"], selected["model"])
        self.assertEqual(result["best_params"], selected["params"])
        self.assertEqual(len(figures), 1)
        self.assertIn("GELECEK TAHMİNİ", [trace.name for trace in figures[0].data])
        self.assertIn("%95 TAHMİN ARALIĞI", [trace.name for trace in figures[0].data])
        self.assertIn("/100", figures[0].layout.title.text)

    def test_required_sarimax_uses_company_specific_future_index(self):
        index = pd.date_range("2021-03-01", periods=22, freq="QS-MAR")
        future_index = pd.date_range(index[-1], periods=3, freq="QS-MAR")[1:]
        tufe = 2000 + np.arange(len(index)) * 45.0
        frame = pd.DataFrame(
            {
                "Satış": 100 + np.arange(len(index)) * 5 + np.sin(np.arange(len(index))),
                "TUFE": tufe,
            },
            index=index,
        )
        future_exog = pd.DataFrame(
            {"TUFE": [tufe[-1] + 45.0, tufe[-1] + 90.0]},
            index=future_index,
        )

        result = forecast_model_secici(
            frame,
            "Satış",
            exog_df=frame,
            exog_cols=["TUFE"],
            future_exog=future_exog,
            future_index=future_index,
            require_sarimax_exog=True,
            log=False,
            plot=False,
            trend_options=("t",),
        )

        self.assertGreater(result["sarimax_exog_attempted"], 0)
        self.assertGreater(result["sarimax_exog_successful"], 0)
        self.assertIn("SARIMAX_EXOG", result["optimized_model_families"])
        self.assertIn(result["best_model_name"], {"ETS", "ARIMA", "SARIMA", "SARIMAX_EXOG"})
        self.assertEqual(result["forecast_steps"], 2)
        self.assertEqual(list(result["future_forecast"].index), list(future_index))
        self.assertTrue((result["cv_predictions"].groupby("fold").size() == 2).all())
        self.assertEqual(result["cv_exog_method"], "default_ex_ante_forecast")

    def test_cv_exog_is_forecast_from_each_training_origin(self):
        index = pd.date_range("2021-03-01", periods=22, freq="QS-MAR")
        future_index = pd.date_range(index[-1], periods=3, freq="QS-MAR")[1:]
        frame = pd.DataFrame(
            {
                "Satış": 100.0 + np.arange(len(index)) * 7.0,
                "TUFE": 7.0 + np.arange(len(index)) * 0.04,
            },
            index=index,
        )
        future_exog = pd.DataFrame(
            {"TUFE": [frame["TUFE"].iloc[-1] + 0.04, frame["TUFE"].iloc[-1] + 0.08]},
            index=future_index,
        )
        calls = []

        def exog_forecaster(history, validation_index):
            self.assertLess(history.index[-1], validation_index[0])
            calls.append((history.index[-1], tuple(validation_index)))
            step = float(history["TUFE"].diff().dropna().median())
            return pd.DataFrame(
                {"TUFE": float(history["TUFE"].iloc[-1]) + step * np.arange(1, len(validation_index) + 1)},
                index=validation_index,
            )

        result = forecast_model_secici(
            frame,
            "Satış",
            exog_df=frame,
            exog_cols=["TUFE"],
            future_exog=future_exog,
            future_index=future_index,
            require_sarimax_exog=True,
            exog_cv_forecaster=exog_forecaster,
            log=False,
            plot=False,
            trend_options=("t",),
        )

        self.assertEqual(len(calls), result["cv_folds"])
        self.assertEqual(result["cv_exog_method"], "dedicated_ex_ante_forecast")

    def test_missing_target_quarter_is_rejected(self):
        index = pd.date_range("2021-03-01", periods=18, freq="QS-MAR").delete(9)
        frame = pd.DataFrame({"Satış": 100.0 + np.arange(len(index))}, index=index)

        with self.assertRaisesRegex(ValueError, "eksik veya ardışık olmayan"):
            forecast_model_secici(frame, "Satış", log=False, plot=False)

    def test_required_sarimax_rejects_missing_exog(self):
        index = pd.date_range("2021-03-01", periods=22, freq="QS-MAR")
        frame = pd.DataFrame({"Satış": np.arange(len(index)) + 100.0}, index=index)
        future_index = pd.date_range(index[-1], periods=3, freq="QS-MAR")[1:]

        with self.assertRaisesRegex(ValueError, "SARIMAX_EXOG zorunlu"):
            forecast_model_secici(
                frame,
                "Satış",
                future_index=future_index,
                require_sarimax_exog=True,
                log=False,
                plot=False,
            )

    def test_company_specific_future_index_must_be_consecutive(self):
        index = pd.date_range("2021-03-01", periods=22, freq="QS-MAR")
        frame = pd.DataFrame({"Satış": np.arange(len(index)) + 100.0}, index=index)
        invalid_future_index = pd.to_datetime(["2026-12-01"])

        with self.assertRaisesRegex(ValueError, "şirket-özel tahmin tarihleri"):
            forecast_model_secici(
                frame,
                "Satış",
                future_index=invalid_future_index,
                log=False,
                plot=False,
            )

    def test_large_recent_level_shift_is_reported_as_regime_signal(self):
        index = pd.date_range("2021-03-01", periods=24, freq="QS-MAR")
        values = np.r_[np.linspace(10, 12, 16), np.linspace(-8, -7, 4), np.linspace(3, 5, 4)]
        frame = pd.DataFrame({"Marj": values}, index=index)
        future_index = pd.date_range(index[-1], periods=3, freq="QS-MAR")[1:]

        result = forecast_model_secici(
            frame,
            "Marj",
            future_index=future_index,
            log=False,
            plot=False,
            trend_options=("t",),
        )

        self.assertTrue(result["regime_change_detected"])
        self.assertIsNotNone(result["regime_change_date"])

    def test_signed_asinh_transform_handles_extreme_profit_swings(self):
        index = pd.date_range("2021-03-01", periods=20, freq="QS-MAR")
        values = np.array(
            [5, 8, -4, 12, 6, 10, -30, 15, 8, 11, -6, 18, 9, 14, -45, 22, 11, 16, -8, 25],
            dtype=float,
        )
        result = forecast_model_secici(
            pd.DataFrame({"Kâr": values}, index=index),
            "Kâr",
            log=False,
            signed_transform=True,
            plot=False,
            trend_options=("t",),
        )

        self.assertEqual(result["target_transform"], "asinh")
        self.assertTrue(np.isfinite(result["future_forecast"]["Kâr Tahmin"]).all())
        self.assertNotIn("ROBUST_SEASONAL", result["mae_results"]["model"].tolist())


if __name__ == "__main__":
    unittest.main()
