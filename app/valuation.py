from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .financial_metrics import prepare_quarterly_financial_flows, relative_discount_pct


FLOW_COLUMNS = ("Satış Gelirleri", "Ana Ortaklık Payları", "FAVÖK")
EQUITY_COLUMN = "  Ana Ortaklığa Ait Özkaynaklar"
SHARE_COLUMN = "  Ödenmiş Sermaye"

INSUFFICIENT_VALUATION_MESSAGE = (
    "Bu şirket için yeterli tarihsel veri bulunamadığından ileri değerleme yapılamaz. "
    "Yeni halka arz edilen şirketlerde en az iki tamamlanmış geçmiş mali yıl ve "
    "yeterli geçerli çarpan verisi oluşması beklenir."
)


class InsufficientValuationDataError(ValueError):
    """Raised when the company does not yet have a defensible valuation history."""


@dataclass(frozen=True)
class ValuationResult:
    summary: pd.DataFrame
    methods: pd.DataFrame
    assumptions: pd.DataFrame
    projection: pd.DataFrame
    data_quality: str


def _finite(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _quantile(series: pd.Series, q: float, default: float) -> float:
    clean = _finite(series)
    return float(clean.quantile(q)) if len(clean) else float(default)


def _bounded_blend(current: float, history: pd.Series, current_weight: float = 0.60) -> tuple[float, float, float]:
    clean = _finite(history)
    if clean.empty:
        return float(current), float(current), float(current)
    median = float(clean.median())
    low = float(clean.quantile(0.25))
    high = float(clean.quantile(0.75))
    base = current_weight * float(current) + (1.0 - current_weight) * median
    outer_low = float(clean.quantile(0.10))
    outer_high = float(clean.quantile(0.90))
    base = float(np.clip(base, min(outer_low, outer_high), max(outer_low, outer_high)))
    return min(low, base), base, max(high, base)


def _complete_annual_flows(quarterly: pd.DataFrame) -> pd.DataFrame:
    groups: list[pd.Series] = []
    for year, group in quarterly.groupby(quarterly.index.year):
        if set(group.index.month) != {3, 6, 9, 12} or len(group) != 4:
            continue
        row = group.loc[:, list(FLOW_COLUMNS)].sum()
        row.name = int(year)
        groups.append(row)
    if not groups:
        return pd.DataFrame(columns=list(FLOW_COLUMNS), dtype=float)
    return pd.DataFrame(groups).sort_index()


def _robust_multiple(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    clean = clean.loc[clean > 0].dropna()
    if clean.empty:
        return {"base": np.nan, "low": np.nan, "high": np.nan, "count": 0.0, "stability": 0.0}

    # Piyasa çarpanlarında birkaç yıl önceki rejim, özellikle kârlılığı hızla
    # değişen şirketlerde bugünkü değerlemeyi temsil etmeyebilir. Son altı
    # çeyrek hem en az bir tam yılı kapsar hem de eski üç haneli çarpanların
    # güncel tek/çift haneli rejimi ezmesini önler.
    clean = clean.tail(6)
    if len(clean) >= 4:
        lower, upper = clean.quantile([0.10, 0.90])
        clean = clean.clip(lower=float(lower), upper=float(upper))
    median = float(clean.median())
    latest = float(clean.iloc[-1])
    # Son gözlem güncel piyasa rejimini taşır; medyan ise geçici bir çeyrek
    # etkisine karşı çıpa görevi görür.
    base = float(0.65 * latest + 0.35 * median)
    base = float(np.clip(base, float(clean.quantile(0.10)), float(clean.quantile(0.90))))
    low = float(clean.quantile(0.25))
    high = float(clean.quantile(0.75))
    dispersion = (high - low) / max(abs(base), 1e-9)
    sample_factor = min(1.0, len(clean) / 8.0)
    regime_gap = abs(latest - median) / max(abs(median), 1e-9)
    stability = sample_factor / (1.0 + max(0.0, dispersion) + 0.5 * regime_gap)
    return {
        "base": base,
        "low": min(low, base),
        "high": max(high, base),
        "count": float(len(clean)),
        "stability": float(stability),
    }


def _calculate_methods(
    projection: pd.DataFrame,
    ratios: pd.DataFrame,
    *,
    shares: float,
    horizon_type: str,
) -> pd.DataFrame:
    recent = ratios.tail(12)
    multiple_specs = {
        "F/K": ("F/K", 0.30),
        "PD/DD": ("PD/DD", 0.15),
        "FD/FAVÖK": ("FD/FAVÖK", 0.35),
        "FD/NS": ("FD/NS", 0.20),
    }
    multiples = {
        method: _robust_multiple(
            recent[column] if column in recent.columns else pd.Series(dtype=float)
        )
        for method, (column, _) in multiple_specs.items()
    }

    method_rows: list[dict[str, Any]] = []
    raw_weights: dict[str, float] = {}
    for method, (_, importance) in multiple_specs.items():
        multiple = multiples[method]
        base = projection.loc["Baz"]
        low = projection.loc["Temkinli"]
        high = projection.loc["İyimser"]
        valid = np.isfinite(multiple["base"]) and multiple["count"] >= 4
        if method == "F/K":
            valid = valid and float(base["Net Kâr"]) > 0
            target = float(base["Net Kâr"] / shares * multiple["base"]) if valid else np.nan
            target_low = float(low["Net Kâr"] / shares * multiple["low"]) if valid else np.nan
            target_high = float(high["Net Kâr"] / shares * multiple["high"]) if valid else np.nan
        elif method == "PD/DD":
            valid = valid and float(base["Özkaynak"]) > 0
            target = float(base["Özkaynak"] / shares * multiple["base"]) if valid else np.nan
            target_low = float(low["Özkaynak"] / shares * multiple["low"]) if valid else np.nan
            target_high = float(high["Özkaynak"] / shares * multiple["high"]) if valid else np.nan
            if horizon_type == "12 aylık ileri değerleme":
                importance *= 0.75
        elif method == "FD/FAVÖK":
            valid = valid and float(base["FAVÖK"]) > 0
            target = float((base["FAVÖK"] * multiple["base"] - base["Net Borç"]) / shares) if valid else np.nan
            target_low = float((low["FAVÖK"] * multiple["low"] - low["Net Borç"]) / shares) if valid else np.nan
            target_high = float((high["FAVÖK"] * multiple["high"] - high["Net Borç"]) / shares) if valid else np.nan
        else:
            # Satışlar tüm sermaye sağlayıcılarına ait bir faaliyet kalemidir;
            # bu nedenle FD/NS ile firma değeri bulunup net borç düşülür.
            valid = valid and float(base["Satış Gelirleri"]) > 0
            target = float((base["Satış Gelirleri"] * multiple["base"] - base["Net Borç"]) / shares) if valid else np.nan
            target_low = float((low["Satış Gelirleri"] * multiple["low"] - low["Net Borç"]) / shares) if valid else np.nan
            target_high = float((high["Satış Gelirleri"] * multiple["high"] - high["Net Borç"]) / shares) if valid else np.nan

        if valid and (not np.isfinite(target) or target <= 0):
            valid = False
            target = target_low = target_high = np.nan
        elif valid:
            target_low = max(0.0, float(target_low))
            target_high = max(float(target), float(target_high))

        raw_weight = float(importance * multiple["stability"]) if valid else 0.0
        raw_weights[method] = raw_weight
        method_rows.append(
            {
                "Yöntem": method,
                "Baz Çarpan": multiple["base"],
                "Çarpan Alt": multiple["low"],
                "Çarpan Üst": multiple["high"],
                "Örnek Sayısı": int(multiple["count"]),
                "Baz Hedef": target,
                "Temkinli Hedef": min(target_low, target) if valid else np.nan,
                "İyimser Hedef": max(target_high, target) if valid else np.nan,
                "Ham Güven Ağırlığı": raw_weight,
            }
        )

    weight_total = sum(raw_weights.values())
    if weight_total <= 0:
        raise InsufficientValuationDataError(
            "En az dört gözleme sahip geçerli bir değerleme çarpanı bulunamadı."
        )
    methods = pd.DataFrame(method_rows).set_index("Yöntem")
    methods["Güven Ağırlığı %"] = [raw_weights[name] / weight_total * 100 for name in methods.index]
    return methods.drop(columns=["Ham Güven Ağırlığı"])


def _retention_ratio(
    ratios: pd.DataFrame,
    annual_flows: pd.DataFrame,
) -> tuple[float, int]:
    if EQUITY_COLUMN not in ratios.columns or annual_flows.empty:
        return 0.75, 0
    year_end = ratios.loc[pd.DatetimeIndex(ratios.index).month == 12, [EQUITY_COLUMN]].copy()
    if year_end.empty:
        return 0.75, 0
    year_end.index = pd.DatetimeIndex(year_end.index).year
    equity = _finite(year_end[EQUITY_COLUMN]).sort_index()
    proxies: list[float] = []
    for year in equity.index.intersection(annual_flows.index):
        previous_year = int(year) - 1
        if previous_year not in equity.index:
            continue
        profit = float(annual_flows.loc[year, "Ana Ortaklık Payları"])
        if profit <= 0:
            continue
        proxy = (float(equity.loc[year]) - float(equity.loc[previous_year])) / profit
        if np.isfinite(proxy):
            proxies.append(float(np.clip(proxy, 0.0, 1.0)))
    if not proxies:
        return 0.75, 0
    return float(np.median(proxies)), len(proxies)


def _scenario_projection(
    quarterly: pd.DataFrame,
    ratios: pd.DataFrame,
) -> tuple[dict[str, float | int | str], pd.DataFrame, pd.DataFrame]:
    latest = pd.Timestamp(quarterly.index[-1])
    latest_year = int(latest.year)
    quarter_number = latest.month // 3
    annual = _complete_annual_flows(quarterly)
    latest_ratio = ratios.sort_index().iloc[-1]
    latest_equity = float(pd.to_numeric(latest_ratio.get(EQUITY_COLUMN), errors="coerce"))
    if not np.isfinite(latest_equity):
        raise InsufficientValuationDataError(
            "Son dönem ana ortaklık özkaynağı bulunamadı."
        )

    historical_annual = annual.loc[annual.index < latest_year]
    if latest.month == 12:
        if latest_year not in annual.index:
            raise InsufficientValuationDataError(
                "Aralık değerlemesi için cari yılın dört gerçek çeyreği bulunamadı."
            )
        if len(historical_annual) < 2:
            raise InsufficientValuationDataError(
                "12 aylık ileri değerleme için en az iki tamamlanmış geçmiş mali yıl gerekli."
            )
        current = annual.loc[latest_year]
        sales_growth = _finite(annual["Satış Gelirleri"].pct_change()).clip(-0.50, 1.00)
        recent_growth = float(sales_growth.iloc[-1]) if len(sales_growth) else 0.0
        growth_low, growth_base, growth_high = _bounded_blend(recent_growth, sales_growth, 0.60)
        sales_scenarios = {
            "low": float(current["Satış Gelirleri"] * (1.0 + growth_low)),
            "base": float(current["Satış Gelirleri"] * (1.0 + growth_base)),
            "high": float(current["Satış Gelirleri"] * (1.0 + growth_high)),
        }
        target_year = latest_year + 1
        reported_quarters = 0
        forecast_quarters = 4
        horizon_type = "12 aylık ileri değerleme"
        seasonality_samples = len(sales_growth)
        sales_driver_label = "Yıllık satış büyümesi"
        sales_driver = (growth_low, growth_base, growth_high)
        margin_history = annual
        current_net_margin = float(current["Ana Ortaklık Payları"] / current["Satış Gelirleri"])
        current_ebitda_margin = float(current["FAVÖK"] / current["Satış Gelirleri"])
        retention, retention_samples = _retention_ratio(ratios, annual)
        equity_profit_factor = retention
    else:
        current_ytd = quarterly.loc[quarterly.index.year == latest_year]
        if len(current_ytd) != quarter_number:
            raise InsufficientValuationDataError(
                "Cari yılın açıklanan çeyrekleri eksik; mevsimsel yıllıklandırma yapılamadı."
            )
        shares: list[float] = []
        for year, full_year in historical_annual.iterrows():
            year_quarters = quarterly.loc[quarterly.index.year == int(year)].sort_index()
            if len(year_quarters) != 4:
                continue
            annual_sales = float(full_year["Satış Gelirleri"])
            if annual_sales <= 0:
                continue
            shares.append(float(year_quarters.iloc[:quarter_number]["Satış Gelirleri"].sum() / annual_sales))
        share_series = pd.Series(shares, dtype=float).loc[lambda s: (s > 0) & (s <= 1.5)]
        if len(share_series) < 2:
            raise InsufficientValuationDataError(
                "Mevsimsel yıl sonu tahmini için en az iki tamamlanmış geçmiş mali yıl gerekli."
            )
        share_low = float(share_series.quantile(0.25))
        share_base = float(share_series.median())
        share_high = float(share_series.quantile(0.75))
        ytd_sales = float(current_ytd["Satış Gelirleri"].sum())
        sales_scenarios = {
            "low": ytd_sales / max(share_high, 1e-9),
            "base": ytd_sales / max(share_base, 1e-9),
            "high": ytd_sales / max(share_low, 1e-9),
        }
        target_year = latest_year
        reported_quarters = quarter_number
        forecast_quarters = 4 - quarter_number
        horizon_type = "Cari yıl sonu değerlemesi"
        seasonality_samples = len(share_series)
        sales_driver_label = "Açıklanan dönem / yıllık satış payı"
        sales_driver = (share_low, share_base, share_high)
        margin_history = historical_annual
        current_net_margin = float(
            current_ytd["Ana Ortaklık Payları"].sum() / current_ytd["Satış Gelirleri"].sum()
        )
        current_ebitda_margin = float(current_ytd["FAVÖK"].sum() / current_ytd["Satış Gelirleri"].sum())
        retention, retention_samples = 1.0, 0
        equity_profit_factor = 1.0

    historical_net_margins = _finite(
        margin_history["Ana Ortaklık Payları"] / margin_history["Satış Gelirleri"].replace(0, np.nan)
    )
    historical_ebitda_margins = _finite(
        margin_history["FAVÖK"] / margin_history["Satış Gelirleri"].replace(0, np.nan)
    )
    net_low, net_base, net_high = _bounded_blend(current_net_margin, historical_net_margins)
    ebitda_low, ebitda_base, ebitda_high = _bounded_blend(
        current_ebitda_margin, historical_ebitda_margins
    )

    year_end_ratios = ratios.loc[pd.DatetimeIndex(ratios.index).month == 12]
    debt_ratio_history = (
        _finite(year_end_ratios["net_borc/FAVOK"])
        if "net_borc/FAVOK" in year_end_ratios.columns
        else pd.Series(dtype=float)
    )
    latest_debt_ratio = float(pd.to_numeric(latest_ratio.get("net_borc/FAVOK"), errors="coerce"))
    if not np.isfinite(latest_debt_ratio):
        latest_debt_ratio = float(debt_ratio_history.median()) if len(debt_ratio_history) else 0.0
    debt_low, debt_base, debt_high = _bounded_blend(latest_debt_ratio, debt_ratio_history)

    projection_rows: list[dict[str, Any]] = []
    scenario_values: dict[str, dict[str, float]] = {}
    reported_profit = float(
        quarterly.loc[quarterly.index.year == latest_year, "Ana Ortaklık Payları"].sum()
    )
    for scenario, sales, net_margin, ebitda_margin, debt_ratio in (
        ("Temkinli", sales_scenarios["low"], net_low, ebitda_low, debt_high),
        ("Baz", sales_scenarios["base"], net_base, ebitda_base, debt_base),
        ("İyimser", sales_scenarios["high"], net_high, ebitda_high, debt_low),
    ):
        net_income = float(sales * net_margin)
        ebitda = float(sales * ebitda_margin)
        net_debt = float(ebitda * debt_ratio)
        if latest.month == 12:
            equity_addition = net_income * equity_profit_factor
        else:
            # Son özkaynak açıklanan yıl içi kârı zaten içerir. Bu nedenle tam
            # yıl kârını yeniden eklemek yerine yalnızca kalan çeyreklerin kârı
            # veya zararı özkaynak köprüsüne taşınır.
            equity_addition = net_income - reported_profit
        equity = latest_equity + equity_addition
        values = {
            "sales": float(sales),
            "net_income": net_income,
            "ebitda": ebitda,
            "net_debt": net_debt,
            "equity": float(equity),
            "net_margin": float(net_margin),
            "ebitda_margin": float(ebitda_margin),
            "debt_ratio": float(debt_ratio),
        }
        scenario_values[scenario] = values
        projection_rows.append(
            {
                "Senaryo": scenario,
                "Satış Gelirleri": values["sales"],
                "Net Kâr": values["net_income"],
                "FAVÖK": values["ebitda"],
                "Net Borç": values["net_debt"],
                "Özkaynak": values["equity"],
                "Net Kâr Marjı %": values["net_margin"] * 100,
                "FAVÖK Marjı %": values["ebitda_margin"] * 100,
                "Net Borç/FAVÖK": values["debt_ratio"],
            }
        )

    assumptions = pd.DataFrame(
        [
            {"Varsayım": sales_driver_label, "Birim": "%", "Temkinli": sales_driver[0] * 100, "Baz": sales_driver[1] * 100, "İyimser": sales_driver[2] * 100, "Örnek Sayısı": seasonality_samples},
            {"Varsayım": "Net kâr marjı", "Birim": "%", "Temkinli": net_low * 100, "Baz": net_base * 100, "İyimser": net_high * 100, "Örnek Sayısı": len(historical_net_margins)},
            {"Varsayım": "FAVÖK marjı", "Birim": "%", "Temkinli": ebitda_low * 100, "Baz": ebitda_base * 100, "İyimser": ebitda_high * 100, "Örnek Sayısı": len(historical_ebitda_margins)},
            {"Varsayım": "Net Borç/FAVÖK", "Birim": "x", "Temkinli": debt_high, "Baz": debt_base, "İyimser": debt_low, "Örnek Sayısı": len(debt_ratio_history)},
            {"Varsayım": "Özkaynakta tutulan kâr oranı", "Birim": "%", "Temkinli": retention * 100, "Baz": retention * 100, "İyimser": retention * 100, "Örnek Sayısı": retention_samples},
        ]
    )
    metadata: dict[str, float | int | str] = {
        "target_year": target_year,
        "reported_quarters": reported_quarters,
        "forecast_quarters": forecast_quarters,
        "horizon_type": horizon_type,
        "seasonality_samples": seasonality_samples,
        "complete_years": len(annual),
    }
    return metadata, pd.DataFrame(projection_rows).set_index("Senaryo"), assumptions


def _historical_validation(
    quarterly: pd.DataFrame,
    ratios: pd.DataFrame,
    *,
    max_windows: int = 3,
) -> dict[str, float]:
    """Backtest year-end targets using only information available at each cutoff."""
    errors: list[float] = []
    year_end_dates = pd.DatetimeIndex(ratios.index)
    year_end_dates = year_end_dates[year_end_dates.month == 12]
    for cutoff in sorted(year_end_dates, reverse=True):
        target_year = int(cutoff.year) + 1
        actual_rows = ratios.loc[
            (pd.DatetimeIndex(ratios.index).year == target_year)
            & (pd.DatetimeIndex(ratios.index).month == 12)
        ]
        if actual_rows.empty:
            continue
        actual_price = float(
            pd.to_numeric(
                actual_rows.iloc[-1].get(
                    "duzeltilmis_fiyat", actual_rows.iloc[-1].get("fiyat")
                ),
                errors="coerce",
            )
        )
        if not np.isfinite(actual_price) or actual_price <= 0:
            continue
        cutoff_ratios = ratios.loc[ratios.index <= cutoff]
        cutoff_quarterly = quarterly.loc[quarterly.index <= cutoff]
        if cutoff_ratios.empty or cutoff_quarterly.empty:
            continue
        shares = float(pd.to_numeric(cutoff_ratios.iloc[-1].get(SHARE_COLUMN), errors="coerce"))
        if not np.isfinite(shares) or shares <= 0:
            continue
        try:
            metadata, projection, _ = _scenario_projection(cutoff_quarterly, cutoff_ratios)
            methods = _calculate_methods(
                projection,
                cutoff_ratios,
                shares=shares,
                horizon_type=str(metadata["horizon_type"]),
            )
        except InsufficientValuationDataError:
            continue
        weights = methods["Güven Ağırlığı %"] / 100.0
        predicted = float((methods["Baz Hedef"] * weights).sum())
        if np.isfinite(predicted) and predicted > 0:
            errors.append(abs(predicted - actual_price) / actual_price)
        if len(errors) >= max_windows:
            break

    if not errors:
        return {"count": 0.0, "median_ape": np.nan, "score": 0.0}
    median_ape = float(np.median(errors))
    sample_factor = min(1.0, len(errors) / float(max_windows))
    accuracy = 1.0 / (1.0 + median_ape)
    return {
        "count": float(len(errors)),
        "median_ape": median_ape,
        "score": float(accuracy * (0.50 + 0.50 * sample_factor)),
    }


def build_rule_based_valuation(
    statements: pd.DataFrame,
    ratios: pd.DataFrame,
    *,
    valuation_date: pd.Timestamp | None = None,
) -> ValuationResult:
    if not isinstance(statements, pd.DataFrame) or statements.empty:
        raise InsufficientValuationDataError("Finansal tablo geçmişi bulunamadı.")
    if not isinstance(ratios, pd.DataFrame) or ratios.empty:
        raise InsufficientValuationDataError("Finansal oran geçmişi bulunamadı.")
    try:
        quarterly = prepare_quarterly_financial_flows(statements, FLOW_COLUMNS)
    except (KeyError, ValueError) as exc:
        raise InsufficientValuationDataError(str(exc)) from exc
    ratios = ratios.copy()
    ratios.index = pd.to_datetime(ratios.index)
    ratios = ratios.sort_index()
    latest = ratios.iloc[-1]
    shares = float(pd.to_numeric(latest.get(SHARE_COLUMN), errors="coerce"))
    current_price = float(pd.to_numeric(latest.get("duzeltilmis_fiyat", latest.get("fiyat")), errors="coerce"))
    if not np.isfinite(shares) or shares <= 0:
        raise InsufficientValuationDataError(
            "Pozitif ödenmiş sermaye/hisse sayısı bulunamadı."
        )
    if not np.isfinite(current_price) or current_price <= 0:
        raise InsufficientValuationDataError("Güncel hisse fiyatı bulunamadı.")
    metadata, projection, assumptions = _scenario_projection(quarterly, ratios)
    methods = _calculate_methods(
        projection,
        ratios,
        shares=shares,
        horizon_type=str(metadata["horizon_type"]),
    )
    weights = methods["Güven Ağırlığı %"] / 100.0
    average_target = float((methods["Baz Hedef"] * weights).sum())
    scenario_low = float((methods["Temkinli Hedef"] * weights).sum())
    scenario_high = float((methods["İyimser Hedef"] * weights).sum())
    scenario_low = min(scenario_low, average_target)
    scenario_high = max(scenario_high, average_target)

    sample_score = min(1.0, float(methods["Örnek Sayısı"].mean()) / 8.0)
    history_score = min(1.0, float(metadata["complete_years"]) / 4.0)
    driver_score = min(1.0, float(metadata["seasonality_samples"]) / 4.0)
    spread = (scenario_high - scenario_low) / max(abs(average_target), 1e-9)
    spread_score = 1.0 / (1.0 + max(0.0, spread))
    validation = _historical_validation(quarterly, ratios)
    # Güven puanının en güçlü bileşeni artık geçmiş yıl sonlarında üretilen
    # hedeflerin sonradan gerçekleşen fiyatlara karşı hatasıdır. Backtest
    # yoksa puan yüksek güven seviyesine çıkamaz.
    confidence_score = int(
        round(
            100
            * (
                0.15 * sample_score
                + 0.15 * history_score
                + 0.10 * driver_score
                + 0.25 * spread_score
                + 0.35 * validation["score"]
            )
        )
    )
    if validation["count"] == 0:
        confidence_score = min(confidence_score, 54)
    confidence_label = "Yüksek" if confidence_score >= 75 else "Orta" if confidence_score >= 55 else "Düşük"
    upside = float(relative_discount_pct(average_target, current_price))

    valuation_timestamp = pd.Timestamp(valuation_date) if valuation_date is not None else pd.Timestamp(ratios.index[-1])
    if valuation_timestamp.tzinfo is not None:
        valuation_timestamp = valuation_timestamp.tz_localize(None)
    target_date = pd.Timestamp(int(metadata["target_year"]), 12, 31)
    horizon_days = int((target_date.normalize() - valuation_timestamp.normalize()).days)
    if horizon_days <= 0:
        raise InsufficientValuationDataError(
            "Hedef değerleme tarihi geçmiş durumda; daha güncel finansal dönem gerekli."
        )
    horizon_years = max(horizon_days / 365.25, 1.0 / 12.0)
    target_period_return = average_target / current_price - 1.0
    status = (
        "iskontolu" if target_period_return >= 0.20 else
        "az değerli" if target_period_return >= 0.10 else
        "adil" if target_period_return >= -0.10 else
        "biraz yüksek" if target_period_return >= -0.20 else
        "pahalı"
    )
    summary = pd.DataFrame(
        [{
            "Değerleme Ufku": metadata["horizon_type"],
            "Hedef Yıl": int(metadata["target_year"]),
            "Açıklanan Çeyrek": int(metadata["reported_quarters"]),
            "Tahmin Edilen Çeyrek": int(metadata["forecast_quarters"]),
            "Güncel Fiyat": current_price,
            "Ağırlıklı Hedef": average_target,
            "Temkinli Hedef": scenario_low,
            "İyimser Hedef": scenario_high,
            "Hedef Potansiyeli %": upside,
            "Değerleme Vadesi (Yıl)": horizon_years,
            "Hedef Dönem Getirisi %": target_period_return * 100,
            "Backtest Örnek Sayısı": int(validation["count"]),
            "Backtest Medyan Mutlak Hata %": validation["median_ape"] * 100,
            "Veri Güveni": confidence_label,
            "Güven Puanı": confidence_score,
            "Değerleme Görünümü": status,
        }],
        index=[target_date],
    )
    return ValuationResult(
        summary=summary,
        methods=methods,
        assumptions=assumptions,
        projection=projection,
        data_quality=str(quarterly.attrs.get("data_quality_status", "—")),
    )
