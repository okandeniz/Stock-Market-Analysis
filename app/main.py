from __future__ import annotations

import logging
import re
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
logger = logging.getLogger(__name__)


app = FastAPI(title="Finansal Mercek")
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
        piotroski_hesapla = payload.get("piotroski_hesapla", False)
        if not isinstance(piotroski_hesapla, bool):
            raise ValueError("piotroski_hesapla boolean olmalı")
        if not sektor:
            raise ValueError("sektor boş olamaz")
        if sektor not in sector_options(PROJECT_ROOT)["sektorler"]:
            raise ValueError("geçersiz sektör seçimi")
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
            piotroski_hesapla=piotroski_hesapla,
        )
        return {"ok": True, "tables": out.tables, "charts": out.charts, "meta": out.meta}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("Sektör analizi beklenmeyen bir hatayla durdu")
        raise HTTPException(status_code=500, detail="Sektör analizi tamamlanamadı.") from e


@app.get("/api/company/options")
def api_company_options() -> dict:
    return company_options()


@app.post("/api/company/run")
def api_company_run(payload: dict) -> dict:
    try:
        hisse = str(payload.get("hisse", "")).strip().upper()
        degerleme = str(payload.get("degerleme", "")).strip().upper()

        if not re.fullmatch(r"[A-Z]{1,10}", hisse):
            raise ValueError("hisse 1-10 ASCII harften oluşmalı (örn: THYAO)")
        if degerleme not in ("EVET", "HAYIR"):
            raise ValueError("degerleme EVET/HAYIR olmalı")
        out = run_company_analysis(
            project_root=PROJECT_ROOT,
            outputs_dir=OUTPUTS_DIR,
            hisse=hisse,
            degerleme=degerleme,
        )
        return {"ok": True, "tables": out.tables, "charts": out.charts, "meta": out.meta}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("Şirket analizi beklenmeyen bir hatayla durdu")
        raise HTTPException(status_code=500, detail="Şirket analizi tamamlanamadı.") from e
