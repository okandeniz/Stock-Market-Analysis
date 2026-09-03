from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .notebook_runtime import NotebookRuntime, RenderedOutput
from .plotly_theme import ACCENT, ACCENT_H, DOWN_COLOR, TEXT_COLOR, apply_theme, format_tr_number
from .table_format import dataframe_to_html
from .valuation import (
    INSUFFICIENT_VALUATION_MESSAGE,
    InsufficientValuationDataError,
    ValuationResult,
    build_rule_based_valuation,
)


def _valuation_kpi_summary(df: pd.DataFrame | None) -> dict[str, Any] | None:
    """Return the decision-oriented forward valuation fields for KPI cards."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    row = df.iloc[-1]

    def finite_value(column: str) -> float | None:
        try:
            value = float(row.get(column, np.nan))
        except (TypeError, ValueError):
            return None
        return value if np.isfinite(value) else None

    def first_finite(*columns: str) -> float | None:
        for column in columns:
            value = finite_value(column)
            if value is not None:
                return value
        return None

    status = row.get("Değerleme Görünümü", row.get("durum", "belirsiz"))
    if pd.isna(status) or not str(status).strip():
        status = "belirsiz"

    period_value = df.index[-1]
    if isinstance(period_value, (pd.Timestamp, pd.Period)):
        period_label = f"{period_value.year}-{period_value.month:02d}"
    else:
        period_label = str(period_value)

    return {
        "period": period_label,
        "horizon": str(row.get("Değerleme Ufku", "Yıl sonu değerlemesi")),
        "current_price": first_finite("Güncel Fiyat", "fiyat"),
        "average_target": first_finite("Ağırlıklı Hedef", "Ortalama Tahmin"),
        "upside_pct": first_finite("Hedef Potansiyeli %", "iskonto_%"),
        "target_period_return_pct": first_finite(
            "Hedef Dönem Getirisi %",
            "Hedef Potansiyeli %",
            "iskonto_%",
        ),
        "scenario_low": finite_value("Temkinli Hedef"),
        "scenario_high": finite_value("İyimser Hedef"),
        "confidence": str(row.get("Veri Güveni", "—")),
        "confidence_score": finite_value("Güven Puanı"),
        "status": str(status),
    }


def _neutral_valuation_position(status: Any) -> str:
    """Translate internal valuation bands into non-directive presentation copy."""
    normalized = str(status or "").strip().casefold()
    if normalized in {"iskontolu", "az değerli"}:
        return "Piyasa fiyatı model ortalamasının altında"
    if normalized in {"pahalı", "biraz yüksek"}:
        return "Piyasa fiyatı model ortalamasının üzerinde"
    if normalized == "adil":
        return "Piyasa fiyatı model ortalamasına yakın"
    return "Model konumu hesaplanamadı"


def _valuation_summary_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Return a user-facing copy of the valuation summary with neutral labels."""
    display = df.copy()
    if "Değerleme Görünümü" in display.columns:
        display["Piyasa Fiyatının Model Aralığındaki Konumu"] = display[
            "Değerleme Görünümü"
        ].map(_neutral_valuation_position)
    if "Hedef Dönem Getirisi %" in display.columns:
        display["Piyasa Fiyatına Göre Model Farkı (%)"] = display[
            "Hedef Dönem Getirisi %"
        ]
    display = display.rename(
        columns={
            "Ağırlıklı Hedef": "Model Değerleme Ortalaması",
            "Temkinli Hedef": "Temkinli Senaryo Değeri",
            "İyimser Hedef": "İyimser Senaryo Değeri",
            "Hedef Potansiyeli %": "Model Fiyat Farkı (%)",
            "Veri Güveni": "Veri ve Model Yeterliliği",
            "Güven Puanı": "Yeterlilik Puanı",
        }
    )
    return display.drop(
        columns=["Hedef Dönem Getirisi %", "Değerleme Görünümü"],
        errors="ignore",
    )


