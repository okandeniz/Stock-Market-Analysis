"""Quarterly statistical-model selection with rolling validation.

Each statistical family is tuned on the same horizon-matched validation
windows.  The best parameterization from every family is compared by MASE
(MAE is the tie-breaker), and one winning model produces the final forecast.
Naive forecasts and model combinations are deliberately excluded.
"""
from __future__ import annotations

import warnings
from typing import Any, Callable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import statsmodels.api as sm
from sklearn.metrics import mean_absolute_error
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

from .financial_metrics import quarter_steps_to_year_end
from .plotly_theme import apply_theme


_SMALL_ARIMA_ORDERS = (
    (1, 0, 0),
    (0, 0, 1),
    (1, 0, 1),
    (1, 1, 0),
    (0, 1, 1),
    (1, 1, 1),
)
_ARIMA_ORDERS = _SMALL_ARIMA_ORDERS + (
    (2, 0, 1),
    (1, 0, 2),
    (2, 1, 1),
    (1, 1, 2),
)
_SARIMA_CONFIGS = (
    ((1, 0, 0), (1, 0, 0, 4)),
    ((0, 0, 1), (0, 0, 1, 4)),
    ((1, 0, 1), (1, 0, 1, 4)),
    ((1, 1, 0), (0, 1, 1, 4)),
    ((0, 1, 1), (1, 0, 0, 4)),
    ((1, 1, 1), (1, 1, 0, 4)),
)
_ETS_CONFIGS = (
    {"trend": None, "damped_trend": False, "seasonal": None, "seasonal_periods": None},
    {"trend": "add", "damped_trend": False, "seasonal": None, "seasonal_periods": None},
    {"trend": "add", "damped_trend": True, "seasonal": None, "seasonal_periods": None},
    {"trend": None, "damped_trend": False, "seasonal": "add", "seasonal_periods": 4},
    {"trend": "add", "damped_trend": False, "seasonal": "add", "seasonal_periods": 4},
    {"trend": "add", "damped_trend": True, "seasonal": "add", "seasonal_periods": 4},
)


def _future_index(last_date: pd.Timestamp, steps: int, freq: str) -> pd.DatetimeIndex:
    return pd.date_range(start=last_date, periods=steps + 1, freq=freq)[1:]


