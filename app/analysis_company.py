from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .notebook_runtime import NotebookRuntime, RenderedOutput


def _to_html(obj: Any) -> str:
    """DataFrame veya dict'i HTML tablosuna dönüştürür."""
    if isinstance(obj, pd.DataFrame):
        return obj.to_html(index=False, border=0, classes="data-table")
    return pd.DataFrame([obj]).to_html(index=False, border=0, classes="data-table")


def _score_summary_html(total_score: Any, signal: str) -> str:
    """Toplam skor + sinyal için renkli HTML tablo üretir."""
    signal_colors = {
        "Çok Güçlü": "#6DB432",
        "Güçlü":     "#8BC064",
        "Nötr":      "#f0c040",
        "Zayıf":     "#ff8c42",
        "Çok Zayıf": "#ff6b6b",
    }
    score_text = f"{total_score:.2f} / 100" if isinstance(total_score, (int, float)) else "—"
    color = signal_colors.get(signal, "#7B7B7D")
    return (
        '<table border="0" class="data-table">'
        "<thead><tr>"
        '<th style="text-align:left">Toplam Skor</th>'
        '<th style="text-align:left">Sinyal</th>'
        "</tr></thead>"
        "<tbody><tr>"
        f'<td style="text-align:left;font-size:20px;font-weight:700;color:#f0f0f0">{score_text}</td>'
        f'<td style="text-align:left;font-size:16px;font-weight:700;color:{color}">{signal}</td>'
        "</tr></tbody>"
        "</table>"
    )


def company_options() -> dict[str, Any]:
    return {
        "degerleme": ["EVET", "HAYIR"],
        "hazir_tahmin": ["EVET", "HAYIR"],
    }