def _valuation_methods_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Use valuation terminology without changing the calculation schema."""
    return df.rename(
        columns={
            "Temkinli Hedef": "Temkinli Senaryo Değeri",
            "Baz Hedef": "Baz Senaryo Değeri",
            "İyimser Hedef": "İyimser Senaryo Değeri",
        }
    )


def _report_metadata(
    hisse: str,
    financials: pd.DataFrame,
    *,
    valuation_created: bool,
) -> dict[str, Any]:
    """Create traceable, user-visible report metadata for each analysis run."""
    created_at = datetime.now(ZoneInfo("Europe/Istanbul"))
    period = "—"
    if isinstance(financials, pd.DataFrame) and not financials.empty:
        parsed = pd.to_datetime(financials.index, errors="coerce")
        valid = parsed[~pd.isna(parsed)]
        if len(valid):
            latest = pd.Timestamp(valid[-1])
            period = f"{latest.year}/{latest.month}"
    return {
        "report_id": f"FM-{hisse}-{created_at:%Y%m%d-%H%M%S}",
        "generated_at": created_at.isoformat(timespec="seconds"),
        "financial_period": period,
        "financial_source": "İş Yatırım",
        "price_source": "Yahoo Finance",
        "price_time_note": (
            "Fiyat, analiz çalıştırılırken veri kaynağındaki son erişilebilir "
            "gözlemden alınır; gerçek zamanlı fiyat garantisi verilmez."
        ),
        "methodology_version": "FM-Değerleme v2.0",
        "valuation_created": bool(valuation_created),
        "update_policy": (
            "Rapor, kullanıcı analizi yeniden çalıştırdığında erişilebilen finansal "
            "tablolar ve fiyat verileriyle yeniden oluşturulur."
        ),
        "correction_policy": (
            "Veri veya hesaplama hatası tespit edilirse sonuç yeni rapor kimliği ve "
            "güncel metodoloji sürümüyle yeniden yayımlanır."
        ),
    }


def _build_vertical_balance_analysis(raw_financials: pd.DataFrame) -> pd.DataFrame:
    """Compare the latest balance sheet with the same quarter one year earlier.

    Each balance-sheet line is shown both as an amount and as a share of total
    assets. The calculation mirrors the ``Dikey Analiz`` workbook: line item /
    ``TOPLAM VARLIKLAR`` for each of the two comparable reporting dates.
    """
    if not isinstance(raw_financials, pd.DataFrame) or raw_financials.empty:
        return pd.DataFrame()

    frame = raw_financials.copy()
    parsed_index = pd.to_datetime(frame.index, errors="coerce")
    valid_positions = np.flatnonzero(~pd.isna(parsed_index))
    if not len(valid_positions):
        return pd.DataFrame()

    frame = frame.iloc[valid_positions].copy()
    frame.index = pd.DatetimeIndex(parsed_index[valid_positions])
    frame = frame.sort_index()
    latest_period = pd.Timestamp(frame.index[-1])
    comparison_mask = (
        (frame.index.year == latest_period.year - 1)
        & (frame.index.month == latest_period.month)
    )
    if not comparison_mask.any():
        return pd.DataFrame()

    comparison_row = frame.loc[comparison_mask].iloc[-1]
    latest_row = frame.iloc[-1]
    columns = list(frame.columns)
    try:
        balance_start = columns.index("Dönen Varlıklar")
        income_start = columns.index("Satış Gelirleri")
    except ValueError:
        return pd.DataFrame()
    if income_start <= balance_start:
        return pd.DataFrame()

    balance_columns = columns[balance_start:income_start]
    try:
        total_assets_position = balance_columns.index("TOPLAM VARLIKLAR")
    except ValueError:
        return pd.DataFrame()

    # Positional selection is intentional: the source data can contain duplicate
    # labels such as short- and long-term "Finansal Borçlar".
    previous_values = pd.to_numeric(
        comparison_row.iloc[balance_start:income_start], errors="coerce"
    ).replace([np.inf, -np.inf], np.nan)
    current_values = pd.to_numeric(
        latest_row.iloc[balance_start:income_start], errors="coerce"
    ).replace([np.inf, -np.inf], np.nan)
    previous_total_assets = previous_values.iloc[total_assets_position]
    current_total_assets = current_values.iloc[total_assets_position]

    def vertical_share(values: pd.Series, total_assets: Any) -> pd.Series:
        try:
            denominator = float(total_assets)
        except (TypeError, ValueError):
            denominator = float("nan")
        if not np.isfinite(denominator) or denominator == 0:
            return pd.Series(np.nan, index=values.index, dtype=float)
        shares = values.astype(float).div(denominator).mul(100)
        # The reference workbook leaves zero-weight rows blank.
        return shares.mask(values.eq(0))

    def period_label(period: pd.Timestamp) -> str:
        return f"{period.year}/{period.month}"

    def display_label(value: Any) -> str:
        text = str(value)
        indentation = len(text) - len(text.lstrip(" "))
        return f"{'\u2003' * (indentation // 2)}{text.lstrip()}"

    comparison_period = pd.Timestamp(frame.loc[comparison_mask].index[-1])
    previous_label = period_label(comparison_period)
    current_label = period_label(latest_period)
    result = pd.DataFrame(
        {
            f"{previous_label} Tutar": previous_values.to_numpy(),
            f"{previous_label} Pay (%)": vertical_share(
                previous_values, previous_total_assets
            ).to_numpy(),
            f"{current_label} Tutar": current_values.to_numpy(),
            f"{current_label} Pay (%)": vertical_share(
                current_values, current_total_assets
            ).to_numpy(),
            "Değişim (%)": (
                current_values.sub(previous_values)
                .div(previous_values.abs().replace(0, np.nan))
                .mul(100)
            ).to_numpy(),
        },
        index=pd.Index([display_label(column) for column in balance_columns], name="Kalem"),
    )
    return result


def _build_vertical_income_analysis(raw_financials: pd.DataFrame) -> pd.DataFrame:
    """Compare cumulative income statements for the same quarter year over year."""
    if not isinstance(raw_financials, pd.DataFrame) or raw_financials.empty:
        return pd.DataFrame()

    frame = raw_financials.copy()
    parsed_index = pd.to_datetime(frame.index, errors="coerce")
    valid_positions = np.flatnonzero(~pd.isna(parsed_index))
    if not len(valid_positions):
        return pd.DataFrame()

    frame = frame.iloc[valid_positions].copy()
    frame.index = pd.DatetimeIndex(parsed_index[valid_positions])
    frame = frame.sort_index()
    latest_period = pd.Timestamp(frame.index[-1])
    comparison_mask = (
        (frame.index.year == latest_period.year - 1)
        & (frame.index.month == latest_period.month)
    )
    if not comparison_mask.any():
        return pd.DataFrame()

    columns = list(frame.columns)
    try:
        income_start = columns.index("Satış Gelirleri")
        income_end = len(columns) - 1 - columns[::-1].index("Ana Ortaklık Payları")
    except ValueError:
        return pd.DataFrame()
    if income_end < income_start:
        return pd.DataFrame()

    income_columns = columns[income_start : income_end + 1]
    previous_row = frame.loc[comparison_mask].iloc[-1]
    current_row = frame.iloc[-1]
    previous_values = pd.to_numeric(
        previous_row.iloc[income_start : income_end + 1], errors="coerce"
    ).replace([np.inf, -np.inf], np.nan)
    current_values = pd.to_numeric(
        current_row.iloc[income_start : income_end + 1], errors="coerce"
    ).replace([np.inf, -np.inf], np.nan)
    previous_sales = previous_values.iloc[0]
    current_sales = current_values.iloc[0]

    def sales_share(values: pd.Series, sales: Any) -> pd.Series:
        try:
            denominator = float(sales)
        except (TypeError, ValueError):
            denominator = float("nan")
        if not np.isfinite(denominator) or denominator == 0:
            return pd.Series(np.nan, index=values.index, dtype=float)
        return values.astype(float).div(denominator).mul(100).mask(values.eq(0))

    def period_label(period: pd.Timestamp) -> str:
        return f"{period.year}/{period.month}"

    comparison_period = pd.Timestamp(frame.loc[comparison_mask].index[-1])
    previous_label = period_label(comparison_period)
    current_label = period_label(latest_period)
    return pd.DataFrame(
        {
            f"{previous_label} Tutar": previous_values.to_numpy(),
            f"{previous_label} Pay (%)": sales_share(
                previous_values, previous_sales
            ).to_numpy(),
            f"{current_label} Tutar": current_values.to_numpy(),
            f"{current_label} Pay (%)": sales_share(
                current_values, current_sales
            ).to_numpy(),
            # Reference workbook formula: current / previous - 1.
            "Değişim (%)": (
                current_values.div(previous_values.replace(0, np.nan)).sub(1).mul(100)
            ).to_numpy(),
        },
        index=pd.Index([str(column).strip() for column in income_columns], name="Kalem"),
    )


def _vertical_analysis_to_html(df: pd.DataFrame, *, missing_message: str) -> str:
    """Render vertical analysis with one sticky-compatible header row."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return dataframe_to_html(
            pd.DataFrame(
                {
                    "Durum": [missing_message]
                }
            ),
            index=False,
        )
    return dataframe_to_html(
        df,
        classes="data-table vertical-analysis-table",
    )