def _default_exog_cv_forecast(
    history: pd.DataFrame,
    future_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Produce a conservative ex-ante exogenous path for validation.

    The production application supplies a dedicated CPI callback.  This
    fallback keeps the public forecasting function safe for other callers:
    realised values from a validation window are never used as future exog.
    """
    result = pd.DataFrame(index=future_index)
    for column in history.columns:
        values = pd.to_numeric(history[column], errors="coerce").dropna()
        if values.empty:
            raise ValueError(f"{column} için dışsal değişken geçmişi boş.")
        differences = values.diff().dropna()
        if differences.empty:
            increments = np.zeros(len(future_index), dtype=float)
        else:
            recent_step = float(differences.tail(min(8, len(differences))).median())
            if len(values) >= 5:
                seasonal_step = float((values.iloc[-1] - values.iloc[-5]) / 4.0)
                step = 0.65 * recent_step + 0.35 * seasonal_step
            else:
                step = recent_step
            increments = step * np.power(0.97, np.arange(len(future_index), dtype=float))
        result[column] = float(values.iloc[-1]) + np.cumsum(increments)
    return result


def _validation_folds(
    length: int,
    horizon: int,
    max_splits: int = 5,
) -> list[tuple[int, int]]:
    """Return recent expanding-window folds with the production horizon.

    Consecutive recent origins are intentionally used.  They measure the
    regime in which the production forecast will operate and avoid giving a
    very old eight-observation fold the same influence as the latest data.
    """
    horizon = max(1, int(horizon))
    latest_train_end = length - horizon
    min_train = max(8, horizon * 2)
    if latest_train_end < min_train:
        return []
    origins = list(range(min_train, latest_train_end + 1))[-max_splits:]
    return [(end, end + horizon) for end in origins]


def _candidate_specs(
    use_exog: bool,
    trend_options: tuple[str, ...],
    series_length: int,
) -> list[dict[str, Any]]:
    """Build parameter grids containing statistical models only."""
    trends = tuple(dict.fromkeys(trend_options)) or ("n",)

    def compatible_trends(
        order: tuple[int, int, int],
        seasonal_order: tuple[int, int, int, int] | None = None,
    ) -> tuple[str, ...]:
        seasonal_difference = seasonal_order[1] if seasonal_order is not None else 0
        if order[1] == 0 and seasonal_difference == 0:
            return trends
        reduced = tuple(trend for trend in trends if trend in {"n", "t"})
        return reduced or ("t",)
    specs: list[dict[str, Any]] = []

    for params in _ETS_CONFIGS:
        if params["seasonal"] is None or series_length >= 16:
            specs.append({"model": "ETS", "params": dict(params)})

    arima_orders = _ARIMA_ORDERS if series_length >= 20 else _SMALL_ARIMA_ORDERS
    for order in arima_orders:
        for trend in compatible_trends(order):
            specs.append({"model": "ARIMA", "params": {"order": order, "trend": trend}})

    if use_exog:
        exog_orders = _ARIMA_ORDERS if series_length >= 20 else _SMALL_ARIMA_ORDERS
        for order in exog_orders:
            for trend in compatible_trends(order):
                specs.append(
                    {
                        "model": "SARIMAX_EXOG",
                        "params": {
                            "order": order,
                            "seasonal_order": (0, 0, 0, 0),
                            "trend": trend,
                        },
                    }
                )

    if series_length >= 16:
        for order, seasonal_order in _SARIMA_CONFIGS:
            for trend in compatible_trends(order, seasonal_order):
                specs.append(
                    {
                        "model": "SARIMA",
                        "params": {
                            "order": order,
                            "seasonal_order": seasonal_order,
                            "trend": trend,
                        },
                    }
                )
                if use_exog:
                    specs.append(
                        {
                            "model": "SARIMAX_EXOG",
                            "params": {
                                "order": order,
                                "seasonal_order": seasonal_order,
                                "trend": trend,
                            },
                        }
                    )
    return specs


def _fit_and_predict(
    spec: dict[str, Any],
    train: pd.Series,
    steps: int,
    prediction_index: pd.DatetimeIndex,
    *,
    exog_train: pd.DataFrame | None = None,
    exog_future: pd.DataFrame | None = None,
) -> pd.Series:
    model_name = spec["model"]
    params = spec["params"]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if model_name == "ETS":
            fitted = ExponentialSmoothing(
                train,
                trend=params["trend"],
                damped_trend=params["damped_trend"],
                seasonal=params["seasonal"],
                seasonal_periods=params["seasonal_periods"],
                initialization_method="estimated",
            ).fit(optimized=True)
            values = fitted.forecast(steps)
        elif model_name == "ARIMA":
            fitted = sm.tsa.arima.ARIMA(
                train,
                order=params["order"],
                trend=params["trend"],
            ).fit()
            values = fitted.forecast(steps=steps)
        elif model_name in {"SARIMA", "SARIMAX_EXOG"}:
            uses_exog = model_name == "SARIMAX_EXOG"
            if uses_exog and (exog_train is None or exog_future is None):
                raise ValueError("SARIMAX_EXOG için dışsal veri gerekli.")
            fitted = SARIMAX(
                train,
                exog=exog_train if uses_exog else None,
                order=params["order"],
                seasonal_order=params["seasonal_order"],
                trend=params["trend"],
                enforce_stationarity=False,
                enforce_invertibility=False,
            ).fit(disp=False)
            values = fitted.get_forecast(
                steps=steps,
                exog=exog_future if uses_exog else None,
            ).predicted_mean
        else:
            raise ValueError(f"Desteklenmeyen istatistiksel model: {model_name}")

    return pd.Series(np.asarray(values, dtype=float).reshape(-1), index=prediction_index)


def _target_transform(
    source: pd.Series,
    log: bool,
    signed_transform: bool,
) -> tuple[pd.Series, float, float]:
    if log:
        return np.log1p(source), 0.0, 1.0
    center = float(source.median())
    if signed_transform:
        scale = float((source - center).abs().median()) * 1.4826
    else:
        scale = float(source.std(ddof=0))
    if not np.isfinite(scale) or scale < 1e-9:
        scale = 1.0
    transformed = (source - center) / scale
    if signed_transform:
        transformed = np.arcsinh(transformed)
    return transformed, center, scale


def _original_scale(
    values: pd.Series,
    *,
    log: bool,
    signed_transform: bool,
    center: float,
    scale: float,
    smearing: float = 1.0,
) -> pd.Series:
    raw = np.asarray(values, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        if log:
            transformed = np.exp(raw) * smearing - 1
        elif signed_transform:
            transformed = np.sinh(np.clip(raw, -20, 20)) * scale + center
        else:
            transformed = raw * scale + center
    return pd.Series(transformed, index=values.index)


def _mase_scale(train_original: pd.Series, seasonal_period: int = 4) -> float:
    values = np.asarray(train_original, dtype=float)
    if len(values) > seasonal_period:
        diffs = np.abs(values[seasonal_period:] - values[:-seasonal_period])
    else:
        diffs = np.abs(np.diff(values))
    scale = float(np.nanmean(diffs)) if len(diffs) else np.nan
    if not np.isfinite(scale) or scale < 1e-9:
        fallback = float(np.nanmean(np.abs(np.diff(values)))) if len(values) > 1 else 1.0
        scale = fallback if np.isfinite(fallback) and fallback >= 1e-9 else 1.0
    return scale


def _recency_weights(count: int) -> np.ndarray:
    weights = np.linspace(1.0, 2.0, num=count)
    return weights / weights.sum()


def _conformal_radius(errors: list[float], coverage: float) -> float:
    absolute = np.abs(np.asarray(errors, dtype=float))
    absolute = absolute[np.isfinite(absolute)]
    if not len(absolute):
        return np.nan
    quantile = min(1.0, np.ceil((len(absolute) + 1) * coverage) / len(absolute))
    return float(np.quantile(absolute, quantile, method="higher"))


def _regime_diagnostics(source: pd.Series) -> dict[str, Any]:
    """Detect recent shifts after removing quarterly trend/seasonality.

    Applying a level-shift detector directly to a steadily rising series (CPI
    is the typical example) produces false alarms.  Year-over-year differences
    retain abrupt changes while removing most deterministic trend and season.
    """
    diagnostic = source.diff(4).dropna() if len(source) >= 16 else source.diff().dropna()
    values = np.asarray(diagnostic, dtype=float)
    if len(values) < 12:
        return {"detected": False, "date": None, "score": np.nan}

    best_score = -np.inf
    best_split: int | None = None
    for split in range(max(4, len(values) - 8), len(values) - 3):
        left = values[max(0, split - 8):split]
        right = values[split:]
        pooled = np.sqrt((np.var(left) + np.var(right)) / 2)
        overall = np.std(values)
        denominator = max(float(pooled), float(overall) * 0.25, 1e-9)
        score = abs(float(np.mean(right) - np.mean(left))) / denominator
        if score > best_score:
            best_score = score
            best_split = split

    detected = bool(best_split is not None and best_score >= 1.5)
    return {
        "detected": detected,
        "date": diagnostic.index[best_split] if detected and best_split is not None else None,
        "score": float(best_score),
    }


def _rolling_interval_coverage(fold_errors: list[np.ndarray]) -> tuple[float, float]:
    """Measure conformal coverage using only errors available before each fold."""
    checks_80: list[bool] = []
    checks_95: list[bool] = []
    calibration: list[float] = []
    for errors in fold_errors:
        current = np.abs(np.asarray(errors, dtype=float))
        current = current[np.isfinite(current)]
        if calibration:
            radius_80 = _conformal_radius(calibration, 0.80)
            radius_95 = _conformal_radius(calibration, 0.95)
            checks_80.extend((current <= radius_80).tolist())
            checks_95.extend((current <= radius_95).tolist())
        calibration.extend(current.tolist())
    return (
        float(np.mean(checks_80)) if checks_80 else np.nan,
        float(np.mean(checks_95)) if checks_95 else np.nan,
    )


def _confidence_diagnostics(
    *,
    selected_mase: float,
    family_runner_up_mase: float,
    fold_variability: float,
    coverage_80: float,
    coverage_95: float,
    regime: dict[str, Any],
) -> tuple[int, str, dict[str, float], list[str]]:
    """Return an explained 0–100 forecast confidence score."""
    cv_score = 35.0 * (1.0 - np.clip(selected_mase / 1.5, 0.0, 1.0))
    if np.isfinite(family_runner_up_mase) and selected_mase > 1e-9:
        family_gap = (family_runner_up_mase - selected_mase) / selected_mase
        selection_score = 7.5 + 7.5 * np.clip(family_gap / 0.25, 0.0, 1.0)
    else:
        family_gap = np.nan
        selection_score = 7.5
    stability_score = 20.0 * (1.0 - np.clip(fold_variability, 0.0, 1.0))
    if np.isfinite(coverage_80) and np.isfinite(coverage_95):
        coverage_gap = abs(coverage_80 - 0.80) + abs(coverage_95 - 0.95)
        coverage_score = 15.0 * (1.0 - np.clip(coverage_gap / 0.80, 0.0, 1.0))
    else:
        coverage_score = 7.5
    if regime.get("detected"):
        regime_score = 7.5 * (
            1.0 - np.clip((float(regime.get("score", 1.5)) - 1.5) / 1.5, 0.0, 1.0)
        )
    else:
        regime_score = 15.0

    components = {
        "CV doğruluğu": float(cv_score),
        "Aileler arası seçicilik": float(selection_score),
        "Pencere istikrarı": float(stability_score),
        "Aralık kalibrasyonu": float(coverage_score),
        "Rejim istikrarı": float(regime_score),
    }
    score = int(round(sum(components.values())))
    label = "Yüksek" if score >= 75 else "Orta" if score >= 55 else "Düşük"

    reasons: list[str] = []
    if selected_mase < 0.80:
        reasons.append("CV hatası baz ölçeğe göre düşük")
    elif selected_mase >= 1.0:
        reasons.append("CV hatası serinin mevsimsel değişim ölçeğine göre yüksek")
    if np.isfinite(family_gap) and family_gap >= 0.10:
        reasons.append("Seçilen model diğer istatistiksel ailelerden belirgin biçimde daha düşük hatalı")
    if fold_variability > 0.50:
        reasons.append("Doğrulama pencereleri arasında hata değişken")
    if regime.get("detected"):
        reasons.append("Trend ve mevsimsellik sonrası yakın dönem rejim sinyali var")
    if not reasons:
        reasons.append("Seçilen modelin hata, pencere istikrarı ve aralık kalibrasyonu dengeli")
    return score, label, components, reasons


def forecast_model_secici(
    df: pd.DataFrame,
    col: str,
    exog_df: pd.DataFrame | None = None,
    exog_cols: list[str] | str | None = None,
    future_exog: pd.DataFrame | None = None,
    freq: str = "QS-MAR",
    test_size: float = 0.20,
    log: bool = True,
    signed_transform: bool = False,
    plot: bool = True,
    trend_options: tuple[str, ...] = ("n", "c", "t", "ct"),
    show_func: Callable[[Any], None] | None = None,
    future_index: pd.DatetimeIndex | None = None,
    require_sarimax_exog: bool = False,
    exog_cv_forecaster: Callable[[pd.DataFrame, pd.DatetimeIndex], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Forecast a quarterly target with robust rolling-origin validation.

    ``test_size`` is retained for API compatibility.  Validation now uses the
    actual production horizon because a two-quarter decision must be tested
    with two-quarter backtests, not with an unrelated percentage split.
    When exogenous variables are enabled, each validation path is forecast
    strictly from data available at that fold's origin.
    """
    del test_size
    if col not in df.columns:
        raise KeyError(f"Tahmin kolonu bulunamadı: {col}")

    data = pd.DataFrame({col: pd.to_numeric(df[col], errors="coerce")})
    data.index = pd.to_datetime(data.index)
    if data.index.has_duplicates:
        raise ValueError(f"{col} tahmin serisi tekrar eden dönemler içeriyor.")
    data = data.sort_index().asfreq(freq)
    missing_target = data.index[data[col].isna()]
    if len(missing_target):
        labels = ", ".join(missing_target.strftime("%Y-%m")[:8])
        suffix = " …" if len(missing_target) > 8 else ""
        raise ValueError(
            f"{col} tahmin serisi eksik veya ardışık olmayan dönemler içeriyor: "
            + labels
            + suffix
        )
    source = data[col]
    if len(source) < 13:
        raise ValueError(f"{col} tahmini için en az 13 geçerli dönem gerekli; bulunan: {len(source)}.")
    if log and (source <= -1).any():
        raise ValueError(f"{col} log tahmini için -1 veya daha küçük değer içeriyor.")

    if log and signed_transform:
        raise ValueError("log ve signed_transform aynı anda kullanılamaz.")
    y, target_center, target_scale = _target_transform(source, log, signed_transform)
    if future_index is None:
        forecast_steps = quarter_steps_to_year_end(y.index[-1])
        future_dates = _future_index(y.index[-1], forecast_steps, freq)
    else:
        future_dates = pd.DatetimeIndex(pd.to_datetime(future_index)).sort_values()
        if future_dates.empty or future_dates.has_duplicates:
            raise ValueError("future_index boş olamaz ve tekrar eden tarih içeremez.")
        forecast_steps = len(future_dates)
        expected_dates = _future_index(y.index[-1], forecast_steps, freq)
        if not future_dates.equals(expected_dates):
            raise ValueError(
                f"{col} için şirket-özel tahmin tarihleri hedef serinin son dönemiyle "
                "ardışık ve tam eşleşmiyor."
            )

    folds = _validation_folds(len(y), forecast_steps)
    if len(folds) < 2:
        raise ValueError(f"{col} için en az iki zaman serisi doğrulama penceresi oluşturulamadı.")

    use_exog = exog_df is not None and exog_cols is not None
    if require_sarimax_exog and not use_exog:
        raise ValueError("SARIMAX_EXOG zorunlu; tarihsel dışsal veri sağlanmadı.")
    exog = None
    selected_exog_cols: list[str] = []
    if use_exog:
        selected_exog_cols = [exog_cols] if isinstance(exog_cols, str) else list(exog_cols)
        exog = exog_df.copy()
        exog.index = pd.to_datetime(exog.index)
        exog = exog.sort_index().asfreq(freq)[selected_exog_cols]
        exog = exog.reindex(y.index).apply(pd.to_numeric, errors="coerce")
        if exog.isna().any().any():
            raise ValueError("Tarihsel dışsal veri hedef seriyle tam eşleşmiyor.")

    prepared_future_exog = None
    if use_exog:
        if future_exog is None:
            raise ValueError("Dışsal değişkenli tahmin için future_exog gerekli.")
        prepared_future_exog = future_exog.copy()
        prepared_future_exog.index = pd.to_datetime(prepared_future_exog.index)
        prepared_future_exog = (
            prepared_future_exog.sort_index().asfreq(freq)[selected_exog_cols]
            .apply(pd.to_numeric, errors="coerce")
        )
        if (
            len(prepared_future_exog) != forecast_steps
            or not prepared_future_exog.index.equals(future_dates)
            or prepared_future_exog.isna().any().any()
        ):
            raise ValueError("future_exog tahmin ufkuyla eşleşmiyor veya eksik değer içeriyor.")

    cv_exog_paths: dict[int, pd.DataFrame] = {}
    if use_exog:
        assert exog is not None
        forecaster = exog_cv_forecaster or _default_exog_cv_forecast
        for fold_number, (train_end, test_end) in enumerate(folds):
            fold_index = pd.DatetimeIndex(y.index[train_end:test_end])
            path = forecaster(exog.iloc[:train_end].copy(), fold_index)
            if not isinstance(path, pd.DataFrame):
                raise TypeError("exog_cv_forecaster bir DataFrame döndürmeli.")
            path = path.copy()
            path.index = pd.to_datetime(path.index)
            absent = [name for name in selected_exog_cols if name not in path.columns]
            if absent:
                raise ValueError("CV dışsal değişken tahmininde eksik kolonlar: " + ", ".join(absent))
            path = path.reindex(fold_index).loc[:, selected_exog_cols]
            path = path.apply(pd.to_numeric, errors="coerce")
            if path.isna().any().any():
                raise ValueError("CV dışsal değişken tahmini eksik veya tarihlerle eşleşmiyor.")
            cv_exog_paths[fold_number] = path

    specs = _candidate_specs(use_exog, trend_options, len(y))
    validation_rows: list[dict[str, Any]] = []
    candidate_predictions: dict[int, list[pd.Series]] = {}
    candidate_encoded_residuals: dict[int, list[float]] = {}
    fold_weights = _recency_weights(len(folds))

    for candidate_index, spec in enumerate(specs):
        fold_maes: list[float] = []
        fold_mases: list[float] = []
        fold_predictions: list[pd.Series] = []
        encoded_residuals: list[float] = []
        for fold_number, (train_end, test_end) in enumerate(folds):
            train = y.iloc[:train_end]
            test = y.iloc[train_end:test_end]
            try:
                prediction = _fit_and_predict(
                    spec,
                    train,
                    len(test),
                    test.index,
                    exog_train=exog.iloc[:train_end] if exog is not None else None,
                    exog_future=cv_exog_paths.get(fold_number) if exog is not None else None,
                )
                actual_original = source.iloc[train_end:test_end]
                prediction_original = _original_scale(
                    prediction,
                    log=log,
                    signed_transform=signed_transform,
                    center=target_center,
                    scale=target_scale,
                )
                mae = float(mean_absolute_error(actual_original, prediction_original))
                mase = mae / _mase_scale(source.iloc[:train_end])
                if not np.isfinite(mae) or not np.isfinite(mase) or mase > 1e6:
                    raise ValueError("Sayısal olarak kararsız tahmin adayı.")
                fold_maes.append(mae)
                fold_mases.append(mase)
                fold_predictions.append(prediction)
                encoded_residuals.extend((test - prediction).to_numpy(dtype=float).tolist())
            except Exception:
                break

        # A production candidate must be dependable at every validation origin.
        if len(fold_maes) == len(folds):
            candidate_predictions[candidate_index] = fold_predictions
            candidate_encoded_residuals[candidate_index] = encoded_residuals
            validation_rows.append(
                {
                    "candidate_index": candidate_index,
                    "model": spec["model"],
                    "mae": float(np.average(fold_maes, weights=fold_weights)),
                    "mae_mean": float(np.mean(fold_maes)),
                    "mae_std": float(np.std(fold_maes)),
                    "mase": float(np.average(fold_mases, weights=fold_weights)),
                    "mase_std": float(np.std(fold_mases)),
                    "cv_folds": len(fold_maes),
                    "params": {
                        **spec["params"],
                        "exog_cols": selected_exog_cols if spec["model"] == "SARIMAX_EXOG" else None,
                    },
                }
            )

    if not validation_rows:
        raise RuntimeError(f"{col} için hiçbir tahmin modeli başarıyla kurulamadı.")

    mae_df = pd.DataFrame(validation_rows).sort_values(
        ["mase", "mae", "mae_std", "model"], ascending=[True, True, True, True]
    ).reset_index(drop=True)

    sarimax_attempted = sum(spec["model"] == "SARIMAX_EXOG" for spec in specs)
    sarimax_rows = mae_df.loc[mae_df["model"] == "SARIMAX_EXOG"]
    if require_sarimax_exog and sarimax_rows.empty:
        raise RuntimeError(
            f"{col} için SARIMAX_EXOG adayları denendi ancak bütün CV "
            "pencerelerinde başarılı olan model kurulamadı."
        )

    # Önce her model ailesinin parametreleri kendi içinde optimize edilir.
    # Ardından yalnızca aile kazananları aynı hata metriğiyle karşılaştırılır.
    mae_df["family_rank"] = mae_df.groupby("model").cumcount() + 1
    mae_df["is_family_best"] = mae_df["family_rank"].eq(1)
    family_best = (
        mae_df.loc[mae_df["is_family_best"]]
        .sort_values(["mase", "mae", "mae_std", "model"])
        .reset_index(drop=True)
    )
    selected_row = family_best.iloc[0]
    selected_candidate_index = int(selected_row["candidate_index"])
    selected_spec = specs[selected_candidate_index]
    mae_df["is_selected"] = mae_df["candidate_index"].eq(selected_candidate_index)

    # Seçilen tek modelin CV tahminlerini ve hatalarını oluştur.
    cv_rows: list[pd.DataFrame] = []
    selected_errors: list[float] = []
    selected_fold_errors: list[np.ndarray] = []
    selected_fold_maes: list[float] = []
    for fold_number, (train_end, test_end) in enumerate(folds):
        actual = source.iloc[train_end:test_end]
        encoded_prediction = candidate_predictions[selected_candidate_index][fold_number]
        selected_prediction = _original_scale(
            encoded_prediction,
            log=log,
            signed_transform=signed_transform,
            center=target_center,
            scale=target_scale,
        )
        errors = actual - selected_prediction
        selected_errors.extend(errors.to_numpy(dtype=float).tolist())
        selected_fold_errors.append(errors.to_numpy(dtype=float))
        selected_fold_maes.append(float(np.mean(np.abs(errors))))
        cv_rows.append(
            pd.DataFrame(
                {
                    "actual": actual,
                    "prediction": selected_prediction,
                    "fold": fold_number + 1,
                },
                index=actual.index,
            )
        )

    cv_detail = pd.concat(cv_rows).sort_index()
    cv_plot = cv_detail.groupby(level=0)[["actual", "prediction"]].mean()

    try:
        encoded_future_prediction = _fit_and_predict(
            selected_spec,
            y,
            forecast_steps,
            future_dates,
            exog_train=exog,
            exog_future=prepared_future_exog,
        )
    except Exception as exc:
        raise RuntimeError(
            f"{col} için seçilen {selected_spec['model']} modeli tam veri üzerinde "
            "yeniden kurulamadı."
        ) from exc
    smearing = 1.0
    if log:
        residuals = np.asarray(
            candidate_encoded_residuals[selected_candidate_index], dtype=float
        )
        smearing = float(
            np.clip(np.mean(np.exp(np.clip(residuals, -20, 20))), 0.8, 1.25)
        )
    future_prediction = _original_scale(
        encoded_future_prediction,
        log=log,
        signed_transform=signed_transform,
        center=target_center,
        scale=target_scale,
        smearing=smearing,
    )

    radius_80 = _conformal_radius(selected_errors, 0.80)
    radius_95 = _conformal_radius(selected_errors, 0.95)
    lower_80 = future_prediction - radius_80
    upper_80 = future_prediction + radius_80
    lower_95 = future_prediction - radius_95
    upper_95 = future_prediction + radius_95
    if log:
        lower_80 = lower_80.clip(lower=0)
        lower_95 = lower_95.clip(lower=0)

    regime = _regime_diagnostics(source)
    fold_variability = float(
        np.std(selected_fold_maes) / max(np.mean(selected_fold_maes), 1e-9)
    )
    selected_mae = float(selected_row["mae"])
    selected_mase = float(selected_row["mase"])
    family_runner_up_mase = (
        float(family_best.iloc[1]["mase"]) if len(family_best) > 1 else np.nan
    )
    coverage_80, coverage_95 = _rolling_interval_coverage(selected_fold_errors)
    confidence_score, model_confidence, confidence_components, confidence_reasons = (
        _confidence_diagnostics(
            selected_mase=selected_mase,
            family_runner_up_mase=family_runner_up_mase,
            fold_variability=fold_variability,
            coverage_80=coverage_80,
            coverage_95=coverage_95,
            regime=regime,
        )
    )
    best_model_name = str(selected_row["model"])
    best_params = dict(selected_row["params"])
    parameter_summary = ", ".join(
        f"{name}={value}"
        for name, value in best_params.items()
        if value is not None and name != "exog_cols"
    )

    if plot:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=source.index, y=source, mode="lines", name="GERÇEK"))
        fig.add_trace(
            go.Scatter(
                x=cv_plot.index,
                y=cv_plot["prediction"],
                mode="lines+markers",
                name=f"CV TAHMİNİ ({len(folds)} PENCERE)",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=future_dates,
                y=lower_95,
                mode="lines",
                line={"width": 0},
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=future_dates,
                y=upper_95,
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                fillcolor="rgba(110, 180, 50, 0.10)",
                name="%95 TAHMİN ARALIĞI",
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=future_dates,
                y=lower_80,
                mode="lines",
                line={"width": 0},
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=future_dates,
                y=upper_80,
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                fillcolor="rgba(110, 180, 50, 0.20)",
                name="%80 TAHMİN ARALIĞI",
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=future_dates,
                y=future_prediction,
                mode="lines+markers",
                line={"dash": "dash"},
                name="GELECEK TAHMİNİ",
            )
        )
        apply_theme(
            fig,
            height=440,
            title=(
                f"{col} — {best_model_name} ({parameter_summary}) | "
                f"Güven: {confidence_score}/100 ({model_confidence})"
            ),
        )
        (show_func or (lambda figure: figure.show()))(fig)

    future_forecast = pd.DataFrame(
        {
            f"{col} Tahmin": future_prediction,
            f"{col} Alt %80": lower_80,
            f"{col} Üst %80": upper_80,
            f"{col} Alt %95": lower_95,
            f"{col} Üst %95": upper_95,
        }
    )
    if log:
        future_forecast.insert(
            0,
            f"Log {col} Tahmin",
            np.log1p(future_forecast[f"{col} Tahmin"].clip(lower=0)),
        )

    return {
        "mae_results": mae_df.drop(columns=["candidate_index"]),
        "family_best_results": family_best.drop(columns=["candidate_index"]),
        "best_model_name": best_model_name,
        "best_params": best_params,
        "best_test_prediction": cv_plot["prediction"],
        "cv_predictions": cv_detail,
        "final_model": {"model": best_model_name, "params": best_params},
        "future_forecast": future_forecast,
        "validation": "horizon_matched_expanding_window_cv",
        "selection_metric": "mase",
        "model_selection": "lowest_optimized_family_mase",
        "cv_folds": len(folds),
        "candidate_count": len(specs),
        "successful_candidate_count": len(mae_df),
        "optimized_model_families": family_best["model"].tolist(),
        "sarimax_exog_attempted": sarimax_attempted,
        "sarimax_exog_successful": len(sarimax_rows),
        "sarimax_exog_best_mae": (
            float(sarimax_rows["mae"].min()) if not sarimax_rows.empty else np.nan
        ),
        "forecast_steps": forecast_steps,
        "forecast_start": future_dates[0],
        "forecast_end": future_dates[-1],
        "selected_model_mae": selected_mae,
        "selected_model_mase": selected_mase,
        "model_confidence": model_confidence,
        "confidence_score": confidence_score,
        "confidence_components": confidence_components,
        "confidence_reasons": confidence_reasons,
        "fold_error_variability": fold_variability,
        "interval_coverage_80": coverage_80,
        "interval_coverage_95": coverage_95,
        "regime_change_detected": bool(regime["detected"]),
        "regime_change_date": regime["date"],
        "regime_change_score": regime["score"],
        "interval_method": "rolling_cv_conformal",
        "target_transform": "log1p" if log else "asinh" if signed_transform else "standardized",
        "cv_exog_method": (
            "dedicated_ex_ante_forecast"
            if use_exog and exog_cv_forecaster is not None
            else "default_ex_ante_forecast"
            if use_exog
            else "not_applicable"
        ),
    }
