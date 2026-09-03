from __future__ import annotations

import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .notebook_runtime import NotebookRuntime, RenderedOutput
from .plotly_theme import (
    COLORSCALE_HIGH_GOOD,
    COLORSCALE_LOW_GOOD,
    DOWN_COLOR,
    TREND_COLORWAY,
    UP_COLOR,
    apply_theme,
    format_tr_number,
    format_period_labels,
    heatmap_vertical_spacing,
    style_heatmap_xaxes,
    style_subplot_titles,
    to_json_safe,
)
from .table_format import dataframe_to_html, write_formatted_excel

# Columns for bar charts (absolute values)
_BAR_COLS = [
    "PD",
    "FD",
    "Satış Gelirleri",
    "Net Faaliyet Kar/Zararı",
    "FAVÖK",
    "Ana Ortaklık Payları",
    "Piotroski F-Skoru",
]

# Columns for heatmap charts (ratios)
_RATIO_COLS = [
    "F/K",
    "FD/FAVÖK",
    "FD/NS",
    "PD/DD",
    "NFK/PD_%",
    "iskonto_%",
    "brüt_kar_marjı_%",
    "net_kar_marjı_%",
    "aktif_devir_hizi",
    "ozkaynak_carpani",
    "roe_dupont_%",
    "faiz_karsilama",
    "ihracat_oranı_%",
]

# Columns where a higher value is better (for heatmap coloring)
_HIGH_IS_GOOD = {
    "NFK/PD_%",
    "iskonto_%",
    "brüt_kar_marjı_%",
    "net_kar_marjı_%",
    "aktif_devir_hizi",
    "roe_dupont_%",
    "faiz_karsilama",
    "ihracat_oranı_%",
}

_DISPLAY_LABELS = {
    "faiz_karsilama": "Faiz Karşılama Oranı",
    "ihracat_oranı_%": "İhracat Oranı (%)",
    "Ortalama Tahmin PD": "Sektör Referanslı Model Piyasa Değeri",
    "Ortalama Tahmin Fiyat": "Sektör Referanslı Model Değeri",
    "iskonto_%": "Piyasa Fiyatına Göre Model Farkı (%)",
}


def _sector_report_metadata(sektor: str, analiz_turu: str) -> dict[str, Any]:
    created_at = datetime.now(ZoneInfo("Europe/Istanbul"))
    return {
        "report_id": f"FM-SEKTOR-{created_at:%Y%m%d-%H%M%S}",
        "generated_at": created_at.isoformat(timespec="seconds"),
        "scope": sektor,
        "comparison_method": analiz_turu,
        "financial_source": "İş Yatırım",
        "price_source": "Yahoo Finance",
        "methodology_version": "FM-Sektör v2.0",
        "valuation_created": True,
        "price_time_note": (
            "Fiyatlar veri kaynağındaki son erişilebilir gözlemlerdir; gerçek zamanlı "
            "fiyat garantisi verilmez."
        ),
        "update_policy": (
            "Rapor, analiz yeniden çalıştırıldığında erişilebilen finansal tablolar ve "
            "fiyat verileriyle yeniden oluşturulur."
        ),
        "correction_policy": (
            "Veri veya hesaplama hatası tespit edilirse yeni rapor kimliğiyle düzeltilmiş "
            "bir sonuç yayımlanır."
        ),
    }

_SECTOR_FLOW_COLS = [
    "Satış Gelirleri",
    "BRÜT KAR (ZARAR)",
    "Net Faaliyet Kar/Zararı",
    "FAVÖK",
    "Ana Ortaklık Payları",
]

_SECTOR_FLOW_LABELS = {
    "Satış Gelirleri": "Satış Gelirleri",
    "BRÜT KAR (ZARAR)": "Brüt Kâr (Zarar)",
    "Net Faaliyet Kar/Zararı": "Net Faaliyet Kârı/Zararı",
    "FAVÖK": "FAVÖK",
    "Ana Ortaklık Payları": "Net Dönem Kârı/Zararı",
}

_SECTOR_MARGIN_SPECS = {
    "Brüt Kâr Marjı %": "BRÜT KAR (ZARAR)",
    "Faaliyet Kâr Marjı %": "Net Faaliyet Kar/Zararı",
    "FAVÖK Marjı %": "FAVÖK",
    "Net Kâr Marjı %": "Ana Ortaklık Payları",
}