def _plot_rule_based_valuation(mod: Any, result: ValuationResult) -> None:
    """Show method targets and the rule-based scenario band without model jargon."""
    methods = result.methods.loc[result.methods["Güven Ağırlığı %"] > 0].copy()
    summary = result.summary.iloc[-1]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=methods.index.tolist(),
            y=methods["Baz Hedef"],
            name="Yöntem Değerlemesi",
            marker_color=ACCENT,
            text=[format_tr_number(value, 2, " TL") for value in methods["Baz Hedef"]],
            textposition="outside",
            hovertemplate="%{x}<br>Model değeri: %{y:,.2f} TL<extra></extra>",
        )
    )
    fig.add_hrect(
        y0=float(summary["Temkinli Hedef"]),
        y1=float(summary["İyimser Hedef"]),
        fillcolor="rgba(110,173,80,0.20)",
        line_width=0,
        annotation_text="Temkinli–İyimser senaryo aralığı",
        annotation_position="top left",
    )
    fig.add_hline(
        y=float(summary["Ağırlıklı Hedef"]),
        line_color=DOWN_COLOR,
        line_dash="dash",
    )
    fig.add_annotation(
        x=0.99,
        y=0.98,
        xref="paper",
        yref="paper",
        xanchor="right",
        yanchor="top",
        text=f"Model değerleme ortalaması: {format_tr_number(summary['Ağırlıklı Hedef'], 2, ' TL')}",
        showarrow=False,
        bgcolor="rgba(236,241,229,0.94)",
        bordercolor=DOWN_COLOR,
        borderwidth=1,
        borderpad=6,
        font={"color": TEXT_COLOR, "size": 12},
    )
    fig.update_yaxes(title_text="Hisse Fiyatı (TL)", rangemode="tozero")
    apply_theme(
        fig,
        height=470,
        title=(
            "Model Bazlı Değerleme — "
            f"{summary['Değerleme Ufku']} | Model yeterliliği: "
            f"{summary['Veri Güveni']} {int(summary['Güven Puanı'])}/100"
        ),
    )
    # Kısa yöntem adları (F/K, PD/DD…) yatay daha okunaklı.
    fig.update_xaxes(tickangle=0)
    mod.show(fig)