def run_company_analysis(
    *,
    project_root: Path,
    outputs_dir: Path,
    hisse: str,
    degerleme: str,
    hazir_tahmin: str | None,
    evds_api_key: str | None,
) -> RenderedOutput:
    nb_path = project_root / "Sirket Analiz.ipynb"
    rt = NotebookRuntime(nb_path, project_root=project_root, outputs_dir=outputs_dir)
    mod = rt.module()

    required = [
        "bilanco_cekme",
        "gelir_tablosu",
        "bilanco_yillik",
        "oran_rasyo_hesaplama",
        "TUFE_alma",
        "donemlik_fark",
        "waterfall_subplots_readable",
        "degisim_plot",
        "karlılık_plot",
        "denge_plot",
        "liktide_plot",
        "yeterlik_plot",
        "plot_nakit_akimi",
        "plot_degerleme_dashboard",
        "financial_scorecard",
    ]
    for fn in required:
        if not hasattr(mod, fn):
            raise RuntimeError(f"Notebook içinde `{fn}` fonksiyonu bulunamadı.")

    api_key = (evds_api_key or os.getenv("EVDS_API_KEY") or "").strip()

    # EVDS API Key yalnızca TUFE istatistiksel olarak tahmin edilecekse zorunludur.
    # Diğer tüm senaryolarda opsiyoneldir.
    tufe_needs_evds = degerleme == "EVET" and hazir_tahmin == "HAYIR"
    if tufe_needs_evds and not api_key:
        raise RuntimeError(
            "TUFE istatistiksel tahmini için EVDS API Key gerekli. "
            "UI'dan girin veya ortam değişkeni `EVDS_API_KEY` ayarlayın."
        )

    cleanup, snapshot = rt.with_matplotlib_saver(request_id="company", prefix="sirket")
    try:
        df_bilanco = mod.bilanco_cekme([hisse])
        gelir_tab_yil = mod.gelir_tablosu(df_bilanco, ceyrek=False, yillik=True)
        new_df = mod.bilanco_yillik(df_bilanco, gelir_tab_yil)
        df = mod.oran_rasyo_hesaplama(new_df, hisse)

        # API Key varsa EVDS'den TUFE çek ve df ile birleştir.
        has_tufe = False
        if api_key:
            makro_data = mod.TUFE_alma(df, api_key)
            df = df.merge(makro_data, how="inner", left_index=True, right_index=True)
            base_tufe = df["TUFE"].iloc[0]
            df["Satış Gelirleri_reel"] = df["Satış Gelirleri"] * (base_tufe / df["TUFE"])
            has_tufe = True

        df_fark = mod.donemlik_fark(df_bilanco)
        mod.waterfall_subplots_readable(df_fark)
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
        ]
        df_karlilik = df[[c for c in karlilik_cols if c in df.columns]]
        mod.karlılık_plot(df_karlilik)
        snapshot("karlılık")

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
        ]
        df_likitide = df[[c for c in likitide_cols if c in df.columns]]
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

        df_gelecek_donem = None
        if degerleme == "EVET" and len(df) >= 13:
            if hazir_tahmin not in ("EVET", "HAYIR"):
                raise RuntimeError("`hazir_tahmin` seçimi EVET/HAYIR olmalı.")

            if not hasattr(mod, "TUFE_alma_2") or not hasattr(mod, "forecast_model_secici"):
                raise RuntimeError(
                    "Değerleme için gerekli `TUFE_alma_2` veya `forecast_model_secici` notebook içinde yok."
                )
            if not hasattr(mod, "conditional_mean"):
                raise RuntimeError("Değerleme için gerekli `conditional_mean` notebook içinde yok.")

            # TUFE exog'u yalnızca tarihsel TUFE verisi mevcutsa kullan.
            use_exog = has_tufe
            future_exog_1: pd.DataFrame | None = None
            future_exog_2: pd.DataFrame | None = None

            if hazir_tahmin == "EVET":
                tufe_tahmin = pd.read_csv(project_root / "tufe_tahmin.csv")
                tufe_tahmin.set_index("Unnamed: 0", inplace=True)
                tufe_tahmin.index = pd.to_datetime(tufe_tahmin.index)

                if has_tufe:
                    # Tarihsel TUFE mevcut → CSV tahmin değerleriyle tamamla
                    if "TUFE Tahmin" in tufe_tahmin.columns:
                        df["TUFE"] = df["TUFE"].combine_first(tufe_tahmin["TUFE Tahmin"])
                    if "Log TUFE Tahmin" in tufe_tahmin.columns:
                        df["log_TUFE"] = df["log_TUFE"].combine_first(tufe_tahmin["Log TUFE Tahmin"])

                last_month = df.index[-1].month
                if last_month == 12:
                    n_steps = 4
                elif last_month == 9:
                    n_steps = 1
                elif last_month == 6:
                    n_steps = 2
                elif last_month == 3:
                    n_steps = 3
                else:
                    raise ValueError(f"Beklenmeyen finansal dönem ayı: {last_month}")

                if use_exog:
                    future_tufe = tufe_tahmin.tail(n_steps)
                    future_exog_1 = pd.DataFrame(
                        {"log_TUFE": future_tufe["Log TUFE Tahmin"].values},
                        index=future_tufe.index,
                    )
                    future_exog_2 = pd.DataFrame(
                        {"TUFE": future_tufe["TUFE Tahmin"].values},
                        index=future_tufe.index,
                    )

            else:
                # hazir_tahmin == "HAYIR" → API Key zorunlu, TUFE EVDS'den tahmin edilir
                makro_data2 = mod.TUFE_alma_2(df, api_key)
                tufe_sonuc = mod.forecast_model_secici(
                    df=makro_data2,
                    col="TUFE",
                    freq="QS-MAR",
                    test_size=0.20,
                    log=True,
                    trend_options=("t", "ct"),
                )
                tufe_tahmin = tufe_sonuc["future_forecast"]
                tufe_tahmin.index = pd.to_datetime(tufe_tahmin.index)
                future_exog_1 = pd.DataFrame(
                    {"log_TUFE": tufe_tahmin["Log TUFE Tahmin"].values}, index=tufe_tahmin.index
                )
                future_exog_2 = pd.DataFrame(
                    {"TUFE": tufe_tahmin["TUFE Tahmin"].values}, index=tufe_tahmin.index
                )

            satis_geliri_sonuc = mod.forecast_model_secici(
                df=df,
                col="Satış Gelirleri",
                exog_df=df if use_exog else None,
                exog_cols=["log_TUFE"] if use_exog else None,
                future_exog=future_exog_1,
                freq="QS-MAR",
                test_size=0.20,
                log=True,
                trend_options=("t", "ct"),
            )
            satis_geliri_tahmin = satis_geliri_sonuc["future_forecast"]

            net_kar_marji_sonuc = mod.forecast_model_secici(
                df=df,
                col="net_kar_marjı_%",
                exog_df=df if use_exog else None,
                exog_cols=["TUFE"] if use_exog else None,
                future_exog=future_exog_2,
                freq="QS-MAR",
                test_size=0.20,
                log=False,
                trend_options=("t", "ct"),
            )
            favok_marji_sonuc = mod.forecast_model_secici(
                df=df,
                col="favok_marjı_%",
                exog_df=df if use_exog else None,
                exog_cols=["TUFE"] if use_exog else None,
                future_exog=future_exog_2,
                freq="QS-MAR",
                test_size=0.20,
                log=False,
                trend_options=("t", "ct"),
            )
            net_borc_favok_sonuc = mod.forecast_model_secici(
                df=df,
                col="net_borc/FAVOK",
                exog_df=df if use_exog else None,
                exog_cols=["TUFE"] if use_exog else None,
                future_exog=future_exog_2,
                freq="QS-MAR",
                test_size=0.20,
                log=False,
                trend_options=("t", "ct"),
            )

            # Tahmin grafiklerini değerleme olarak etiketle
            snapshot("değerleme")

            df_join_tahmin = (
                satis_geliri_tahmin.join(tufe_tahmin, how="left")
                .join(net_kar_marji_sonuc["future_forecast"], how="left")
                .join(favok_marji_sonuc["future_forecast"], how="left")
                .join(net_borc_favok_sonuc["future_forecast"], how="left")
            )

            idx = df_join_tahmin.index[-1]
            df_gelecek_donem = pd.DataFrame(index=[idx])
            df_gelecek_donem["Satis_Geliri_tahmin"] = df_join_tahmin.loc[idx, "Satış Gelirleri Tahmin"]
            df_gelecek_donem["net_kar_marjı_% Tahmin"] = df_join_tahmin.loc[
                idx, "net_kar_marjı_% Tahmin"
            ]
            df_gelecek_donem["favok_marjı_% Tahmin"] = df_join_tahmin.loc[idx, "favok_marjı_% Tahmin"]
            df_gelecek_donem["net_borc/FAVOK Tahmin"] = df_join_tahmin.loc[idx, "net_borc/FAVOK Tahmin"]

            df_gelecek_donem["Net_Kar_Tahmini"] = (
                df_gelecek_donem["Satis_Geliri_tahmin"] * df_gelecek_donem["net_kar_marjı_% Tahmin"] / 100
            )
            df_gelecek_donem["FAVOK_Tahmini"] = (
                df_gelecek_donem["Satis_Geliri_tahmin"] * df_gelecek_donem["favok_marjı_% Tahmin"] / 100
            )
            df_gelecek_donem["Ozkaynak_Tahmini"] = (
                df.loc[df.index[-1], "  Ana Ortaklığa Ait Özkaynaklar"] + df_gelecek_donem["Net_Kar_Tahmini"]
            )
            df_gelecek_donem["net_borc Tahmin"] = (
                df_gelecek_donem["FAVOK_Tahmini"] * df_gelecek_donem["net_borc/FAVOK Tahmin"]
            )

            df_gelecek_donem["F/K Median"] = mod.conditional_mean(df["F/K"].dropna())
            df_gelecek_donem["PD/DD Median"] = mod.conditional_mean(df["PD/DD"].dropna())
            df_gelecek_donem["FD/FAVÖK Median"] = mod.conditional_mean(df["FD/FAVÖK"].dropna())
            df_gelecek_donem["PD/NS Median"] = mod.conditional_mean(df["PD/NS"].dropna())

            sermaye = df.loc[df.index[-1], "  Ödenmiş Sermaye"]
            df_gelecek_donem["Tahmini HBK"] = df_gelecek_donem["Net_Kar_Tahmini"] / sermaye
            df_gelecek_donem["F/K Fiyat Tahmini"] = df_gelecek_donem["F/K Median"] * df_gelecek_donem["Tahmini HBK"]
            df_gelecek_donem["PD/DD Fiyat Tahmini"] = (
                df_gelecek_donem["PD/DD Median"] * df_gelecek_donem["Ozkaynak_Tahmini"]
            ) / sermaye
            df_gelecek_donem["FD/FAVÖK Fiyat Tahmini"] = (
                (df_gelecek_donem["FAVOK_Tahmini"] * df_gelecek_donem["FD/FAVÖK Median"])
                - df_gelecek_donem["net_borc Tahmin"]
            ) / sermaye
            df_gelecek_donem["PD/NS Fiyat Tahmini"] = (
                (df_gelecek_donem["Satis_Geliri_tahmin"] / sermaye) * df_gelecek_donem["PD/NS Median"]
            )
            df_gelecek_donem["Ortalama Tahmin"] = df_gelecek_donem[
                ["F/K Fiyat Tahmini", "PD/DD Fiyat Tahmini", "FD/FAVÖK Fiyat Tahmini", "PD/NS Fiyat Tahmini"]
            ].mean(axis=1)

            df_gelecek_donem["fiyat"] = df.loc[df.index[-1], "duzeltilmis_fiyat"]
            df_gelecek_donem["iskonto_%"] = ((df_gelecek_donem["Ortalama Tahmin"] / df_gelecek_donem["fiyat"]) - 1) * 100

            conditions = [
                (df_gelecek_donem["iskonto_%"] >= 20),
                (df_gelecek_donem["iskonto_%"].between(10, 20)),
                (df_gelecek_donem["iskonto_%"].between(-10, 10)),
                (df_gelecek_donem["iskonto_%"].between(-20, -10)),
                (df_gelecek_donem["iskonto_%"] < -20),
            ]
            choices = ["iskontolu", "az değerli", "adil", "biraz yüksek", "pahalı"]
            df_gelecek_donem["durum"] = np.select(conditions, choices, default="belirsiz")

    finally:
        images = cleanup()

    tables: list[dict[str, str]] = [
        {
            "name": "Dönemsel Farklar (Şelale)",
            "category": "büyüme",
            "html": df_fark.to_html(index=True, border=0, classes="data-table"),
        },
        {
            "name": "Büyüme Oranları",
            "category": "büyüme",
            "html": degisimler_df.to_html(index=True, border=0, classes="data-table"),
        },
        {
            "name": "Kar Marjları",
            "category": "karlılık",
            "html": df_karlilik.to_html(index=True, border=0, classes="data-table"),
        },
        {
            "name": "Bilanço Dengesi",
            "category": "bilanço",
            "html": df_denge.to_html(index=True, border=0, classes="data-table"),
        },
        {
            "name": "Likidite",
            "category": "likidite",
            "html": df_likitide.to_html(index=True, border=0, classes="data-table"),
        },
        {
            "name": "Nakit Döngüsü",
            "category": "verimlilik",
            "html": df_yeterlik.to_html(index=True, border=0, classes="data-table"),
        },
        {
            "name": "Nakit Akımı",
            "category": "nakit",
            "html": df_nakit_akimi.to_html(index=True, border=0, classes="data-table"),
        },
        {
            "name": "Çarpanlar",
            "category": "değerleme",
            "html": df_degerleme.to_html(index=True, border=0, classes="data-table"),
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
    ]

    if df_gelecek_donem is not None:
        tables.append(
            {
                "name": "Gelecek Dönem Değerleme",
                "category": "değerleme",
                "html": df_gelecek_donem.to_html(index=True, border=0, classes="data-table"),
            }
        )

    return RenderedOutput(
        tables=tables,
        images=images,
        meta={
            "hisse": hisse,
            "degerleme": degerleme,
            "hazir_tahmin": hazir_tahmin,
            "rows": int(len(df)),
        },
    )