def _period_label(value: Any) -> str:
    timestamp = pd.to_datetime(value, errors="coerce")
    return "—" if pd.isna(timestamp) else f"{timestamp.year}/{timestamp.month}"


def _build_sector_financial_history(
    company_histories: dict[str, pd.DataFrame],
    latest_financial_periods: dict[str, Any],
    *,
    requested_symbols: list[str] | None = None,
    reference_coverage: float = 0.70,
) -> dict[str, Any] | None:
    """Create comparable sector totals without mixing stale reporting periods.

    The reference quarter is the newest quarter reached by at least 70% of the
    successfully analysed companies. Every plotted metric uses companies that
    reported that reference quarter. Historical changes are calculated with a
    pairwise-comparable cohort for each adjacent period. This retains the full
    available history without making a newly available/missing company look
    like a rise or fall in the sector.
    """
    normalized_histories: dict[str, pd.DataFrame] = {}
    normalized_latest: dict[str, pd.Timestamp] = {}
    for symbol, history in (company_histories or {}).items():
        if not isinstance(history, pd.DataFrame) or history.empty:
            continue
        frame = history.copy()
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).tz_localize(None)
        frame = frame.sort_index()
        available = [column for column in _SECTOR_FLOW_COLS if column in frame.columns]
        if not available:
            continue
        frame = frame.loc[:, available].apply(pd.to_numeric, errors="coerce")
        normalized_histories[str(symbol)] = frame
        latest = pd.to_datetime((latest_financial_periods or {}).get(symbol), errors="coerce")
        if pd.isna(latest):
            latest = frame.index.max()
        normalized_latest[str(symbol)] = pd.Timestamp(latest).tz_localize(None)

    if not normalized_histories or not normalized_latest:
        return None

    successful_symbols = sorted(normalized_histories)
    successful_count = len(successful_symbols)
    minimum_coverage = max(1, int(np.ceil(successful_count * reference_coverage)))
    latest_values = pd.Series(normalized_latest).sort_values()
    observed_latest = pd.Timestamp(latest_values.max())
    reference_period = observed_latest
    for candidate in sorted(latest_values.unique(), reverse=True):
        candidate_ts = pd.Timestamp(candidate)
        if int((latest_values >= candidate_ts).sum()) >= minimum_coverage:
            reference_period = candidate_ts
            break

    reference_symbols = sorted(
        symbol
        for symbol in successful_symbols
        if normalized_latest[symbol] >= reference_period
        and reference_period in normalized_histories[symbol].index
    )
    if not reference_symbols:
        return None

    totals = pd.DataFrame(dtype=float)
    differences = pd.DataFrame(dtype=float)
    trend = pd.DataFrame(dtype=float)
    metric_coverage: dict[str, int] = {}
    metric_period_coverage: dict[str, dict[str, int]] = {}
    metric_change_coverage: dict[str, dict[str, int]] = {}
    for column in _SECTOR_FLOW_COLS:
        eligible = [
            symbol
            for symbol in reference_symbols
            if column in normalized_histories[symbol].columns
            and pd.notna(normalized_histories[symbol].at[reference_period, column])
        ]
        if not eligible:
            continue
        matrix = pd.concat(
            {
                symbol: normalized_histories[symbol][column]
                for symbol in eligible
            },
            axis=1,
        ).sort_index()
        available_count = matrix.notna().sum(axis=1)
        total = matrix.sum(axis=1, min_count=1).where(available_count.gt(0))
        totals[column] = total
        metric_coverage[column] = len(eligible)

        label = _SECTOR_FLOW_LABELS.get(column, column)
        metric_period_coverage[label] = {
            _period_label(period): int(count)
            for period, count in available_count.items()
            if int(count) > 0
        }

        comparable_change = pd.Series(np.nan, index=matrix.index, dtype=float)
        chained_trend = pd.Series(np.nan, index=matrix.index, dtype=float)
        change_counts: dict[str, int] = {}
        populated_periods = list(matrix.index[available_count.gt(0)])
        if populated_periods:
            chained_trend.loc[populated_periods[0]] = 100.0
        for previous_period, current_period in zip(
            populated_periods, populated_periods[1:]
        ):
            comparable = (
                matrix.loc[[previous_period, current_period]].notna().all(axis=0)
            )
            comparable_symbols = list(matrix.columns[comparable])
            if not comparable_symbols:
                continue
            previous_total = float(
                matrix.loc[previous_period, comparable_symbols].sum()
            )
            current_total = float(
                matrix.loc[current_period, comparable_symbols].sum()
            )
            comparable_change.loc[current_period] = current_total - previous_total
            change_counts[_period_label(current_period)] = len(comparable_symbols)

            previous_index = chained_trend.loc[previous_period]
            if np.isfinite(previous_index) and previous_total != 0:
                chained_trend.loc[current_period] = (
                    float(previous_index) * current_total / previous_total
                )

        differences[column] = comparable_change
        trend[column] = chained_trend
        metric_change_coverage[label] = change_counts

    totals = totals.sort_index().dropna(how="all")
    if totals.empty:
        return None
    differences = differences.sort_index().dropna(how="all")
    trend = trend.sort_index().dropna(how="all")

    margins = pd.DataFrame(dtype=float)
    margin_coverage: dict[str, int] = {}
    margin_period_coverage: dict[str, dict[str, int]] = {}
    for label, numerator in _SECTOR_MARGIN_SPECS.items():
        eligible = [
            symbol
            for symbol in reference_symbols
            if numerator in normalized_histories[symbol].columns
            and "Satış Gelirleri" in normalized_histories[symbol].columns
            and pd.notna(normalized_histories[symbol].at[reference_period, numerator])
            and pd.notna(normalized_histories[symbol].at[reference_period, "Satış Gelirleri"])
        ]
        if not eligible:
            continue
        numerator_matrix = pd.concat(
            {symbol: normalized_histories[symbol][numerator] for symbol in eligible}, axis=1
        ).sort_index()
        sales_matrix = pd.concat(
            {symbol: normalized_histories[symbol]["Satış Gelirleri"] for symbol in eligible}, axis=1
        ).sort_index()
        shared_index = numerator_matrix.index.union(sales_matrix.index).sort_values()
        numerator_matrix = numerator_matrix.reindex(shared_index)
        sales_matrix = sales_matrix.reindex(shared_index)
        comparable = numerator_matrix.notna() & sales_matrix.notna()
        period_count = comparable.sum(axis=1)
        numerator_total = numerator_matrix.where(comparable).sum(axis=1, min_count=1)
        sales_total = sales_matrix.where(comparable).sum(axis=1, min_count=1)
        margins[label] = numerator_total / sales_total.replace(0, np.nan) * 100.0
        margin_coverage[label] = len(eligible)
        margin_period_coverage[label] = {
            _period_label(period): int(count)
            for period, count in period_count.items()
            if int(count) > 0
        }
    margins = margins.replace([np.inf, -np.inf], np.nan).dropna(how="all")

    observed_missing = {
        symbol: _period_label(normalized_latest[symbol])
        for symbol in successful_symbols
        if normalized_latest[symbol] < observed_latest
    }
    reference_missing = {
        symbol: _period_label(normalized_latest[symbol])
        for symbol in successful_symbols
        if normalized_latest[symbol] < reference_period
    }
    requested = [str(symbol) for symbol in (requested_symbols or successful_symbols)]
    no_history = sorted(set(requested).difference(normalized_histories))

    return {
        "totals": totals,
        "differences": differences,
        "trend": trend,
        "margins": margins,
        "coverage": {
            "observed_latest_period": _period_label(observed_latest),
            "reference_period": _period_label(reference_period),
            "successful_count": successful_count,
            "reference_count": len(reference_symbols),
            "requested_count": len(requested),
            "reference_ratio_pct": round(len(reference_symbols) / successful_count * 100.0, 1),
            "observed_latest_reporter_count": int((latest_values >= observed_latest).sum()),
            "observed_latest_missing": observed_missing,
            "reference_missing": reference_missing,
            "no_history": no_history,
            "metric_coverage": {
                _SECTOR_FLOW_LABELS.get(column, column): count
                for column, count in metric_coverage.items()
            },
            "metric_period_coverage": metric_period_coverage,
            "metric_change_coverage": metric_change_coverage,
            "margin_coverage": margin_coverage,
            "margin_period_coverage": margin_period_coverage,
            "method": "Dönemsel eşleşen şirket evrenli yıllıklandırılmış sektör toplamı",
        },
    }