def _build_company_summary(
    hisse: str,
    raw_financials: pd.DataFrame,
    ratios: pd.DataFrame,
    quarterly_income: pd.DataFrame,
) -> dict[str, Any] | None:
    """Build the compact company dashboard.

    Income rows use exact same-quarter YoY; balance-sheet rows use the prior
    reporting period (QoQ) because stock levels are most useful sequentially.
    """
    if not isinstance(raw_financials, pd.DataFrame) or raw_financials.empty:
        return None

    raw = raw_financials.sort_index()
    ratio_frame = ratios.sort_index() if isinstance(ratios, pd.DataFrame) else pd.DataFrame()
    quarterly = (
        quarterly_income.sort_index()
        if isinstance(quarterly_income, pd.DataFrame)
        else pd.DataFrame()
    )
    raw_periods = pd.to_datetime(raw.index, errors="coerce")
    valid_positions = np.flatnonzero(~pd.isna(raw_periods))
    if not len(valid_positions):
        return None

    latest_position = int(valid_positions[-1])
    latest_period = pd.Timestamp(raw_periods[latest_position])
    latest_index = raw.index[latest_position]
    comparison_matches = [
        int(position)
        for position in valid_positions
        if pd.Timestamp(raw_periods[position]).year == latest_period.year - 1
        and pd.Timestamp(raw_periods[position]).month == latest_period.month
    ]
    comparison_position = comparison_matches[-1] if comparison_matches else None
    comparison_index = raw.index[comparison_position] if comparison_position is not None else None
    prior_period_position = (
        int(valid_positions[-2]) if len(valid_positions) >= 2 else None
    )
    prior_period_index = (
        raw.index[prior_period_position] if prior_period_position is not None else None
    )
    prior_period = (
        pd.Timestamp(raw_periods[prior_period_position])
        if prior_period_position is not None
        else None
    )

    def period_label(value: Any) -> str:
        period = pd.Timestamp(value)
        return f"{period.year}/{period.month}"

    def frame_row_for_period(frame: pd.DataFrame, period: pd.Timestamp) -> pd.Series | None:
        if frame.empty:
            return None
        frame_periods = pd.to_datetime(frame.index, errors="coerce")
        positions = [
            position
            for position, value in enumerate(frame_periods)
            if pd.notna(value)
            and pd.Timestamp(value).year == period.year
            and pd.Timestamp(value).month == period.month
        ]
        return frame.iloc[positions[-1]] if positions else None

    def finite_value(row: pd.Series | None, candidates: tuple[str, ...]) -> float | None:
        if row is None:
            return None
        for column in candidates:
            if column not in row.index:
                continue
            try:
                value = float(row[column])
            except (TypeError, ValueError):
                continue
            if np.isfinite(value):
                return value
        return None

    latest_raw = raw.loc[latest_index]
    yoy_raw = raw.loc[comparison_index] if comparison_index is not None else None
    prior_raw = raw.loc[prior_period_index] if prior_period_index is not None else None
    latest_ratio = frame_row_for_period(ratio_frame, latest_period)
    yoy_ratio = (
        frame_row_for_period(
            ratio_frame,
            pd.Timestamp(year=latest_period.year - 1, month=latest_period.month, day=1),
        )
        if comparison_index is not None
        else None
    )
    prior_ratio = (
        frame_row_for_period(ratio_frame, prior_period) if prior_period is not None else None
    )

    def comparison_row(
        label: str,
        candidates: tuple[str, ...],
        *,
        previous_raw_row: pd.Series | None,
        previous_ratio_row: pd.Series | None,
        source: str = "raw",
        inverse: bool = False,
    ) -> dict[str, Any] | None:
        current_source = latest_ratio if source == "ratio" else latest_raw
        previous_source = previous_ratio_row if source == "ratio" else previous_raw_row
        current = finite_value(current_source, candidates)
        previous = finite_value(previous_source, candidates)
        if current is None and previous is None:
            return None
        change_pct = None
        if current is not None and previous not in (None, 0):
            if inverse:
                # Net borç = finansal borç - nakit. Bu nedenle negatif değer
                # nakit fazlasıdır ve daha negatife gitmek iyileşmedir. İşareti
                # koruyan değişim: -13 -> -23 = -%75 (yeşil), 40 -> 50 =
                # +%25 (kırmızı). Renk ters yönlü gösterge kuralıyla belirlenir.
                change_pct = (current - previous) / abs(previous) * 100
            # Net borç dışındaki kalemlerde negatif bir tabandan pozitife
            # geçişte klasik yüzde değişim yanıltıcıdır (örn. zarar -> kâr).
            elif previous < 0 < current:
                change_pct = None
            else:
                change_pct = (current / previous - 1) * 100
        return {
            "label": label,
            "current": current,
            "previous": previous,
            "change_pct": change_pct if change_pct is None or np.isfinite(change_pct) else None,
            "inverse": inverse,
        }

    income_specs = [
        ("Satışlar", ("Satış Gelirleri",)),
        ("Brüt Kâr", ("BRÜT KAR (ZARAR)",)),
        ("FAVÖK", ("FAVÖK",)),
        (
            "Net Parasal Pozisyon Kazancı/(Kaybı)",
            (
                "Net Parasal Pozisyon Kazançları (Kayıpları)",
                "Net Parasal Pozisyon Kazancı (Kaybı)",
                "Net Parasal Pozisyon Kazanç/Kayıpları",
            ),
        ),
        ("Net Dönem Kârı", ("Ana Ortaklık Payları", "DÖNEM KARI (ZARARI)")),
    ]
    balance_specs = [
        ("Dönen Varlıklar", ("Dönen Varlıklar",), "raw", False),
        ("Duran Varlıklar", ("Duran Varlıklar",), "raw", False),
        ("Toplam Varlıklar", ("TOPLAM VARLIKLAR",), "raw", False),
        ("Net Borç", ("net_borc",), "ratio", True),
        (
            "Özkaynaklar",
            ("Özkaynaklar", "  Ana Ortaklığa Ait Özkaynaklar"),
            "raw",
            False,
        ),
    ]
    income_rows = [
        row
        for label, candidates in income_specs
        if (
            row := comparison_row(
                label,
                candidates,
                previous_raw_row=yoy_raw,
                previous_ratio_row=yoy_ratio,
            )
        )
        is not None
    ]
    balance_rows = [
        row
        for label, candidates, source, inverse in balance_specs
        if (
            row := comparison_row(
                label,
                candidates,
                previous_raw_row=prior_raw,
                previous_ratio_row=prior_ratio,
                source=source,
                inverse=inverse,
            )
        )
        is not None
    ]

    quarterly_points: list[dict[str, Any]] = []
    for index, row in quarterly.tail(5).iterrows():
        quarterly_points.append(
            {
                "period": period_label(index),
                "sales": finite_value(row, ("Satış Gelirleri",)),
                "ebitda": finite_value(row, ("FAVÖK",)),
                "net_income": finite_value(
                    row,
                    ("Ana Ortaklık Payları", "DÖNEM KARI (ZARARI)"),
                ),
            }
        )

    price_points: list[dict[str, Any]] = []
    price_column = next(
        (column for column in ("duzeltilmis_fiyat", "fiyat") if column in ratio_frame.columns),
        None,
    )
    if price_column:
        for index, value in pd.to_numeric(
            ratio_frame[price_column], errors="coerce"
        ).dropna().tail(12).items():
            price_points.append({"period": period_label(index), "price": float(value)})

    return {
        "symbol": str(hisse).upper(),
        "latest_period": period_label(latest_period),
        "comparison_period": (
            period_label(comparison_index) if comparison_index is not None else None
        ),
        "comparison_available": comparison_index is not None,
        "balance_comparison_period": (
            period_label(prior_period_index) if prior_period_index is not None else None
        ),
        "balance_comparison_available": prior_period_index is not None,
        "kpis": {
            "price": finite_value(latest_ratio, ("duzeltilmis_fiyat", "fiyat")),
            "market_cap": finite_value(latest_ratio, ("PD",)),
            "pe": finite_value(latest_ratio, ("F/K",)),
            "pb": finite_value(latest_ratio, ("PD/DD",)),
            "ev_ebitda": finite_value(latest_ratio, ("FD/FAVÖK",)),
        },
        "income_rows": income_rows,
        "balance_rows": balance_rows,
        "quarterly": quarterly_points,
        "price_history": price_points,
    }


