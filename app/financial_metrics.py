"""Ortak finansal metrik hesaplamaları.

Hem `Sirket Analiz.ipynb` (tek şirket, dönemsel analiz) hem de
`Sektor Analizi.ipynb` (sektördeki tüm şirketler, anlık kıyaslama) bu
modülü kullanır. Böylece Piotroski F-Skoru ve DuPont ayrıştırması tek bir
yerden bakımlı tutulur ve iki notebook arasında tutarlı hesaplanır.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

# yfinance eşzamanlı (multi-thread) çağrılarda thread-safe değildir: paylaşılan
# içi önbelleği nedeniyle bir hissenin verisi başka bir hisseninkiyle karışabilir
# (örn. bir sütunun yanlışlıkla ikilenmesi). `Sektor Analizi.ipynb` sektördeki
# hisseleri ThreadPoolExecutor ile paralel çekerken, `Sirket Analiz.ipynb` de
# aynı süreç içinde ayrı bir istek thread'inde çalışabilir; bu yüzden kilit
# tüm proje için tek ve paylaşılan olmalı.
_yf_lock = threading.Lock()
_YF_CACHE_TTL_SECONDS = 300.0
_yf_cache: dict[tuple[Any, ...], tuple[float, pd.DataFrame]] = {}


def _freeze_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze_cache_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze_cache_value(item) for item in value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).isoformat()
    try:
        hash(value)
        return value
    except TypeError:
        return repr(value)


def clear_yf_cache() -> None:
    """Süreç içi fiyat önbelleğini test veya elle yenileme için temizle."""
    with _yf_lock:
        _yf_cache.clear()


def calculate_coverage_and_export_ratios(data: pd.DataFrame) -> pd.DataFrame:
    """Faiz karşılama ve ihracat oranlarını güvenli paydalarla hesapla.

    İhracat oranında mali tablolarda ayrı açıklanan yurtiçi ve yurtdışı
    satışların toplamı kullanılır. Sıfır veya eksik paydalar ``NaN`` bırakılır;
    böylece tablo ve grafiklerde yanıltıcı sonsuz değerler gösterilmez.
    """
    result = data.copy()

    if {"FAVÖK", "Finansman Giderleri"}.issubset(result.columns):
        favok = pd.to_numeric(result["FAVÖK"], errors="coerce")
        finance_cost = pd.to_numeric(
            result["Finansman Giderleri"], errors="coerce"
        ).abs().replace(0, np.nan)
        result["faiz_karsilama"] = (favok / finance_cost).replace(
            [np.inf, -np.inf], np.nan
        )
    else:
        result["faiz_karsilama"] = np.nan

    sales_columns = {"Yurtiçi Satışlar", "Yurtdışı Satışlar"}
    if sales_columns.issubset(result.columns):
        domestic_sales = pd.to_numeric(result["Yurtiçi Satışlar"], errors="coerce")
        export_sales = pd.to_numeric(result["Yurtdışı Satışlar"], errors="coerce")
        disclosed_sales = (domestic_sales + export_sales).replace(0, np.nan)
        result["ihracat_oranı_%"] = (export_sales / disclosed_sales * 100).replace(
            [np.inf, -np.inf], np.nan
        )
    else:
        result["ihracat_oranı_%"] = np.nan

    return result


def select_column_occurrence(
    df: pd.DataFrame,
    name: str,
    occurrence: int = 0,
    *,
    default: float | None = None,
) -> pd.Series:
    """Return a duplicate-labelled column by semantic name and occurrence.

    İş Yatırım repeats balance-sheet labels under current and non-current
    sections. Selecting these fields by an absolute column number makes every
    downstream valuation sensitive to upstream schema changes.
    """
    matches = [idx for idx, column in enumerate(df.columns) if column == name]
    if occurrence < 0 or occurrence >= len(matches):
        if default is not None:
            return pd.Series(default, index=df.index, name=name, dtype=float)
        raise KeyError(
            f"{name!r} kolonunun {occurrence + 1}. tekrarı bulunamadı "
            f"(bulunan tekrar sayısı: {len(matches)})."
        )
    series = df.iloc[:, matches[occurrence]].copy()
    series.name = name
    return series


def relative_discount_pct(fair_value: Any, market_value: Any):
    """Return upside/discount percentage using fair value as the numerator."""
    fair = pd.to_numeric(fair_value, errors="coerce")
    market = pd.to_numeric(market_value, errors="coerce")
    market = market.replace(0, np.nan) if isinstance(market, pd.Series) else market
    if np.isscalar(market) and market == 0:
        return np.nan
    return (fair / market - 1) * 100


def quarter_steps_to_year_end(
    last_date: str | date | datetime | pd.Timestamp,
    *,
    as_of: str | date | datetime | pd.Timestamp | None = None,
) -> int:
    """Number of quarter-start periods from ``last_date`` to year-end.

    The target is the next relevant December financial period. If the current
    year's December statement is already reached, the following year-end is
    used so a "year-end" forecast never degrades into a one-quarter forecast.
    """
    last = pd.Timestamp(last_date)
    if last.month not in (3, 6, 9, 12):
        raise ValueError(f"Beklenmeyen finansal dönem ayı: {last.month}")
    current_year = pd.Timestamp(as_of or pd.Timestamp.now()).year
    target_year = max(current_year, last.year)
    if last.month == 12 and last.year >= current_year:
        target_year = last.year + 1
    steps = (target_year - last.year) * 4 + (12 - last.month) // 3
    return int(steps)


def prepare_quarterly_financial_flows(
    statements: pd.DataFrame,
    columns: list[str] | tuple[str, ...],
    *,
    freq: str = "QS-MAR",
) -> pd.DataFrame:
    """Validate cumulative statements and convert them to true-quarter flows.

    BIST income statements are cumulative within each calendar year.  A missing
    interim statement must therefore be rejected instead of, for example,
    treating September minus March as the third-quarter result.  Leading data
    before the first available March statement is dropped because it cannot be
    de-accumulated safely.
    """
    if statements.empty:
        raise ValueError("Finansal tablo boş olamaz.")

    requested = list(dict.fromkeys(columns))
    if not requested:
        raise ValueError("En az bir finansal akım kolonu gerekli.")
    duplicate_columns = [name for name in requested if list(statements.columns).count(name) > 1]
    if duplicate_columns:
        raise ValueError(
            "Tekrarlanan finansal kolonlar var: " + ", ".join(duplicate_columns)
        )
    missing_columns = [name for name in requested if name not in statements.columns]
    if missing_columns:
        raise KeyError("Eksik finansal akım kolonları: " + ", ".join(missing_columns))

    frame = statements.loc[:, requested].copy()
    frame.index = pd.to_datetime(frame.index)
    if frame.index.has_duplicates:
        duplicate_dates = frame.index[frame.index.duplicated()].strftime("%Y-%m").tolist()
        raise ValueError("Tekrarlanan finansal dönemler var: " + ", ".join(duplicate_dates))
    frame = frame.sort_index()
    invalid_dates = frame.index[~frame.index.month.isin((3, 6, 9, 12))]
    if len(invalid_dates):
        labels = invalid_dates.strftime("%Y-%m").tolist()
        raise ValueError("Beklenmeyen finansal dönem ayları var: " + ", ".join(labels))

    warnings: list[str] = []
    march_positions = np.flatnonzero(frame.index.month == 3)
    if not len(march_positions):
        raise ValueError("Gerçek çeyrek hesabı için başlangıç Mart dönemi bulunamadı.")
    first_march = int(march_positions[0])
    if first_march:
        dropped = frame.index[:first_march]
        warnings.append(
            "İlk Mart dönemi öncesindeki "
            f"{len(dropped)} dönem güvenli ayrıştırılamadığı için kullanılmadı."
        )
        frame = frame.iloc[first_march:].copy()

    expected = pd.date_range(frame.index[0], frame.index[-1], freq=freq)
    missing_periods = expected.difference(frame.index)
    unexpected_periods = frame.index.difference(expected)
    if len(missing_periods) or len(unexpected_periods):
        details: list[str] = []
        if len(missing_periods):
            details.append("eksik: " + ", ".join(missing_periods.strftime("%Y-%m")))
        if len(unexpected_periods):
            details.append("beklenmeyen: " + ", ".join(unexpected_periods.strftime("%Y-%m")))
        raise ValueError("Finansal dönemler ardışık değil (" + "; ".join(details) + ").")

    frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    missing_cells = frame.isna()
    if missing_cells.any().any():
        labels: list[str] = []
        for date, column in zip(*np.where(missing_cells.to_numpy())):
            labels.append(f"{frame.index[date]:%Y-%m} / {frame.columns[column]}")
        preview = ", ".join(labels[:6])
        suffix = " …" if len(labels) > 6 else ""
        raise ValueError("Finansal akımlarda eksik/sayısal olmayan değerler var: " + preview + suffix)

    quarterly = frame.copy()
    non_march = quarterly.index.month != 3
    quarterly.loc[non_march, requested] = frame.groupby(frame.index.year)[requested].diff().loc[
        non_march
    ]

    # Flag extreme year-over-year changes without silently deleting them.  The
    # warning helps identify restatements or presentation-basis changes while
    # leaving the final judgement visible to the user.
    for column in requested:
        annual_change = quarterly[column].diff(4).dropna()
        if len(annual_change) < 8:
            continue
        median = float(annual_change.median())
        mad = float((annual_change - median).abs().median())
        scale = max(1.4826 * mad, float(annual_change.abs().median()) * 0.05, 1e-9)
        extreme = annual_change.index[((annual_change - median).abs() / scale) > 8.0]
        if len(extreme):
            warnings.append(
                f"{column} için olağandışı yıllık değişim görülen dönemler: "
                + ", ".join(extreme.strftime("%Y-%m"))
                + ". Düzeltme/enflasyon muhasebesi etkisi kontrol edilmeli."
            )

    quarterly.attrs["data_quality_warnings"] = warnings
    quarterly.attrs["data_quality_status"] = (
        "; ".join(warnings)
        if warnings
        else "Dönem sürekliliği ve zorunlu finansal değer kontrolleri geçti."
    )
    return quarterly


def _joint_cv_interval_radius(cv_predictions: pd.DataFrame, coverage: float) -> float:
    """Finite-sample conformal radius for the sum of a forecast horizon."""
    required = {"actual", "prediction", "fold"}
    if cv_predictions.empty or not required.issubset(cv_predictions.columns):
        return np.nan
    path_errors: list[float] = []
    for _, group in cv_predictions.groupby("fold"):
        errors = (
            pd.to_numeric(group["actual"], errors="coerce")
            - pd.to_numeric(group["prediction"], errors="coerce")
        ).dropna()
        if len(errors):
            path_errors.append(float(errors.sum()))
    absolute = np.abs(np.asarray(path_errors, dtype=float))
    absolute = absolute[np.isfinite(absolute)]
    if not len(absolute):
        return np.nan
    quantile = min(1.0, np.ceil((len(absolute) + 1) * coverage) / len(absolute))
    return float(np.quantile(absolute, quantile, method="higher"))


def reconcile_year_end_flow(
    actual_quarters: pd.Series,
    forecast: pd.DataFrame,
    column: str,
    *,
    cv_predictions: pd.DataFrame | None = None,
) -> dict[str, float | int | str]:
    """Combine reported quarters with forecasts for a calendar-year total.

    Income-statement observations are flows.  A year-end sales/profit/EBITDA
    estimate therefore has to be the sum of the quarters already reported in
    the target year and only the still-missing quarterly forecasts.  Taking
    the last forecast row would incorrectly treat one quarter as a full year.
    """
    actual = pd.to_numeric(actual_quarters, errors="coerce").dropna().copy()
    actual.index = pd.to_datetime(actual.index)
    projected = forecast.copy()
    projected.index = pd.to_datetime(projected.index)
    projected = projected.sort_index()
    if projected.empty:
        raise ValueError("Yıl sonu mutabakatı için en az bir tahmin dönemi gerekli.")

    target_year = int(projected.index[-1].year)
    reported = actual.loc[actual.index.year == target_year]
    missing = projected.loc[projected.index.year == target_year]
    point_col = f"{column} Tahmin"
    required = [
        point_col,
        f"{column} Alt %80",
        f"{column} Üst %80",
        f"{column} Alt %95",
        f"{column} Üst %95",
    ]
    absent = [name for name in required if name not in missing.columns]
    if absent:
        raise KeyError("Yıl sonu mutabakatında eksik kolonlar: " + ", ".join(absent))
    if missing[required].isna().any().any():
        raise ValueError("Yıl sonu mutabakatındaki tahmin aralıkları eksik değer içeriyor.")

    known_total = float(reported.sum())
    result: dict[str, float | int | str] = {
        "target_year": target_year,
        "reported_quarters": int(len(reported)),
        "forecast_quarters": int(len(missing)),
        "reported_total": known_total,
        "future_total": float(missing[point_col].sum()),
        "point": known_total + float(missing[point_col].sum()),
    }
    nonnegative = bool((reported >= 0).all() and (missing[point_col] >= 0).all())
    used_joint_paths = False
    for coverage in (80, 95):
        radius = (
            _joint_cv_interval_radius(cv_predictions, coverage / 100)
            if isinstance(cv_predictions, pd.DataFrame)
            else np.nan
        )
        if np.isfinite(radius):
            used_joint_paths = True
            lower = float(result["point"]) - float(radius)
            upper = float(result["point"]) + float(radius)
            result[f"lower_{coverage}"] = max(0.0, lower) if nonnegative else lower
            result[f"upper_{coverage}"] = upper
        else:
            result[f"lower_{coverage}"] = known_total + float(
                missing[f"{column} Alt %{coverage}"].sum()
            )
            result[f"upper_{coverage}"] = known_total + float(
                missing[f"{column} Üst %{coverage}"].sum()
            )
    result["interval_method"] = (
        "joint_cv_path_conformal" if used_joint_paths else "summed_quarter_bounds_fallback"
    )
    return result


def yf_download_safe(*args, retries: int = 3, backoff: float = 2.0, **kwargs):
    """`yfinance.download`'ı bir kilit altında (thread-safety için) ve yeniden
    deneme ile çağırır. Boş sonuç veya ağ hatası durumunda kısa bir bekleme ile
    tekrar dener; tüm denemeler tükenirse en son (muhtemelen boş) sonucu
    döndürür ya da son hatayı fırlatır.
    """
    cache_key = (
        _freeze_cache_value(args),
        _freeze_cache_value(kwargs),
    )
    last_err = None
    result = None
    for attempt in range(retries):
        try:
            with _yf_lock:
                cached = _yf_cache.get(cache_key)
                if cached is not None:
                    created_at, cached_frame = cached
                    if time.monotonic() - created_at <= _YF_CACHE_TTL_SECONDS:
                        return cached_frame.copy(deep=True)
                    _yf_cache.pop(cache_key, None)
                result = yf.download(*args, **kwargs)
                if result is not None and not result.empty:
                    # Savunma amaçlı: aynı isimli sütun ikilenmesi olursa
                    # (yfinance'in eşzamanlı çağrılarda görülen önbellek sorunu)
                    # ilk sütunu koru, diğerlerini at.
                    result = result.loc[:, ~result.columns.duplicated()]
                    _yf_cache[cache_key] = (time.monotonic(), result.copy(deep=True))
                    return result.copy(deep=True)
        except Exception as e:
            last_err = e
        if attempt < retries - 1:
            time.sleep(backoff * (attempt + 1))
    if last_err is not None:
        raise last_err
    return result


def split_adjusted_paid_capital(
    paid_capital: pd.Series,
    stock_splits: pd.Series | None,
    *,
    ratio_tolerance: float = 0.25,
) -> tuple[pd.Series, pd.Series]:
    """Normalize historical paid capital to Yahoo's split-adjusted price basis.

    Yahoo's ``Close`` history is back-adjusted for stock splits, but not for
    cash dividends. Financial statements, on the other hand, usually retain
    the paid capital that was legally valid on each reporting date. For a
    consistent market-cap/EPS basis, pre-split capital is multiplied by the
    future split ratio.

    Some data providers retrospectively restate paid capital. If the first
    post-split report is essentially unchanged from the last pre-split report,
    the function detects that the series is already restated and avoids a
    second adjustment.
    """
    capital = pd.to_numeric(paid_capital, errors="coerce").copy()
    capital.index = pd.DatetimeIndex(pd.to_datetime(capital.index)).tz_localize(None)
    capital = capital.sort_index()
    factors = pd.Series(1.0, index=capital.index, dtype=float)
    if stock_splits is None or len(stock_splits) == 0:
        return capital, factors

    splits = pd.to_numeric(stock_splits, errors="coerce").dropna()
    split_index = pd.DatetimeIndex(pd.to_datetime(splits.index))
    if split_index.tz is not None:
        split_index = split_index.tz_localize(None)
    splits.index = split_index
    splits = splits.loc[(splits > 0) & (~np.isclose(splits, 1.0))].sort_index()

    raw = capital.copy()
    for split_date, split_ratio_value in splits.items():
        split_ratio = float(split_ratio_value)
        # Bilanço sermayesi, borsadaki bölünme gününden önceki bir finansal
        # tabloda yeni tutarı gösterebilir (LINK: 41 katlık artış 2025/12
        # bilançoda, Yahoo olayı 16 Mart 2026). Önce sermaye serisindeki split
        # oranına uyan gerçek geçiş dönemini ara ve yalnız daha eski dönemleri
        # düzelt.
        capital_ratios = raw / raw.shift(1).replace(0, np.nan)
        transition_window = capital_ratios.loc[
            (capital_ratios.index >= split_date - pd.Timedelta(days=180))
            & (capital_ratios.index <= split_date + pd.Timedelta(days=180))
        ].dropna()
        matching_transitions = transition_window.loc[
            np.isclose(
                transition_window,
                split_ratio,
                rtol=ratio_tolerance,
                atol=0.02,
            )
        ]
        if not matching_transitions.empty:
            distance = (np.log(matching_transitions.abs()) - np.log(abs(split_ratio))).abs()
            effective_date = pd.Timestamp(distance.idxmin())
            factors.loc[factors.index < effective_date] *= split_ratio
            continue

        pre = raw.loc[raw.index < split_date].dropna()
        post = raw.loc[raw.index >= split_date].dropna()
        if pre.empty:
            continue

        should_adjust = post.empty
        if not post.empty:
            observed_ratio = float(post.iloc[0] / pre.iloc[-1]) if pre.iloc[-1] != 0 else np.nan
            split_is_visible_in_statements = (
                np.isfinite(observed_ratio)
                and np.isclose(observed_ratio, split_ratio, rtol=ratio_tolerance, atol=0.02)
            )
            statements_are_already_restated = (
                np.isfinite(observed_ratio)
                and np.isclose(observed_ratio, 1.0, rtol=0.10, atol=0.02)
            )
            should_adjust = split_is_visible_in_statements and not statements_are_already_restated

        if should_adjust:
            mask = capital.index < split_date
            factors.loc[mask] *= split_ratio

    return capital * factors, factors


def prepare_split_consistent_prices(prices_raw: pd.DataFrame) -> pd.DataFrame:
    """Return prices on one split basis, without double-adjusting Yahoo data.

    Depending on the requested date window, Yahoo may return pre-split ``Close``
    observations either on their original basis or already back-adjusted. The
    discontinuity around each ``Stock Splits`` event is therefore inspected:
    only when pre/post Close is approximately the announced split ratio are
    observations before that event divided by the ratio.
    """
    if not isinstance(prices_raw, pd.DataFrame) or prices_raw.empty:
        return pd.DataFrame(
            columns=[
                "fiyat",
                "duzeltilmis_fiyat",
                "toplam_getiri_fiyati",
                "fiyat_duzeltme_katsayisi",
            ],
            dtype=float,
        )
    if "Close" not in prices_raw.columns:
        raise ValueError("Bölünmeye göre düzeltilmiş fiyat için Yahoo Close kolonu gerekli.")

    frame = prices_raw.copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index))
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    frame = frame.sort_index()
    close = pd.to_numeric(frame["Close"], errors="coerce")
    # Yahoo gün içinde henüz kapanış oluşmadan hacim/açılış içeren, fakat Close
    # değeri boş olan geçici bir son satır döndürebilir. Bu satır güncel fiyat
    # diye seçilirse değerleme tümüyle devre dışı kalır; yalnız gerçekleşmiş
    # pozitif kapanışları fiyat serisine al.
    valid_close = close.notna() & np.isfinite(close) & (close > 0)
    frame = frame.loc[valid_close].copy()
    close = close.loc[valid_close]
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "fiyat",
                "duzeltilmis_fiyat",
                "toplam_getiri_fiyati",
                "fiyat_duzeltme_katsayisi",
            ],
            dtype=float,
        )
    total_return = (
        pd.to_numeric(frame["Adj Close"], errors="coerce")
        if "Adj Close" in frame.columns
        else close.copy()
    )
    total_return = total_return.where(np.isfinite(total_return), close)
    factors = pd.Series(1.0, index=frame.index, dtype=float)
    if "Stock Splits" in frame.columns:
        splits = pd.to_numeric(frame["Stock Splits"], errors="coerce").fillna(0.0)
        splits = splits.loc[(splits > 0) & (~np.isclose(splits, 1.0))]
        for split_date, split_ratio_value in splits.items():
            split_ratio = float(split_ratio_value)
            # Yahoo bazen fiyat bazını resmi Stock Splits satırından birkaç iş
            # günü önce değiştirir (CCOLA: olay 13 Ağustos, fiyat kopuşu 1
            # Ağustos 2024). Bu yüzden yalnız olay gününe değil çevresindeki
            # 45 günlük penceredeki split oranına uyan en büyük kopuşa bakılır.
            observed_ratios = close.shift(1) / close.replace(0, np.nan)
            window = observed_ratios.loc[
                (observed_ratios.index >= split_date - pd.Timedelta(days=45))
                & (observed_ratios.index <= split_date + pd.Timedelta(days=5))
            ].dropna()
            matching = window.loc[
                np.isclose(window, split_ratio, rtol=0.35, atol=0.10)
            ]
            if matching.empty:
                continue
            distance = (np.log(matching.abs()) - np.log(abs(split_ratio))).abs()
            jump_date = pd.Timestamp(distance.idxmin())
            factors.loc[factors.index < jump_date] *= split_ratio

    split_adjusted_close = close / factors
    split_adjusted_total_return = total_return / factors
    return pd.DataFrame(
        {
            "fiyat": split_adjusted_close,
            # Adj Close ayrıca temettüleri içerdiği için değerleme çarpanında
            # kullanılmaz; yalnızca toplam getiri hesabında tutulur.
            "duzeltilmis_fiyat": split_adjusted_close,
            "toplam_getiri_fiyati": split_adjusted_total_return,
            "fiyat_duzeltme_katsayisi": factors,
        },
        index=frame.index,
    )


def _col_or_default(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series(np.nan, index=df.index)


def dupont_analizi_donemsel(df: pd.DataFrame) -> pd.DataFrame:
    """3 adımlı DuPont ayrıştırması (dönemsel zaman serisi):

        ROE = Net Kâr Marjı × Aktif Devir Hızı × Özkaynak Çarpanı

    `df` içinde `net_kar_marjı_%`, `aktif_devir_hizi`, `ortalama_toplam_aktifler`,
    `ortalama_toplam_ozkaynak` zaten hesaplanmışsa (örn. `oran_rasyo_hesaplama`
    çıktısı) bunlar birebir kullanılır — böylece skor kartındaki ROA/ROE ile
    aynı tabana oturur. Yoksa (örn. sektör analizi akışı) ham kalemlerden
    (Satış Gelirleri, Ana Ortaklık Payları, TOPLAM VARLIKLAR,
    Ana Ortaklığa Ait Özkaynaklar) kendisi hesaplar. Eksik sütun olduğunda
    ilgili bileşen NaN döner, hata fırlatılmaz.
    """
    data = df.sort_index()

    satis = _col_or_default(data, "Satış Gelirleri")
    net_kar = _col_or_default(data, "Ana Ortaklık Payları")
    varlik = _col_or_default(data, "TOPLAM VARLIKLAR")
    ozkaynak = _col_or_default(data, "  Ana Ortaklığa Ait Özkaynaklar")

    ort_varlik = (
        data["ortalama_toplam_aktifler"]
        if "ortalama_toplam_aktifler" in data.columns
        else (varlik + varlik.shift(1)) / 2
    )
    ort_ozkaynak = (
        data["ortalama_toplam_ozkaynak"]
        if "ortalama_toplam_ozkaynak" in data.columns
        else (ozkaynak + ozkaynak.shift(1)) / 2
    )

    net_kar_marji = (
        data["net_kar_marjı_%"]
        if "net_kar_marjı_%" in data.columns
        else (net_kar / satis.replace(0, np.nan)) * 100
    )
    aktif_devir_hizi = (
        data["aktif_devir_hizi"]
        if "aktif_devir_hizi" in data.columns
        else satis / ort_varlik.replace(0, np.nan)
    )
    ozkaynak_carpani = ort_varlik / ort_ozkaynak.replace(0, np.nan)
    roe_dupont = (net_kar_marji / 100) * aktif_devir_hizi * ozkaynak_carpani * 100

    return pd.DataFrame(
        {
            "net_kar_marjı_%": net_kar_marji,
            "aktif_devir_hizi": aktif_devir_hizi,
            "ozkaynak_carpani": ozkaynak_carpani,
            "roe_dupont_%": roe_dupont,
        },
        index=data.index,
    )


def piotroski_f_skoru(df: pd.DataFrame) -> dict:
    """
    Piotroski F-Skoru (0-9): kârlılık, kaldıraç/likidite/fon kaynağı ve faaliyet
    verimliliği eksenlerinde yıllık iyileşme/kötüleşme sinyallerini 9 ikili (0/1)
    kritere dönüştürür. Karşılaştırma, TTM (son 12 ay) verisiyle 4 dönem (1 yıl)
    öncesindeki TTM verisi arasında yapılır.

    Sabit eşikler yerine şirketin KENDİ geçmişine göre (Δ pozitif mi/negatif mi)
    değerlendirme yapıldığı için sektörden bağımsız çalışır. Bir kriter için
    gereken veri mevcut değilse (örn. bazı sektörlerde bulunmayan kalemler),
    o kriter puanlamaya dahil edilmez; toplam skor yalnızca hesaplanabilen
    kriterler üzerinden raporlanır (örn. "6/7" gibi).
    """
    data = df.copy().sort_index()
    if len(data) < 5:
        return {
            "score": np.nan,
            "max_score": np.nan,
            "eksik_kriter": np.nan,
            "criteria": pd.DataFrame(columns=["Kategori", "Kriter", "Sonuç", "Detay"]),
        }

    last = data.iloc[-1]
    prev = data.iloc[-5]  # 4 dönem (1 yıl) önceki TTM

    def g(row, col):
        if col not in data.columns:
            return np.nan
        val = row[col]
        try:
            val = float(val)
        except (TypeError, ValueError):
            return np.nan
        return val if np.isfinite(val) else np.nan

    puanlar = []
    rows = []

    def kriter(kosul, baslik, kategori, detay=""):
        if pd.isna(kosul):
            puan = np.nan
            sonuc = "Veri yok"
        else:
            puan = 1 if bool(kosul) else 0
            sonuc = "✓ Geçti" if puan == 1 else "✗ Kaldı"
        puanlar.append(puan)
        rows.append({"Kategori": kategori, "Kriter": baslik, "Sonuç": sonuc, "Detay": detay})

    # ------------------------------------------------
    # A) KÂRLILIK (4 kriter)
    # ------------------------------------------------
    roa_last, roa_prev = g(last, "aktif_karliligi_%"), g(prev, "aktif_karliligi_%")
    cfo_last = g(last, " İşletme Faaliyetlerinden Kaynaklanan Net Nakit")
    net_income_last = g(last, "Ana Ortaklık Payları")

    kriter(
        roa_last > 0 if pd.notna(roa_last) else np.nan,
        "Pozitif Aktif Karlılığı (ROA > 0)", "Kârlılık",
        f"ROA: %{roa_last:.2f}" if pd.notna(roa_last) else "",
    )
    kriter(
        cfo_last > 0 if pd.notna(cfo_last) else np.nan,
        "Pozitif Faaliyet Nakit Akışı (CFO > 0)", "Kârlılık",
        f"CFO: {cfo_last:,.0f}" if pd.notna(cfo_last) else "",
    )
    delta_roa = (roa_last - roa_prev) if pd.notna(roa_last) and pd.notna(roa_prev) else np.nan
    kriter(
        delta_roa > 0 if pd.notna(delta_roa) else np.nan,
        "ROA Yıllık Artış", "Kârlılık",
        f"Δ ROA: {delta_roa:+.2f} puan" if pd.notna(delta_roa) else "",
    )
    accrual = (cfo_last > net_income_last) if pd.notna(cfo_last) and pd.notna(net_income_last) else np.nan
    kriter(
        accrual,
        "Nakit Akışı Net Kâr'ı Aşıyor (Kazanç Kalitesi)", "Kârlılık",
        f"CFO {cfo_last:,.0f} vs Net Kâr {net_income_last:,.0f}" if pd.notna(accrual) else "",
    )

    # ------------------------------------------------
    # B) KALDIRAÇ / LİKİDİTE / FON KAYNAĞI (3 kriter)
    # ------------------------------------------------
    def uzun_vade_kaldirac(row):
        uzun_vade = g(row, "Uzun Vadeli Yükümlülükler")
        varlik = g(row, "TOPLAM VARLIKLAR")
        if pd.isna(uzun_vade) or pd.isna(varlik) or varlik == 0:
            return np.nan
        return uzun_vade / varlik

    lev_last, lev_prev = uzun_vade_kaldirac(last), uzun_vade_kaldirac(prev)
    delta_lev = (lev_last - lev_prev) if pd.notna(lev_last) and pd.notna(lev_prev) else np.nan
    kriter(
        delta_lev < 0 if pd.notna(delta_lev) else np.nan,
        "Uzun Vadeli Kaldıraç Azalışı", "Kaldıraç/Likidite",
        f"Δ Kaldıraç: {delta_lev:+.2%}" if pd.notna(delta_lev) else "",
    )
    cari_last, cari_prev = g(last, "cari_oran"), g(prev, "cari_oran")
    delta_cari = (cari_last - cari_prev) if pd.notna(cari_last) and pd.notna(cari_prev) else np.nan
    kriter(
        delta_cari > 0 if pd.notna(delta_cari) else np.nan,
        "Cari Oran İyileşmesi", "Kaldıraç/Likidite",
        f"Δ Cari Oran: {delta_cari:+.2f}" if pd.notna(delta_cari) else "",
    )
    sermaye_artis = g(last, "Sermaye Artırımı")
    kriter(
        sermaye_artis <= 0 if pd.notna(sermaye_artis) else np.nan,
        "Yeni Pay İhracı Yok (Sulanma Yok)", "Kaldıraç/Likidite",
        f"Sermaye Artırımı (nakit girişi): {sermaye_artis:,.0f}" if pd.notna(sermaye_artis) else "",
    )

    # ------------------------------------------------
    # C) FAALİYET VERİMLİLİĞİ (2 kriter)
    # ------------------------------------------------
    brut_last, brut_prev = g(last, "brüt_kar_marjı_%"), g(prev, "brüt_kar_marjı_%")
    delta_brut = (brut_last - brut_prev) if pd.notna(brut_last) and pd.notna(brut_prev) else np.nan
    kriter(
        delta_brut > 0 if pd.notna(delta_brut) else np.nan,
        "Brüt Kâr Marjı Artışı", "Faaliyet Verimliliği",
        f"Δ Brüt Marj: {delta_brut:+.2f} puan" if pd.notna(delta_brut) else "",
    )
    devir_last, devir_prev = g(last, "aktif_devir_hizi"), g(prev, "aktif_devir_hizi")
    delta_devir = (devir_last - devir_prev) if pd.notna(devir_last) and pd.notna(devir_prev) else np.nan
    kriter(
        delta_devir > 0 if pd.notna(delta_devir) else np.nan,
        "Aktif Devir Hızı Artışı", "Faaliyet Verimliliği",
        f"Δ Aktif Devir Hızı: {delta_devir:+.2f}" if pd.notna(delta_devir) else "",
    )

    gecerli_puanlar = [p for p in puanlar if pd.notna(p)]
    score = int(sum(gecerli_puanlar)) if gecerli_puanlar else np.nan
    max_score = len(gecerli_puanlar) if gecerli_puanlar else np.nan
    eksik_kriter = len(puanlar) - len(gecerli_puanlar)

    criteria_df = pd.DataFrame(rows)[["Kategori", "Kriter", "Sonuç", "Detay"]]

    print(
        f"\nPiotroski F-Skoru: {score}/{max_score}"
        + (f" ({eksik_kriter} kriter veri yetersizliğinden hesaplanamadı)" if eksik_kriter else "")
        + "\n"
    )

    return {
        "score": score,
        "max_score": max_score,
        "eksik_kriter": eksik_kriter,
        "criteria": criteria_df,
    }
