from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analysis_company import company_options, run_company_analysis
from .analysis_sector import run_sector_analysis, sector_options


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "static"
OUTPUTS_DIR = STATIC_DIR / "outputs"
TEMPLATES_DIR = PROJECT_ROOT / "templates"


app = FastAPI(title="Stock Market Analysis")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/sector/options")
def api_sector_options() -> dict:
    return sector_options(PROJECT_ROOT)


@app.post("/api/sector/run")
def api_sector_run(payload: dict) -> dict:
    try:
        sektor = str(payload.get("sektor", "")).strip()
        analiz_turu = str(payload.get("analiz_turu", "")).strip().upper()
        excel_durum = str(payload.get("excel_durum", "")).strip().upper()
        if not sektor:
            raise ValueError("sektor boş olamaz")
        if analiz_turu not in ("TOPLAM", "MEDIAN"):
            raise ValueError("analiz_turu TOPLAM/MEDIAN olmalı")
        if excel_durum not in ("EVET", "HAYIR"):
            raise ValueError("excel_durum EVET/HAYIR olmalı")

        out = run_sector_analysis(
            project_root=PROJECT_ROOT,
            outputs_dir=OUTPUTS_DIR,
            sektor=sektor,
            analiz_turu=analiz_turu,
            excel_durum=excel_durum,
        )
        return {"ok": True, "tables": out.tables, "images": out.images, "meta": out.meta}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/company/options")
def api_company_options() -> dict:
    return company_options()


@app.post("/api/company/run")
def api_company_run(payload: dict) -> dict:
    try:
        hisse = str(payload.get("hisse", "")).strip().upper()
        degerleme = str(payload.get("degerleme", "")).strip().upper()
        hazir_tahmin = payload.get("hazir_tahmin")
        hazir_tahmin = str(hazir_tahmin).strip().upper() if hazir_tahmin is not None else None
        evds_api_key = str(payload.get("evds_api_key", "")).strip() or None

        if not hisse.isalpha():
            raise ValueError("hisse sadece harf içermeli (örn: THYAO)")
        if degerleme not in ("EVET", "HAYIR"):
            raise ValueError("degerleme EVET/HAYIR olmalı")
        if degerleme == "EVET" and hazir_tahmin is None:
            raise ValueError("degerleme=EVET iken hazir_tahmin zorunlu")

        out = run_company_analysis(
            project_root=PROJECT_ROOT,
            outputs_dir=OUTPUTS_DIR,
            hisse=hisse,
            degerleme=degerleme,
            hazir_tahmin=hazir_tahmin,
            evds_api_key=evds_api_key,
        )
        return {"ok": True, "tables": out.tables, "images": out.images, "meta": out.meta}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e