def _to_html(obj: Any) -> str:
    """DataFrame veya dict'i HTML tablosuna dönüştürür."""
    if isinstance(obj, pd.DataFrame):
        return dataframe_to_html(obj, index=False)
    return dataframe_to_html(pd.DataFrame([obj]), index=False)


def _score_summary_html(total_score: Any, signal: str) -> str:
    """Toplam skor + sinyal için renkli HTML tablo üretir."""
    signal_colors = {
        "Çok Güçlü": ACCENT,
        "Güçlü":     ACCENT_H,
        "Nötr":      "#56685B",
        "Zayıf":     "#B00000",
        "Çok Zayıf": DOWN_COLOR,
    }
    score_text = (
        f"{format_tr_number(total_score, 2)} / 100"
        if isinstance(total_score, (int, float)) and not pd.isna(total_score)
        else "—"
    )
    color = signal_colors.get(signal, "#56685B")
    return (
        '<table border="0" class="data-table">'
        "<thead><tr>"
        '<th style="text-align:left">Toplam Skor</th>'
        '<th style="text-align:left">Sinyal</th>'
        "</tr></thead>"
        "<tbody><tr>"
        f'<td style="text-align:left;font-size:20px;font-weight:700;color:{TEXT_COLOR}">{score_text}</td>'
        f'<td style="text-align:left;font-size:16px;font-weight:700;color:{color}">{signal}</td>'
        "</tr></tbody>"
        "</table>"
    )


def _piotroski_summary_html(score: Any, max_score: Any, eksik_kriter: Any) -> str:
    """Piotroski F-Skoru özeti için renkli HTML tablo üretir."""
    if not isinstance(score, (int, float)) or pd.isna(score):
        score_text = "—"
        color = "#56685B"
        note = "Hesaplanamadı (en az 5 dönemlik veri gerekli)"
    else:
        score_text = f"{int(score)} / {int(max_score)}"
        ratio = score / max_score if max_score else 0
        if ratio >= 0.75:
            color = ACCENT
        elif ratio >= 0.5:
            color = "#56685B"
        else:
            color = DOWN_COLOR
        note = (
            f"{int(eksik_kriter)} kriter veri yetersizliğinden hesaplanamadı"
            if eksik_kriter
            else "9 kriterin tamamı hesaplandı"
        )
    return (
        '<table border="0" class="data-table">'
        "<thead><tr>"
        '<th style="text-align:left">Piotroski F-Skoru</th>'
        '<th style="text-align:left">Not</th>'
        "</tr></thead>"
        "<tbody><tr>"
        f'<td style="text-align:left;font-size:20px;font-weight:700;color:{color}">{score_text}</td>'
        f'<td style="text-align:left;font-size:13px;color:#56685B">{note}</td>'
        "</tr></tbody>"
        "</table>"
    )


def company_options() -> dict[str, Any]:
    return {
        "degerleme": ["EVET", "HAYIR"],
    }


def _lookup_company_name(project_root: Path, symbol: str) -> str | None:
    """Return the optional company name from ``temel_ozet.xlsx``.

    The workbook is supporting presentation data. A missing file, unexpected
    schema or unmatched symbol must never stop the financial analysis.
    """
    try:
        overview = pd.read_excel(project_root / "temel_ozet.xlsx")
        normalized_columns = {
            str(column).strip().casefold(): column for column in overview.columns
        }
        code_column = normalized_columns.get("kod")
        name_column = next(
            (
                normalized_columns.get(candidate)
                for candidate in ("hisse adı", "şirket adı", "sirket adi")
                if normalized_columns.get(candidate) is not None
            ),
            None,
        )
        if code_column is None or name_column is None:
            return None

        codes = overview[code_column].astype("string").str.strip().str.upper()
        matches = overview.loc[codes.eq(str(symbol).strip().upper()).fillna(False)]
        if matches.empty:
            return None
        value = matches.iloc[0][name_column]
        if pd.isna(value):
            return None
        company_name = str(value).strip()
        return company_name or None
    except Exception:  # Optional heading metadata must fail open.
        return None


