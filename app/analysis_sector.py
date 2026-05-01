from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .notebook_runtime import NotebookRuntime, RenderedOutput

# Columns for bar charts (absolute values)
_BAR_COLS = [
    "PD",
    "FD",
    "Satış Gelirleri",
    "Net Faaliyet Kar/Zararı",
    "FAVÖK",
    "Ana Ortaklık Payları",
]

# Columns for heatmap charts (ratios)
_RATIO_COLS = [
    "F/K",
    "FD/FAVÖK",
    "FD/NS",
    "PD/DD",
    "NFK/PD_%",
    "iskonto_%",
]

# Columns where a higher value is better (for heatmap coloring)
_HIGH_IS_GOOD = {"NFK/PD_%"}


def _prepare_plot_df(sektor_df: pd.DataFrame) -> pd.DataFrame:
    """Sektör toplamı/medyanı satırlarını kaldır, sayısal dönüşüm yap."""
    ozel = {"SEKTÖR TOPLAM", "SEKTÖR Median"}
    df = sektor_df.loc[~sektor_df.index.isin(ozel)].copy()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="ignore")
    return df


def _plot_sector_bars(sirket_df: pd.DataFrame) -> None:
    """Bar grafikleri oluşturur ve plt.show() çağırır."""
    bar_cols = [c for c in _BAR_COLS if c in sirket_df.columns]
    if not bar_cols:
        return

    ncols = 2
    nrows = (len(bar_cols) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(24, 5 * nrows))
    axes_flat = np.array(axes).flatten()

    for i, col in enumerate(bar_cols):
        ax = axes_flat[i]
        data = (
            sirket_df[col]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_values(ascending=False)
        )
        bars = ax.bar(data.index, data.values, color="#6DB432", edgecolor="#8BC064", linewidth=0.5)
        ax.set_title(col, fontsize=14, fontweight="bold")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(axis="y", alpha=0.3)

        for j, v in enumerate(data.values):
            ax.text(
                j,
                v,
                f"{v:,.0f}",
                ha="center",
                va="bottom" if v >= 0 else "top",
                fontsize=7,
                rotation=90,
            )

    for j in range(len(bar_cols), len(axes_flat)):
        fig.delaxes(axes_flat[j])

    plt.suptitle("Sektör — Mutlak Değer Grafikleri", fontsize=16, fontweight="bold", y=1.01)
    plt.tight_layout()
    plt.show()


def _plot_sector_heatmaps(sirket_df: pd.DataFrame) -> None:
    """Heatmap grafikleri oluşturur ve plt.show() çağırır."""
    ratio_cols = [c for c in _RATIO_COLS if c in sirket_df.columns]
    if not ratio_cols:
        return

    n = len(ratio_cols)
    fig, axes = plt.subplots(n, 1, figsize=(24, 4 * n))
    if n == 1:
        axes = [axes]

    cmap_low = plt.cm.get_cmap("RdYlGn_r")   # düşük değer iyi
    cmap_high = plt.cm.get_cmap("RdYlGn")    # yüksek değer iyi

    for i, col in enumerate(ratio_cols):
        ax = axes[i]
        series = pd.to_numeric(sirket_df[col], errors="coerce").dropna()

        if series.empty:
            ax.set_title(col, fontsize=14, fontweight="bold")
            ax.axis("off")
            continue

        vals = series.values.astype(float).reshape(1, -1)
        vmin = np.nanpercentile(vals, 5)
        vmax = np.nanpercentile(vals, 95)
        if vmin == vmax:
            vmin -= 1
            vmax += 1

        cmap = cmap_high if col in _HIGH_IS_GOOD else cmap_low
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

        img = ax.imshow(vals, aspect="auto", cmap=cmap, norm=norm)
        ax.set_title(col, fontsize=14, fontweight="bold")
        ax.set_yticks([])
        ax.set_xticks(np.arange(len(series)))
        ax.set_xticklabels(series.index, rotation=45, ha="right", fontsize=10)

        for j, v in enumerate(series.values):
            if pd.notna(v):
                rgba = cmap(norm(v))
                lum = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
                tc = "black" if lum > 0.6 else "white"
                ax.text(j, 0, f"{v:.2f}", ha="center", va="center",
                        color=tc, fontsize=10, fontweight="bold")
            else:
                ax.text(j, 0, "NaN", ha="center", va="center",
                        color="gray", fontsize=9)

        plt.colorbar(img, ax=ax, fraction=0.018, pad=0.01)

    plt.suptitle("Sektör — Çarpan / Oran Heatmapları", fontsize=16, fontweight="bold", y=1.005)
    plt.tight_layout()
    plt.show()


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
) -> RenderedOutput:
    nb_path = project_root / "Sektor Analizi.ipynb"
    rt = NotebookRuntime(nb_path, project_root=project_root, outputs_dir=outputs_dir)
    mod = rt.module()

    temel_ozet = pd.read_excel(project_root / "temel_ozet.xlsx")
    hisseler = temel_ozet.loc[temel_ozet["Sektör"] == sektor, "Kod"].tolist()

    if not hasattr(mod, "sektor_analizi"):
        raise RuntimeError("Notebook içinde `sektor_analizi` fonksiyonu bulunamadı.")
    if not hasattr(mod, "safe_filename"):
        raise RuntimeError("Notebook içinde `safe_filename` fonksiyonu bulunamadı.")

    sektor_df = mod.sektor_analizi(hisseler, analiz_turu, temel_ozet)

    tables: list[dict[str, str]] = [
        {
            "name": f"{sektor} Sektörü Analizi",
            "html": sektor_df.to_html(
                index=True,
                escape=False,
                border=0,
                classes="data-table",
            ),
        }
    ]

    if excel_durum == "EVET":
        kayit_klasoru = project_root / "sektorler"
        kayit_klasoru.mkdir(parents=True, exist_ok=True)
        guvenli_sektor_adi = mod.safe_filename(sektor)
        dosya_yolu = kayit_klasoru / f"{guvenli_sektor_adi}.xlsx"
        sektor_df.to_excel(dosya_yolu, index=True)

    # Prepare plot dataframe (exclude summary rows)
    sirket_plot_df = _prepare_plot_df(sektor_df)

    cleanup, snapshot = rt.with_matplotlib_saver(request_id="sector", prefix="sektor")
    try:
        _plot_sector_bars(sirket_plot_df)
        snapshot("bar")
        _plot_sector_heatmaps(sirket_plot_df)
        snapshot("heatmap")
    finally:
        images = cleanup()

    return RenderedOutput(
        tables=tables,
        images=images,
        meta={
            "sektor": sektor,
            "analiz_turu": analiz_turu,
            "excel_durum": excel_durum,
            "hisse_sayisi": len(hisseler),
        },
    )
