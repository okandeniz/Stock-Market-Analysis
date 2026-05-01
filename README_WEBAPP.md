## Web Uygulaması (FastAPI)

Bu proje, `Sektor Analizi.ipynb` ve `Sirket Analiz.ipynb` içindeki tabloları/grafikleri web üzerinden çalıştırıp göstermeyi amaçlar.

### Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Çalıştırma

```bash
uvicorn app.main:app --reload
```

Sonra tarayıcıdan `http://127.0.0.1:8000` açın.

### EVDS API Key

Şirket analizinde EVDS verisi kullanıldığı için API key gerekir:

- UI’daki **EVDS API Key** alanına girin, veya
- Ortam değişkeni olarak set edin:

```powershell
$env:EVDS_API_KEY="YOUR_KEY"
uvicorn app.main:app --reload
```

### Çıktılar

- Üretilen grafikler `static/outputs/` altına PNG olarak kaydedilir ve UI’da gösterilir.
- Sektör analizi “Excel Kaydı = EVET” seçilirse `sektorler/` altında `.xlsx` üretir.