def _prepare_plot_df(sektor_df: pd.DataFrame) -> pd.DataFrame:
    """Sektör toplamı/medyanı satırlarını kaldır, sayısal dönüşüm yap."""
    ozel = {"SEKTÖR TOPLAM", "SEKTÖR Median"}
    df = sektor_df.loc[~sektor_df.index.isin(ozel)].copy()
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass
    return df


def _plot_sector_bars(sirket_df: pd.DataFrame) -> go.Figure | None:
    """Bar grafikleri içeren interaktif bir Plotly figürü döndürür."""
    bar_cols = [
        c
        for c in _BAR_COLS
        if c in sirket_df.columns
        and sirket_df[c].replace([np.inf, -np.inf], np.nan).notna().any()
    ]
    if not bar_cols:
        return None

    ncols = 2
    nrows = (len(bar_cols) + ncols - 1) // ncols
    fig = make_subplots(
        rows=nrows,
        cols=ncols,
        subplot_titles=[_DISPLAY_LABELS.get(col, col) for col in bar_cols],
    )

    for i, col in enumerate(bar_cols):
        row, c = divmod(i, ncols)
        data = (
            sirket_df[col]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_values(ascending=False)
        )
        if data.empty:
            continue
        fig.add_trace(
            go.Bar(
                x=data.index.tolist(),
                y=data.values.tolist(),
                marker=dict(color=UP_COLOR, line=dict(color="#6EAD50", width=0.5)),
                text=[f"{v:,.0f}" for v in data.values],
                textposition="outside",
                showlegend=False,
            ),
            row=row + 1,
            col=c + 1,
        )

    apply_theme(fig, height=340 * nrows, title="Sektör — Mutlak Değer Grafikleri")
    style_subplot_titles(fig)
    fig.update_xaxes(tickangle=45)
    return fig


