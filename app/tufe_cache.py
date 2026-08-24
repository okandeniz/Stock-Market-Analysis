"""Align live quarterly TÜFE forecasts with company financial periods."""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd


REQUIRED_TUFE_COLUMNS = ("Log TUFE Tahmin", "TUFE Tahmin")
TUFE_CHANGE_COLUMN = "TÜFE Çeyreklik Log Değişim"


class TufeForecastError(RuntimeError):
    """Raised when a live TÜFE forecast cannot cover the requested horizon."""


def quarterly_tufe_levels(history: pd.DataFrame) -> pd.Series:
    """Return March/June/September/December CPI levels from monthly EVDS data."""
    if "TUFE" not in history.columns:
        raise TufeForecastError("TÜFE geçmişinde `TUFE` kolonu bulunamadı.")
    level = pd.to_numeric(history["TUFE"], errors="coerce").dropna().copy()
    level.index = pd.to_datetime(level.index)
    level = level.sort_index()
    level = level.loc[level.index.month.isin((3, 6, 9, 12))]
    level = level.loc[~level.index.duplicated(keep="last")]
    if level.empty or (level <= 0).any():
        raise TufeForecastError("Geçerli ve pozitif çeyrek sonu TÜFE endeksi bulunamadı.")
    return level


def prepare_tufe_log_changes(history: pd.DataFrame) -> pd.DataFrame:
    """Turn the trending CPI index into a stationary quarterly inflation rate."""
    level = quarterly_tufe_levels(history)
    changes = np.log(level).diff().dropna()
    return pd.DataFrame({TUFE_CHANGE_COLUMN: changes}, index=changes.index)


def forecast_log_tufe_exog_path(
    history: pd.DataFrame,
    future_index: pd.DatetimeIndex,
    forecast_func: Callable[..., dict[str, Any]],
) -> pd.DataFrame:
    """Forecast log-CPI using only observations available at a CV origin.

    With at least 13 quarterly changes the same model-selection engine used by
    the production CPI forecast is run.  Earlier validation origins use a
    robust recent-change fallback because a full model cannot yet be fitted.
    """
    if "log_TUFE" not in history.columns:
        raise TufeForecastError("CV TÜFE tahmini için `log_TUFE` kolonu gerekli.")
    future_dates = pd.DatetimeIndex(pd.to_datetime(future_index))
    levels = pd.to_numeric(history["log_TUFE"], errors="coerce").dropna().copy()
    levels.index = pd.to_datetime(levels.index)
    levels = levels.sort_index()
    if levels.empty:
        raise TufeForecastError("CV TÜFE tahmini için tarihsel değer bulunamadı.")
    expected = pd.date_range(levels.index[0], levels.index[-1], freq="QS-MAR")
    if not levels.index.equals(expected):
        raise TufeForecastError("CV TÜFE geçmişi ardışık çeyreklerden oluşmuyor.")
    expected_future = pd.date_range(levels.index[-1], periods=len(future_dates) + 1, freq="QS-MAR")[1:]
    if not future_dates.equals(expected_future):
        raise TufeForecastError("CV TÜFE tahmin tarihleri geçmişin devamıyla eşleşmiyor.")

    changes = levels.diff().dropna()
    if len(changes) >= 13:
        change_frame = pd.DataFrame({TUFE_CHANGE_COLUMN: changes}, index=changes.index)
        result = forecast_func(
            df=change_frame,
            col=TUFE_CHANGE_COLUMN,
            freq="QS-MAR",
            log=False,
            plot=False,
            trend_options=("t", "ct"),
            future_index=future_dates,
        )
        future = result.get("future_forecast")
        point_column = f"{TUFE_CHANGE_COLUMN} Tahmin"
        if not isinstance(future, pd.DataFrame) or point_column not in future.columns:
            raise TufeForecastError("CV TÜFE modeli çeyreklik değişim tahmini üretmedi.")
        change_path = pd.to_numeric(future[point_column], errors="coerce").reindex(future_dates)
    else:
        if changes.empty:
            step = 0.0
        else:
            step = float(changes.tail(min(8, len(changes))).median())
        change_path = pd.Series(step, index=future_dates, dtype=float)

    if change_path.isna().any():
        raise TufeForecastError("CV TÜFE değişim tahmini eksik değer içeriyor.")
    projected_log_levels = float(levels.iloc[-1]) + change_path.cumsum()
    return pd.DataFrame({"log_TUFE": projected_log_levels}, index=future_dates)


