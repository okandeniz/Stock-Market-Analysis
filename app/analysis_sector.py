from __future__ import annotations

import uuid
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .notebook_runtime import NotebookRuntime, RenderedOutput
from .plotly_theme import (
    COLORSCALE_HIGH_GOOD,
    COLORSCALE_LOW_GOOD,
    UP_COLOR,
    apply_theme,
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
                marker=dict(color=UP_COLOR, line=dict(color="#8BC064", width=0.5)),
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
            "piotroski_hesapla": piotroski_hesapla,
            "sureler_saniye": {
                "toplam": round(total_seconds, 2),
                "notebook_hazirlama": round(module_seconds, 2),
                "sirket_verileri_ve_fiyatlar": round(data_seconds, 2),
                "tablo_ve_grafikler": round(output_seconds, 2),
            },
        },
    )