def _plot_sector_heatmaps(sirket_df: pd.DataFrame) -> go.Figure | None:
    """Çarpan/oran heatmap'lerini içeren interaktif bir Plotly figürü döndürür."""
    ratio_cols = [c for c in _RATIO_COLS if c in sirket_df.columns]
    if not ratio_cols:
        return None

    n = len(ratio_cols)
    fig = make_subplots(
        rows=n,
        cols=1,
        subplot_titles=[_DISPLAY_LABELS.get(col, col) for col in ratio_cols],
        vertical_spacing=heatmap_vertical_spacing(n),
    )

    for i, col in enumerate(ratio_cols):
        series = pd.to_numeric(sirket_df[col], errors="coerce").dropna()
        if series.empty:
            continue

        vals = series.values.astype(float)
        vmin = float(np.nanpercentile(vals, 5))
        vmax = float(np.nanpercentile(vals, 95))
        if vmin == vmax:
            vmin -= 1
            vmax += 1

        colorscale = COLORSCALE_HIGH_GOOD if col in _HIGH_IS_GOOD else COLORSCALE_LOW_GOOD
        # Her satır kendi renk ölçeğini kullanır; colorbar'ları dikeyde ayır.
        cbar_len = min(0.78 / n, 0.16)
        cbar_y = 1 - (i + 0.5) / n
        x_labels = format_period_labels(series.index)

        fig.add_trace(
            go.Heatmap(
                z=[vals.tolist()],
                x=x_labels,
                y=[_DISPLAY_LABELS.get(col, col)],
                zmin=vmin,
                zmax=vmax,
                colorscale=colorscale,
                text=[[f"{v:.2f}" for v in vals]],
                texttemplate="%{text}",
                textfont={"size": 11},
                showscale=True,
                colorbar=dict(len=cbar_len, y=cbar_y, thickness=12),
                hovertemplate=(
                    "%{x}: %{z:.2f}<extra>"
                    + _DISPLAY_LABELS.get(col, col)
                    + "</extra>"
                ),
            ),
            row=i + 1,
            col=1,
        )
        fig.update_yaxes(showticklabels=False, row=i + 1, col=1)

    apply_theme(fig, height=230 * n, title="Sektör — Çarpan / Oran Heatmapları")
    style_subplot_titles(fig)
    style_heatmap_xaxes(fig)
    return fig


