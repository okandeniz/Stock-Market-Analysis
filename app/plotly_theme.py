"""Shared Plotly theming helpers so charts match the web app's dark UI.

Used both by app/analysis_sector.py (plain Python) and by the plot functions
that live inside the notebooks (imported as `app.plotly_theme`, since the
notebook code is exec'd with the project root on sys.path).
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import pandas as pd

CARD_BG = "#353537"
GRID_COLOR = "rgba(255,255,255,0.09)"
TEXT_COLOR = "#f0f0f0"
MUTED_COLOR = "#B0B0B2"
ACCENT = "#6DB432"
ACCENT_H = "#8BC064"
UP_COLOR = "#6DB432"
DOWN_COLOR = "#ff6b6b"

# Diverging colorscale used for ratio/multiple heatmaps ("düşük iyi").
COLORSCALE_LOW_GOOD = "RdYlGn_r"
# Same scale, reversed, for metrics where a higher value is better.
COLORSCALE_HIGH_GOOD = "RdYlGn"

X_TICK_FONT = {"color": TEXT_COLOR, "size": 11, "family": "Arial"}
Y_TICK_FONT = {"color": MUTED_COLOR, "size": 10}

# Çok sayıda seriyi tek grafikte (örn. trend endeksi) ayırt edilebilir şekilde
# göstermek için koyu temayla uyumlu, birbirinden belirgin renk paleti.
TREND_COLORWAY = [
    "#6DB432", "#ff6b6b", "#4aa3ff", "#f0c040", "#B18CFF",
    "#ff8c42", "#40E0D0", "#FF69B4", "#FFD700", "#00CED1",
    "#FF4500", "#ADFF2F", "#1E90FF", "#DA70D6", "#C0C0C0",
]


def format_period_label(value: Any) -> str:
    """Format a period as MM/YYYY (ör. 06/2026). Non-dates pass through as text."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return str(value)
    return f"{timestamp.month:02d}/{timestamp.year}"


def format_period_labels(values: Iterable[Any]) -> list[str]:
    """Format many axis/period values as MM/YYYY labels."""
    return [format_period_label(value) for value in values]


def heatmap_vertical_spacing(n_rows: int) -> float:
    """Leave readable gaps between stacked heatmaps without exceeding Plotly limits."""
    if n_rows <= 1:
        return 0.0
    # Plotly requires vertical_spacing <= 1 / (rows - 1).
    return float(min(0.08, 0.55 / n_rows, 0.95 / (n_rows - 1)))


def style_heatmap_xaxes(fig: Any) -> None:
    """Angled white period labels with automargin so titles stay clear."""
    fig.update_xaxes(
        tickangle=45,
        tickfont=X_TICK_FONT,
        automargin=True,
        title_standoff=8,
    )


def apply_theme(fig: Any, *, height: int | None = None, title: str | None = None) -> None:
    """Apply the app's dark theme to a Plotly figure, in place."""
    layout_kwargs: dict[str, Any] = {
        "paper_bgcolor": CARD_BG,
        "plot_bgcolor": CARD_BG,
        "font": {"color": TEXT_COLOR, "size": 12},
        "margin": {"l": 60, "r": 30, "t": 60, "b": 80},
        "legend": {"bgcolor": "rgba(0,0,0,0)"},
    }
    if height is not None:
        layout_kwargs["height"] = height
    if title is not None:
        layout_kwargs["title"] = {"text": title, "font": {"size": 18, "color": TEXT_COLOR}}
    fig.update_layout(**layout_kwargs)

    fig.update_xaxes(
        gridcolor=GRID_COLOR,
        zerolinecolor=GRID_COLOR,
        linecolor=GRID_COLOR,
        tickfont=X_TICK_FONT,
        tickangle=45,
        # "Jun 1, 2026" yerine dönem etiketi; kategori eksenlerinde etkisizdir.
        tickformat="%m/%Y",
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor=GRID_COLOR,
        zerolinecolor=GRID_COLOR,
        linecolor=GRID_COLOR,
        tickfont=Y_TICK_FONT,
    )


def style_subplot_titles(fig: Any) -> None:
    """Subplot titles (from make_subplots' subplot_titles=) render as annotations."""
    for ann in fig.layout.annotations:
        ann.font = {"size": 13, "color": TEXT_COLOR, "weight": "bold"}


def format_tr_number(value: Any, decimals: int = 0, suffix: str = "") -> str:
    """Format a number Türkçe (Turkish) style: '.' binlik ayıracı, ',' ondalık ayıracı.

    Örnek: 1415644.5 -> "1.415.645" (decimals=0) veya "1.415.644,50" (decimals=2).
    Grafiklerdeki hover metinlerinde ham/kısaltılmış (1.4B gibi) sayılar yerine
    tam ve net değer göstermek için kullanılır.
    """
    if value is None:
        return "—"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(value) or math.isinf(value):
        return "—"

    formatted = f"{value:,.{decimals}f}"
    # "1,234,567.89" -> "1.234.567,89" (ABD biçiminden Türkçe biçime çevirir)
    formatted = formatted.replace(",", "\u0000").replace(".", ",").replace("\u0000", ".")
    return f"{formatted}{suffix}"


def to_json_safe(fig: Any) -> dict[str, Any]:
    """Convert a Plotly figure into a plain JSON-serializable dict (numpy/Timestamp safe)."""
    import json

    import plotly.utils

    return json.loads(json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder))