def reconstruct_tufe_levels(
    history: pd.DataFrame,
    change_result: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rebuild CPI levels from forecast quarterly log-inflation paths.

    The second result contains validation predictions converted back to index
    levels, so the graph and diagnostics remain understandable to users.
    """
    level = quarterly_tufe_levels(history)

    changes = change_result.get("future_forecast")
    if not isinstance(changes, pd.DataFrame) or changes.empty:
        raise TufeForecastError("Çeyreklik enflasyon modeli gelecek tahmini üretmedi.")
    prefix = TUFE_CHANGE_COLUMN
    mapping = {
        "TUFE Tahmin": f"{prefix} Tahmin",
        "TUFE Alt %80": f"{prefix} Alt %80",
        "TUFE Üst %80": f"{prefix} Üst %80",
        "TUFE Alt %95": f"{prefix} Alt %95",
        "TUFE Üst %95": f"{prefix} Üst %95",
    }
    absent = [source for source in mapping.values() if source not in changes.columns]
    if absent:
        raise TufeForecastError("Enflasyon tahmininde eksik kolonlar: " + ", ".join(absent))

    last_level = float(level.iloc[-1])
    projection = pd.DataFrame(index=pd.to_datetime(changes.index))
    for output, source in mapping.items():
        path = pd.to_numeric(changes[source], errors="coerce")
        projection[output] = last_level * np.exp(path.cumsum().to_numpy(dtype=float))
    projection.insert(0, "Log TUFE Tahmin", np.log1p(projection["TUFE Tahmin"]))

    cv = change_result.get("cv_predictions")
    cv_level_rows: list[pd.DataFrame] = []
    if isinstance(cv, pd.DataFrame) and not cv.empty and "fold" in cv.columns:
        for fold, group in cv.groupby("fold"):
            group = group.sort_index()
            anchors = level.loc[level.index < pd.Timestamp(group.index[0])]
            if anchors.empty:
                continue
            predicted = float(anchors.iloc[-1]) * np.exp(
                pd.to_numeric(group["prediction"], errors="coerce").cumsum()
            )
            actual = level.reindex(group.index)
            cv_level_rows.append(
                pd.DataFrame(
                    {"actual": actual, "prediction": predicted, "fold": fold},
                    index=group.index,
                )
            )
    cv_levels = (
        pd.concat(cv_level_rows).sort_index()
        if cv_level_rows
        else pd.DataFrame(columns=["actual", "prediction", "fold"])
    )
    return projection, cv_levels


def calculate_annual_inflation_projection(
    history: pd.DataFrame,
    projection: pd.DataFrame,
) -> pd.DataFrame:
    """Convert projected CPI levels into year-over-year inflation percentages."""
    actual = quarterly_tufe_levels(history)
    projected = projection.copy().sort_index()
    projected.index = pd.to_datetime(projected.index)
    required = [
        "TUFE Tahmin",
        "TUFE Alt %80",
        "TUFE Üst %80",
        "TUFE Alt %95",
        "TUFE Üst %95",
    ]
    absent = [column for column in required if column not in projected.columns]
    if absent:
        raise TufeForecastError("Yıllık enflasyon hesabında eksik kolonlar: " + ", ".join(absent))

    point_levels = pd.concat([actual, projected["TUFE Tahmin"]]).sort_index()
    result = pd.DataFrame(index=projected.index)
    result["Yıllık Enflasyon Tahmini"] = np.nan
    for coverage in (80, 95):
        result[f"Yıllık Enflasyon Alt %{coverage}"] = np.nan
        result[f"Yıllık Enflasyon Üst %{coverage}"] = np.nan

    for date in result.index:
        previous_year = date - pd.DateOffset(years=1)
        if previous_year not in point_levels.index:
            continue
        point_denominator = float(point_levels.loc[previous_year])
        if point_denominator <= 0:
            continue
        result.loc[date, "Yıllık Enflasyon Tahmini"] = (
            float(projected.loc[date, "TUFE Tahmin"]) / point_denominator - 1
        ) * 100
        for coverage in (80, 95):
            lower_levels = pd.concat(
                [actual, projected[f"TUFE Alt %{coverage}"]]
            ).sort_index()
            upper_levels = pd.concat(
                [actual, projected[f"TUFE Üst %{coverage}"]]
            ).sort_index()
            denominator_low = float(lower_levels.loc[previous_year])
            denominator_high = float(upper_levels.loc[previous_year])
            if denominator_low <= 0 or denominator_high <= 0:
                continue
            result.loc[date, f"Yıllık Enflasyon Alt %{coverage}"] = (
                float(projected.loc[date, f"TUFE Alt %{coverage}"]) / denominator_high - 1
            ) * 100
            result.loc[date, f"Yıllık Enflasyon Üst %{coverage}"] = (
                float(projected.loc[date, f"TUFE Üst %{coverage}"]) / denominator_low - 1
            ) * 100
    return result


def complete_tufe_history(history: pd.DataFrame, projection: pd.DataFrame) -> pd.DataFrame:
    """Fill missing historical TÜFE quarters from a bridge forecast.

    EVDS can return the requested quarter labels with empty values. A forecast
    starting at the last non-empty EVDS observation then contains both those
    missing historical quarters and the genuinely future quarters.
    """
    result = history.copy()
    projected = projection.copy()
    projected.index = pd.to_datetime(projected.index)
    for historical_col, forecast_col in (
        ("TUFE", "TUFE Tahmin"),
        ("log_TUFE", "Log TUFE Tahmin"),
    ):
        if historical_col not in result.columns or forecast_col not in projected.columns:
            continue
        current = pd.to_numeric(result[historical_col], errors="coerce")
        supplement = pd.to_numeric(
            projected[forecast_col].reindex(result.index), errors="coerce"
        )
        result[historical_col] = current.combine_first(supplement)
    return result


def has_complete_tufe_history(history: pd.DataFrame) -> bool:
    required = {"TUFE", "log_TUFE"}
    if not required.issubset(history.columns):
        return False
    values = (
        history[["TUFE", "log_TUFE"]]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    return not values.isna().any().any()


def select_future_tufe(
    forecast: pd.DataFrame,
    *,
    last_financial_date: pd.Timestamp,
    steps: int,
    freq: str = "QS-MAR",
) -> pd.DataFrame:
    missing_columns = set(REQUIRED_TUFE_COLUMNS).difference(forecast.columns)
    if missing_columns:
        raise TufeForecastError("Eksik TÜFE kolonları: " + ", ".join(sorted(missing_columns)))

    expected_index = pd.date_range(
        start=pd.Timestamp(last_financial_date), periods=steps + 1, freq=freq
    )[1:]
    available_columns = [
        name
        for name in (
            *REQUIRED_TUFE_COLUMNS,
            "TUFE Alt %80",
            "TUFE Üst %80",
            "TUFE Alt %95",
            "TUFE Üst %95",
        )
        if name in forecast.columns
    ]
    selected = forecast.reindex(expected_index).loc[:, available_columns]
    if selected.loc[:, list(REQUIRED_TUFE_COLUMNS)].isna().any().any():
        available = forecast.index.min(), forecast.index.max()
        raise TufeForecastError(
            "TÜFE tahmini gerekli dönemleri kapsamıyor. "
            f"Gerekli: {expected_index.min():%Y-%m}–{expected_index.max():%Y-%m}; "
            f"mevcut: {available[0]:%Y-%m}–{available[1]:%Y-%m}."
        )
    return selected