def _plot_sector_annualized_changes(
    differences: pd.DataFrame,
    coverage: dict[str, Any],
) -> go.Figure | None:
    columns = [column for column in _SECTOR_FLOW_COLS if column in differences.columns]
    if not columns or differences.empty:
        return None
    ncols = 2
    nrows = int(np.ceil(len(columns) / ncols))
    fig = make_subplots(
        rows=nrows,
        cols=ncols,
        subplot_titles=[_SECTOR_FLOW_LABELS[column].upper() for column in columns],
    )
    metric_coverage = coverage.get("metric_coverage", {})
    change_coverage = coverage.get("metric_change_coverage", {})
    for index, column in enumerate(columns):
        row, col = divmod(index, ncols)
        series = pd.to_numeric(differences[column], errors="coerce").dropna()
        if series.empty:
            continue
        label = _SECTOR_FLOW_LABELS[column]
        period_counts = change_coverage.get(label, {})
        fallback_count = metric_coverage.get(label, coverage.get("reference_count", 0))
        company_counts = [
            period_counts.get(_period_label(period), fallback_count)
            for period in series.index
        ]
        hover = [
            f"Değişim: {format_tr_number(value)}<br>Karşılaştırılabilir şirket: {company_count}"
            for value, company_count in zip(series, company_counts)
        ]
        fig.add_trace(
            go.Waterfall(
                x=format_period_labels(series.index),
                y=series.values.tolist(),
                measure=["relative"] * len(series),
                increasing={"marker": {"color": UP_COLOR}},
                decreasing={"marker": {"color": DOWN_COLOR}},
                connector={"visible": False},
                text=[format_tr_number(value) for value in series],
                textposition="outside",
                textfont={"size": 10},
                customdata=hover,
                hovertemplate="%{x}<br>%{customdata}<extra>" + label + "</extra>",
                showlegend=False,
            ),
            row=row + 1,
            col=col + 1,
        )
        fig.update_xaxes(tickangle=45, automargin=True, row=row + 1, col=col + 1)
    title = (
        "Sektör Gelir Tablosu Değişim Analizi — Yıllıklandırılmış"
        f" | Referans kapsamı: {coverage.get('reference_count', 0)}/{coverage.get('successful_count', 0)} şirket"
    )
    apply_theme(fig, height=340 * nrows, title=title)
    style_subplot_titles(fig)
    return fig


def _plot_sector_trend_index(
    trend: pd.DataFrame,
    coverage: dict[str, Any],
) -> go.Figure | None:
    columns = [column for column in _SECTOR_FLOW_COLS if column in trend.columns]
    if not columns or trend.empty:
        return None
    ncols = 3
    nrows = int(np.ceil(len(columns) / ncols))
    fig = make_subplots(
        rows=nrows,
        cols=ncols,
        subplot_titles=[_SECTOR_FLOW_LABELS[column].upper() for column in columns],
    )
    metric_coverage = coverage.get("metric_coverage", {})
    period_coverage = coverage.get("metric_period_coverage", {})
    change_coverage = coverage.get("metric_change_coverage", {})
    for index, column in enumerate(columns):
        row, col = divmod(index, ncols)
        series = pd.to_numeric(trend[column], errors="coerce").dropna()
        if series.empty:
            continue
        label = _SECTOR_FLOW_LABELS[column]
        period_counts = period_coverage.get(label, {})
        fallback_count = metric_coverage.get(label, coverage.get("reference_count", 0))
        change_counts = change_coverage.get(label, {})
        company_counts = []
        for position, period in enumerate(series.index):
            period_label = _period_label(period)
            if position == 0:
                company_counts.append(period_counts.get(period_label, fallback_count))
            else:
                company_counts.append(
                    change_counts.get(
                        period_label,
                        period_counts.get(period_label, fallback_count),
                    )
                )
        fig.add_trace(
            go.Scatter(
                x=format_period_labels(series.index),
                y=series.values.tolist(),
                mode="lines+markers",
                line={"color": TREND_COLORWAY[index % len(TREND_COLORWAY)]},
                customdata=company_counts,
                hovertemplate=(
                    "%{x}<br>Endeks: %{y:.1f}<br>Karşılaştırılabilir şirket: %{customdata}"
                    "<extra>" + label + "</extra>"
                ),
                showlegend=False,
            ),
            row=row + 1,
            col=col + 1,
        )
        fig.add_hline(y=100, line_dash="dash", line_width=1, row=row + 1, col=col + 1)
        fig.update_xaxes(tickangle=45, automargin=True, row=row + 1, col=col + 1)
    title = (
        "Sektör Gelir Tablosu Trend Endeksi — Baz = 100"
        f" | Referans dönem: {coverage.get('reference_period', '—')}"
    )
    apply_theme(fig, height=300 * nrows, title=title)
    style_subplot_titles(fig)
    return fig