def run_company_analysis(
    *,
    project_root: Path,
    outputs_dir: Path,
    hisse: str,
    degerleme: str,
) -> RenderedOutput:
    total_started = time.perf_counter()

    nb_path = project_root / "Sirket Analiz.ipynb"
    rt = NotebookRuntime(nb_path, project_root=project_root, outputs_dir=outputs_dir)
    module_started = time.perf_counter()
    mod = rt.module()
    module_seconds = time.perf_counter() - module_started

    required = [
        "bilanco_cekme",
        "gelir_tablosu",
        "bilanco_yillik",
        "oran_rasyo_hesaplama",
        "donemlik_fark",
        "waterfall_subplots_readable",
        "GELIR_KALEMLERI",
        "SELALE_KALEMLERI",
        "trend_endeks_analizi",
        "trend_endeks_plot",
        "ceyreklik_gelir_analizi",
        "ceyreklik_gelir_plot",
        "degisim_plot",
        "karlılık_plot",
        "denge_plot",
        "liktide_plot",
        "yeterlik_plot",
        "plot_nakit_akimi",
        "plot_degerleme_dashboard",
        "financial_scorecard",
        "piotroski_f_skoru",
        "dupont_analizi_donemsel",
        "dupont_plot",
    ]
    for fn in required:
        if not hasattr(mod, fn):
            raise RuntimeError(f"Notebook içinde `{fn}` fonksiyonu bulunamadı.")

    cleanup, snapshot = rt.with_plotly_saver(request_id="company", prefix="sirket")
    try:
        financial_data_started = time.perf_counter()
        df_bilanco = mod.bilanco_cekme([hisse])
        df_dikey_bilanco = _build_vertical_balance_analysis(df_bilanco)
        df_dikey_gelir = _build_vertical_income_analysis(df_bilanco)
        gelir_tab_yil = mod.gelir_tablosu(df_bilanco, ceyrek=False, yillik=True)
        new_df = mod.bilanco_yillik(df_bilanco, gelir_tab_yil)
        df = mod.oran_rasyo_hesaplama(new_df, hisse, df_bilanco)
        financial_data_seconds = time.perf_counter() - financial_data_started

        chart_metric_started = time.perf_counter()
        df_fark = mod.donemlik_fark(df)
        income_columns = [
            column for column in mod.GELIR_KALEMLERI if column in df_fark.columns
        ]
        annualized_income_changes = df_fark.loc[:, income_columns]
        df_ceyreklik_gelir = mod.ceyreklik_gelir_analizi(df_bilanco)
        periodic_income_changes = (
            df_ceyreklik_gelir.loc[:, income_columns]
            .apply(pd.to_numeric, errors="coerce")
            .diff()
            .dropna(how="all")
        )
        raw_cumulative_income_levels = df_bilanco.loc[:, income_columns]
        raw_cumulative_income_levels = raw_cumulative_income_levels.loc[
            :, ~raw_cumulative_income_levels.columns.duplicated()
        ]
        raw_cumulative_income_changes = (
            raw_cumulative_income_levels
            .apply(pd.to_numeric, errors="coerce")
            .diff()
            .dropna(how="all")
        )
        balance_columns = [
            column
            for column in mod.SELALE_KALEMLERI
            if column not in mod.GELIR_KALEMLERI and column in df_bilanco.columns
        ]
        balance_levels = df_bilanco.loc[:, balance_columns]
        balance_levels = balance_levels.loc[:, ~balance_levels.columns.duplicated()]
        balance_changes = (
            balance_levels.apply(pd.to_numeric, errors="coerce").diff().dropna(how="all")
        )

        mod.waterfall_subplots_readable(
            annualized_income_changes,
            title="Gelir Tablosu Değişim Analizi — Yıllıklandırılmış",
        )
        snapshot(
            "büyüme",
            {
                "analysis_section": "income_statement_changes",
                "analysis_section_title": "Gelir Tablosu Kalemleri",
                "chart_toggle_group": "income_statement_change_period",
                "chart_toggle_label": "Yıllıklandırılmış",
                "chart_toggle_order": 1,
            },
        )
        mod.waterfall_subplots_readable(
            periodic_income_changes,
            title="Gelir Tablosu Değişim Analizi — Dönemsel",
        )
        snapshot(
            "büyüme",
            {
                "analysis_section": "income_statement_changes",
                "analysis_section_title": "Gelir Tablosu Kalemleri",
                "chart_toggle_group": "income_statement_change_period",
                "chart_toggle_label": "Dönemsel",
                "chart_toggle_order": 2,
            },
        )
        mod.waterfall_subplots_readable(
            raw_cumulative_income_changes,
            title="Gelir Tablosu Değişim Analizi — Açıklanan Ham 3-6-9-12 Aylık",
        )
        snapshot(
            "büyüme",
            {
                "analysis_section": "income_statement_changes",
                "analysis_section_title": "Gelir Tablosu Kalemleri",
                "chart_toggle_group": "income_statement_change_period",
                "chart_toggle_label": "Açıklanan Kümülatif",
                "chart_toggle_order": 3,
            },
        )
        mod.waterfall_subplots_readable(
            balance_changes,
            title="Bilanço Kalemleri Değişim Analizi",
        )
        snapshot(
            "büyüme",
            {
                "analysis_section": "balance_sheet_changes",
                "analysis_section_title": "Bilanço Kalemleri",
            },
        )

        df_trend_endeks = mod.trend_endeks_analizi(df)
        mod.trend_endeks_plot(df_trend_endeks)
        snapshot("büyüme")

        mod.ceyreklik_gelir_plot(df_ceyreklik_gelir)
        snapshot("büyüme")

        degisimler_cols = [
            "Satış Gelirleri_qoq_%",
            "Satış Gelirleri_yoy_%",
            "BRÜT KAR (ZARAR)_qoq_%",
            "BRÜT KAR (ZARAR)_yoy_%",
            "FAALİYET KARI (ZARARI)_qoq_%",
            "FAALİYET KARI (ZARARI)_yoy_%",
            "FAVÖK_qoq_%",
            "FAVÖK_yoy_%",
            "DÖNEM KARI (ZARARI)_qoq_%",
            "DÖNEM KARI (ZARARI)_yoy_%",
            "Serbest Nakit Akım_qoq_%",
            "Serbest Nakit Akım_yoy_%",
            " İşletme Faaliyetlerinden Kaynaklanan Net Nakit_qoq_%",
            " İşletme Faaliyetlerinden Kaynaklanan Net Nakit_yoy_%",
        ]
        degisimler_df = df[[c for c in degisimler_cols if c in df.columns]]
        mod.degisim_plot(degisimler_df)
        snapshot("büyüme")

        karlilik_cols = [
            "Satış Gelirleri",
            "BRÜT KAR (ZARAR)",
            "FAALİYET KARI (ZARARI)",
            "DÖNEM KARI (ZARARI)",
            "FAVÖK",
            "brüt_kar_marjı_%",
            "faaliyet_kar_marjı_%",
            "favok_marjı_%",
            "net_kar_marjı_%",
            "aktif_karliligi_%",
            "ozkaynak_karliligi_%",
            "ihracat_oranı_%",
        ]
        df_karlilik = df[[c for c in karlilik_cols if c in df.columns]].rename(
            columns={"ihracat_oranı_%": "İhracat Oranı (%)"}
        )
        mod.karlılık_plot(df_karlilik)
        snapshot("karlılık")

        dupont_df = mod.dupont_analizi_donemsel(df)
        mod.dupont_plot(dupont_df)
        snapshot("dupont")

        denge_cols = [
            "Dönen Varlıklar",
            "Duran Varlıklar",
            "TOPLAM VARLIKLAR",
            "Kısa Vadeli Yükümlülükler",
            "Uzun Vadeli Yükümlülükler",
            "Özkaynaklar",
            "toplam_borclar",
            "net_isletme_sermayesi",
        ]
        df_denge = df[[c for c in denge_cols if c in df.columns]]
        mod.denge_plot(df_denge)
        snapshot("bilanço")

        likitide_cols = [
            "  Nakit ve Nakit Benzerleri",
            "cari_oran",
            "likitide_oranı",
            "nakit_oranı",
            "net_borc",
            "net_borc/FAVOK",
            "faiz_karsilama",
        ]
        df_likitide = df[[c for c in likitide_cols if c in df.columns]].rename(
            columns={"faiz_karsilama": "Faiz Karşılama Oranı"}
        )
        mod.liktide_plot(df_likitide)
        snapshot("likidite")

        yeterlik_cols = [
            "aktif_devir_hizi",
            "alacak_devir_hizi",
            "stok_devir_hizi",
            "borc_devir_hizi",
            "alacak_tahsil_suresi_gun",
            "stok_gun_sayisi",
            "borc_odeme_suresi",
            "nakit_dongu",
        ]
        df_yeterlik = df[[c for c in yeterlik_cols if c in df.columns]]
        mod.yeterlik_plot(df_yeterlik)
        snapshot("verimlilik")

        nakit_akimi_cols = [
            " İşletme Faaliyetlerinden Kaynaklanan Net Nakit",
            "Serbest Nakit Akım",
            " Yatırım Faaliyetlerinden Kaynaklanan Nakit",
            "Finansman Faaliyetlerden Kaynaklanan Nakit",
            "Nakit ve Benzerlerindeki Değişim",
            "Dönem Başı Nakit Değerler",
            "Dönem Sonu Nakit",
        ]
        df_nakit_akimi = df[[c for c in nakit_akimi_cols if c in df.columns]]
        mod.plot_nakit_akimi(df_nakit_akimi)
        snapshot("nakit")

        degerleme_cols = [
            "fiyat",
            "getiri",
            "PD",
            "FD",
            "PD/DD",
            "F/K",
            "FD/FAVÖK",
            "PD/NFK",
            "FD/NS",
            "PD/NS",
            "NFK/PD_%",
        ]
        df_degerleme = df[[c for c in degerleme_cols if c in df.columns]]
        mod.plot_degerleme_dashboard(df_degerleme)
        snapshot("değerleme")

        score_output = mod.financial_scorecard(df)
        piotroski_output = mod.piotroski_f_skoru(df)

        df_gelecek_donem = None
        valuation_result: ValuationResult | None = None
        valuation_warning: str | None = None
        financial_data_quality = "İleri değerleme çalıştırılmadı."
        chart_metric_seconds = time.perf_counter() - chart_metric_started
        forecast_seconds = 0.0

        if degerleme == "EVET":
            forecast_started = time.perf_counter()
            try:
                valuation_result = build_rule_based_valuation(
                    df_bilanco,
                    df,
                    valuation_date=pd.Timestamp.now(),
                )
            except InsufficientValuationDataError as exc:
                valuation_warning = f"{INSUFFICIENT_VALUATION_MESSAGE} Eksik koşul: {exc}"
                financial_data_quality = valuation_warning
            else:
                df_gelecek_donem = valuation_result.summary
                financial_data_quality = valuation_result.data_quality
                _plot_rule_based_valuation(mod, valuation_result)
                snapshot("değerleme")
            forecast_seconds = time.perf_counter() - forecast_started


    finally:
        charts = cleanup()

    table_started = time.perf_counter()
    tables: list[dict[str, str]] = [
        {
            "name": "Finansal Kalem Değişimleri",
            "category": "büyüme",
            "html": dataframe_to_html(df_fark),
        },
        {
            "name": "Büyüme Oranları",
            "category": "büyüme",
            "html": dataframe_to_html(degisimler_df),
        },
        {
            "name": "Kalem Bazında Trend Endeksi (Baz = 100)",
            "category": "büyüme",
            "html": dataframe_to_html(df_trend_endeks),
        },
        {
            "name": "Gelir Tablosu Kalemleri (Gerçek Çeyreklik)",
            "category": "büyüme",
            "html": dataframe_to_html(df_ceyreklik_gelir),
        },
        {
            "name": "Kârlılık ve Satış Yapısı",
            "category": "karlılık",
            "html": dataframe_to_html(df_karlilik),
        },
        {
            "name": "DuPont Analizi",
            "category": "dupont",
            "html": dataframe_to_html(dupont_df),
        },
        {
            "name": "Bilanço Dengesi",
            "category": "bilanço",
            "html": dataframe_to_html(df_denge),
        },
        {
            "name": "Dikey Bilanço Karşılaştırması",
            "category": "dikey",
            "html": _vertical_analysis_to_html(
                df_dikey_bilanco,
                missing_message=(
                    "Son dönemle aynı çeyreğe ait bir önceki yıl bilançosu "
                    "bulunamadığı için dikey bilanço analizi oluşturulamadı."
                ),
            ),
        },
        {
            "name": "Dikey Gelir Tablosu Karşılaştırması",
            "category": "dikey",
            "html": _vertical_analysis_to_html(
                df_dikey_gelir,
                missing_message=(
                    "Son dönemle aynı çeyreğe ait bir önceki yıl gelir tablosu "
                    "bulunamadığı için dikey gelir analizi oluşturulamadı."
                ),
            ),
        },
        {
            "name": "Likidite ve Borç Ödeme Gücü",
            "category": "likidite",
            "html": dataframe_to_html(df_likitide),
        },
        {
            "name": "Nakit Döngüsü",
            "category": "verimlilik",
            "html": dataframe_to_html(df_yeterlik),
        },
        {
            "name": "Nakit Akımı",
            "category": "nakit",
            "html": dataframe_to_html(df_nakit_akimi),
        },
        {
            "name": "Çarpanlar",
            "category": "değerleme",
            "html": dataframe_to_html(df_degerleme),
        },
        {
            "name": "Toplam Skor",
            "category": "skor",
            "html": _score_summary_html(
                score_output.get("total_score", float("nan")),
                score_output.get("signal", "—"),
            ),
        },
        {
            "name": "Skor Kartı (Kategori Skorları)",
            "category": "skor",
            "html": _to_html(score_output.get("category_scores", {})),
        },
        {
            "name": "Piotroski F-Skoru",
            "category": "skor",
            "html": _piotroski_summary_html(
                piotroski_output.get("score", float("nan")),
                piotroski_output.get("max_score", float("nan")),
                piotroski_output.get("eksik_kriter", 0),
            ),
        },
        {
            "name": "Piotroski F-Skoru Detayı",
            "category": "skor",
            "html": _to_html(piotroski_output.get("criteria", pd.DataFrame())),
        },
    ]

    if df_gelecek_donem is not None:
        tables.append(
            {
                "name": "Model Bazlı Değerleme Özeti",
                "category": "değerleme",
                "html": dataframe_to_html(
                    _valuation_summary_for_display(df_gelecek_donem)
                ),
            }
        )
    if valuation_result is not None:
        tables.append(
            {
                "name": "Değerleme Yöntemleri ve Ağırlıkları",
                "category": "değerleme",
                "html": dataframe_to_html(
                    _valuation_methods_for_display(valuation_result.methods)
                ),
            }
        )
        tables.append(
            {
                "name": "Finansal Projeksiyon Senaryoları",
                "category": "değerleme",
                "html": dataframe_to_html(valuation_result.projection),
            }
        )
        tables.append(
            {
                "name": "Değerleme Varsayımları",
                "category": "değerleme",
                "html": dataframe_to_html(valuation_result.assumptions, index=False),
            }
        )

    table_seconds = time.perf_counter() - table_started
    total_seconds = time.perf_counter() - total_started
    return RenderedOutput(
        tables=tables,
        charts=charts,
        meta={
            "hisse": hisse,
            "sirket_adi": _lookup_company_name(project_root, hisse),
            "degerleme": degerleme,
            "degerleme_uyarisi": valuation_warning,
            "rows": int(len(df)),
            "finansal_veri_kalitesi": financial_data_quality,
            "sirket_ozeti": _build_company_summary(
                hisse,
                df_bilanco,
                df,
                df_ceyreklik_gelir,
            ),
            "yil_sonu_degerleme_kpi": _valuation_kpi_summary(df_gelecek_donem),
            "rapor_bilgisi": _report_metadata(
                hisse,
                df_bilanco,
                valuation_created=valuation_result is not None,
            ),
            "sureler_saniye": {
                "toplam": round(total_seconds, 2),
                "notebook_hazirlama": round(module_seconds, 2),
                "finansal_veri_ve_fiyat": round(financial_data_seconds, 2),
                "grafik_ve_metrikler": round(chart_metric_seconds, 2),
                "tahmin_ve_degerleme": round(forecast_seconds, 2),
                "tablolar": round(table_seconds, 2),
            },
        },
    )