def _plot_sector_margins(
    margins: pd.DataFrame,
    coverage: dict[str, Any],
) -> go.Figure | None:
    columns = [column for column in _SECTOR_MARGIN_SPECS if column in margins.columns]
    if not columns or margins.empty:
        return None
    ncols = 2
    nrows = int(np.ceil(len(columns) / ncols))
    fig = make_subplots(rows=nrows, cols=ncols, subplot_titles=[c.upper() for c in columns])
    margin_coverage = coverage.get("margin_coverage", {})
    period_coverage = coverage.get("margin_period_coverage", {})
    for index, column in enumerate(columns):
        row, col = divmod(index, ncols)
        series = pd.to_numeric(margins[column], errors="coerce").dropna()
        if series.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=format_period_labels(series.index),
                y=series.values.tolist(),
                mode="lines+markers",
                line={"color": TREND_COLORWAY[index % len(TREND_COLORWAY)]},
                customdata=[
                    period_coverage.get(column, {}).get(
                        _period_label(period),
                        margin_coverage.get(column, coverage.get("reference_count", 0)),
                    )
                    for period in series.index
                ],
                hovertemplate=(
                    "%{x}<br>Marj: %{y:.2f}%<br>Karşılaştırılabilir şirket: %{customdata}"
                    "<extra>" + column + "</extra>"
                ),
                showlegend=False,
            ),
            row=row + 1,
            col=col + 1,
        )
        fig.add_hline(y=0, line_dash="dash", line_width=1, row=row + 1, col=col + 1)
        fig.update_xaxes(tickangle=45, automargin=True, row=row + 1, col=col + 1)
        fig.update_yaxes(ticksuffix="%", row=row + 1, col=col + 1)
    title = (
        "Sektör Kârlılık Marjları — Yıllıklandırılmış Toplamlar"
        f" | Referans kapsamı: {coverage.get('reference_count', 0)}/{coverage.get('successful_count', 0)} şirket"
    )
    apply_theme(fig, height=310 * nrows, title=title)
    style_subplot_titles(fig)
    return fig


def sector_options(project_root: Path) -> dict[str, Any]:
    temel_ozet_path = project_root / "temel_ozet.xlsx"
    temel_ozet = pd.read_excel(temel_ozet_path)
    sektor_list = temel_ozet["Sektör"].unique().tolist()
    disarida_birakilacaklar = [
        "Bankacılık",
        "Diğer",
        "Fin.Kiralama ve Faktoring",
        "Sigorta",
        "Varlık Yönetim",
        "Spor",
    ]
    yeni_liste = [s for s in sektor_list if s not in disarida_birakilacaklar]

    return {
        "sektorler": yeni_liste,
        "analiz_turu": ["TOPLAM", "MEDIAN"],
        "excel_kaydet": ["EVET", "HAYIR"],
    }


def run_sector_analysis(
    *,
    project_root: Path,
    outputs_dir: Path,
    sektor: str,
    analiz_turu: str,
    excel_durum: str,
    piotroski_hesapla: bool = False,
) -> RenderedOutput:
    total_started = time.perf_counter()
    nb_path = project_root / "Sektor Analizi.ipynb"
    rt = NotebookRuntime(nb_path, project_root=project_root, outputs_dir=outputs_dir)
    module_started = time.perf_counter()
    mod = rt.module()
    module_seconds = time.perf_counter() - module_started

    temel_ozet = pd.read_excel(project_root / "temel_ozet.xlsx")
    hisseler = temel_ozet.loc[temel_ozet["Sektör"] == sektor, "Kod"].tolist()

    if not hasattr(mod, "sektor_analizi"):
        raise RuntimeError("Notebook içinde `sektor_analizi` fonksiyonu bulunamadı.")
    if not hasattr(mod, "safe_filename"):
        raise RuntimeError("Notebook içinde `safe_filename` fonksiyonu bulunamadı.")

    data_started = time.perf_counter()
    sektor_df = mod.sektor_analizi(
        hisseler, analiz_turu, temel_ozet, piotroski_hesapla=piotroski_hesapla
    )
    data_seconds = time.perf_counter() - data_started
    failed_symbols = dict(sektor_df.attrs.get("failed_symbols", {}))
    successful_count = int(sektor_df.attrs.get("successful_count", 0))
    if successful_count == 0 or sektor_df.empty:
        detail = "; ".join(f"{code}: {message}" for code, message in failed_symbols.items())
        raise RuntimeError(f"Sektörde hiçbir hisse analiz edilemedi. {detail}".strip())

    sector_financials = _build_sector_financial_history(
        dict(sektor_df.attrs.get("company_histories", {})),
        dict(sektor_df.attrs.get("latest_financial_periods", {})),
        requested_symbols=hisseler,
    )
    sector_coverage = sector_financials["coverage"] if sector_financials else None

    output_started = time.perf_counter()
    display_sector_df = sektor_df.rename(columns=_DISPLAY_LABELS)
    tables: list[dict[str, str]] = [
        {
            "name": f"{sektor} Sektörü Analizi",
            "html": dataframe_to_html(display_sector_df),
        }
    ]

    if excel_durum == "EVET":
        kayit_klasoru = outputs_dir / "sektorler"
        kayit_klasoru.mkdir(parents=True, exist_ok=True)
        guvenli_sektor_adi = mod.safe_filename(sektor)
        dosya_yolu = kayit_klasoru / f"{guvenli_sektor_adi}.xlsx"
        write_formatted_excel(display_sector_df, dosya_yolu, index=True)

    # Prepare plot dataframe (exclude summary rows)
    sirket_plot_df = _prepare_plot_df(sektor_df)

    charts: list[dict[str, Any]] = []
    bar_fig = _plot_sector_bars(sirket_plot_df)
    if bar_fig is not None:
        charts.append(
            {
                "name": f"sektor_bar_{uuid.uuid4().hex[:10]}",
                "category": "bar",
                "figure": to_json_safe(bar_fig),
            }
        )
    heatmap_fig = _plot_sector_heatmaps(sirket_plot_df)
    if heatmap_fig is not None:
        charts.append(
            {
                "name": f"sektor_heatmap_{uuid.uuid4().hex[:10]}",
                "category": "heatmap",
                "figure": to_json_safe(heatmap_fig),
            }
        )
    if sector_financials is not None:
        sector_figures = (
            _plot_sector_annualized_changes(
                sector_financials["differences"], sector_financials["coverage"]
            ),
            _plot_sector_trend_index(
                sector_financials["trend"], sector_financials["coverage"]
            ),
            _plot_sector_margins(
                sector_financials["margins"], sector_financials["coverage"]
            ),
        )
        for figure in sector_figures:
            if figure is None:
                continue
            charts.append(
                {
                    "name": f"sektor_finansal_{uuid.uuid4().hex[:10]}",
                    "category": "sector_financials",
                    "figure": to_json_safe(figure),
                }
            )

    output_seconds = time.perf_counter() - output_started
    total_seconds = time.perf_counter() - total_started
    return RenderedOutput(
        tables=tables,
        charts=charts,
        meta={
            "sektor": sektor,
            "analiz_turu": analiz_turu,
            "excel_durum": excel_durum,
            "istenen_hisse_sayisi": len(hisseler),
            "basarili_hisse_sayisi": successful_count,
            "basarisiz_hisseler": failed_symbols,
            "sektor_donem_kapsami": sector_coverage,
            "rapor_bilgisi": _sector_report_metadata(sektor, analiz_turu),
            "piotroski_hesapla": piotroski_hesapla,
            "sureler_saniye": {
                "toplam": round(total_seconds, 2),
                "notebook_hazirlama": round(module_seconds, 2),
                "sirket_verileri_ve_fiyatlar": round(data_seconds, 2),
                "tablo_ve_grafikler": round(output_seconds, 2),
            },
        },
    )
