import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np


_HTTP_CACHE_TTL_SECONDS = 300.0
_http_local = threading.local()
_http_cache_lock = threading.RLock()
_http_cache = {}
_http_concurrency = threading.BoundedSemaphore(8)


def _session():
    """Her sektör iş parçacığı için bağlantı havuzu yeniden kullan."""
    session = getattr(_http_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(
            {"User-Agent": "Finansal-Mercek/1.0 (+financial-analysis)"}
        )
        _http_local.session = session
    return session


def _cache_key(kind, url, params):
    if isinstance(params, dict):
        frozen_params = tuple(sorted(params.items()))
    else:
        frozen_params = tuple(params or ())
    return kind, url, frozen_params


def _cache_get(key):
    now = time.monotonic()
    with _http_cache_lock:
        cached = _http_cache.get(key)
        if cached is None:
            return None
        created_at, value = cached
        if now - created_at > _HTTP_CACHE_TTL_SECONDS:
            _http_cache.pop(key, None)
            return None
        return value


def _cache_put(key, value):
    with _http_cache_lock:
        _http_cache[key] = (time.monotonic(), value)


def clear_http_cache():
    """Testler ve elle yenileme gereken durumlar için süreç içi önbelleği temizle."""
    with _http_cache_lock:
        _http_cache.clear()


def _get_with_retry(url, params=None, retries=4, backoff=1.5, timeout=20):
    """Sektör analizinde birden fazla hisse eşzamanlı (ThreadPoolExecutor) olarak
    çekildiğinde isyatirim.com.tr üzerindeki yük artıyor ve zaman zaman
    zaman aşımına (Read timed out) veya geçici hatalara yol açıyor. Bu fonksiyon
    kısa bir üstel geri çekilme (exponential backoff) ile yeniden dener.
    """
    key = _cache_key("response", url, params)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    last_err = None
    for attempt in range(retries):
        try:
            with _http_concurrency:
                resp = _session().get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            _cache_put(key, resp)
            return resp
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff * (2**attempt))
    raise RuntimeError(
        f"isyatirim.com.tr'ye bağlanılamadı ({retries} deneme sonrası): {last_err}"
    ) from last_err


def _get_json_with_retry(url, params, retries=4, backoff=1.5, timeout=20):
    """isyatirim.com.tr API'si zaman zaman boş/geçersiz gövde döndürebiliyor
    (rate limit veya geçici kesinti). Bu durumda `.json()` çağrısı
    'Expecting value: line 1 column 1 (char 0)' hatası fırlatır. Bu fonksiyon
    kısa bir üstel geri çekilme (exponential backoff) ile yeniden dener.
    """
    key = _cache_key("json", url, params)
    cached = _cache_get(key)
    if cached is not None:
        return copy.deepcopy(cached)

    last_err = None
    for attempt in range(retries):
        try:
            with _http_concurrency:
                resp = _session().get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            value = resp.json()["value"]
            _cache_put(key, value)
            return copy.deepcopy(value)
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff * (2**attempt))
    raise RuntimeError(
        f"isyatirim.com.tr'den veri alınamadı ({retries} deneme sonrası): {last_err}"
    ) from last_err


def bilanco_cekme(hisseler):
    symbols = [str(symbol).strip().upper() for symbol in hisseler if str(symbol).strip()]
    if len(symbols) != 1:
        raise ValueError("bilanco_cekme her çağrıda tam olarak bir hisse bekler.")
    hisse = symbols[0]

    url1 = "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/sirket-karti.aspx?hisse=" + hisse
    soup = BeautifulSoup(_get_with_retry(url1).text, "html.parser")
    period_select = soup.find("select", id="ddlMaliTabloFirst")
    group_select = soup.find("select", id="ddlMaliTabloGroup")
    if period_select is None or group_select is None:
        raise RuntimeError(f"{hisse} için mali tablo seçim alanları bulunamadı.")

    group_option = group_select.find("option")
    if group_option is None or not group_option.get("value"):
        raise RuntimeError(f"{hisse} için mali tablo grubu bulunamadı.")
    grup = group_option["value"]

    period_labels = []
    for option in period_select.find_all("option"):
        label = option.get_text(strip=True)
        parts = label.split("/")
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            period_labels.append(label)
    if len(period_labels) < 4:
        raise RuntimeError(f"{hisse} için en az dört mali dönem bulunamadı.")

    url2 = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
    descriptions = None
    period_frames = []
    complete_period_count = len(period_labels) - (len(period_labels) % 4)

    def fetch_period_chunk(offset):
        chunk = period_labels[offset : offset + 4]
        params = [
            ("companyCode", hisse),
            ("exchange", "TRY"),
            ("financialGroup", grup),
        ]
        for position, label in enumerate(chunk, start=1):
            year, period = label.split("/")
            params.extend(((f"year{position}", year), (f"period{position}", period)))
        raw = pd.DataFrame.from_dict(_get_json_with_retry(url2, tuple(params)))
        return offset, chunk, raw

    offsets = list(range(0, complete_period_count, 4))
    # Dönem paketleri birbirinden bağımsızdır. Tek şirket analizinde dört
    # bağlantıya kadar paralel indirme soğuk başlangıcı belirgin kısaltır;
    # süreç genelindeki semaphore sektör analizinde toplam bağlantı sayısını 8
    # ile sınırlar ve veri kaynağını aşırı yüklemeyi önler.
    with ThreadPoolExecutor(
        max_workers=min(4, len(offsets)) or 1,
        thread_name_prefix="balance-sheet",
    ) as executor:
        fetched_chunks = list(executor.map(fetch_period_chunk, offsets))

    for _, chunk, raw in sorted(fetched_chunks, key=lambda item: item[0]):
        if raw.empty or "itemDescTr" not in raw.columns:
            raise RuntimeError(f"{hisse} için {chunk[0]}–{chunk[-1]} dönem verisi geçersiz.")
        if descriptions is None:
            descriptions = raw["itemDescTr"].reset_index(drop=True).rename("Bilanço")

        values = raw.drop(columns=["itemCode", "itemDescTr", "itemDescEng"], errors="ignore")
        if values.shape[1] < len(chunk):
            raise RuntimeError(f"{hisse} için {chunk[0]}–{chunk[-1]} dönem değerleri eksik.")
        values = values.iloc[:, : len(chunk)].reset_index(drop=True)
        values.columns = chunk
        period_frames.append(values)

    if descriptions is None or not period_frames:
        raise RuntimeError(f"{hisse} için mali tablo verisi oluşturulamadı.")

    veri3 = pd.concat([descriptions, *period_frames], axis=1)
    value_columns = [column for column in veri3.columns if column != "Bilanço"]
    veri3[value_columns] = veri3[value_columns].apply(pd.to_numeric, errors="coerce")
    # Tahmin edilen kümülatif akımlardaki eksik değerleri sıfıra çevirmek sahte
    # çeyrek sıçramaları üretir. Bu kritik kalemlerde eksikliği koru. Diğer
    # satırlarda API'nin "uygulanamaz" anlamında boş bıraktığı kalemler mevcut
    # notebook hesaplarıyla geriye uyumluluk için sıfır kalabilir.
    veri3 = veri3.set_index("Bilanço")
    forecast_critical_rows = {
        "Satış Gelirleri",
        "Ana Ortaklık Payları",
        "Net Faaliyet Kar/Zararı",
        "Amortisman Giderleri",
    }
    noncritical_rows = ~veri3.index.isin(forecast_critical_rows)
    veri3.loc[noncritical_rows, :] = veri3.loc[noncritical_rows, :].fillna(0)

    favok_inputs = {"Net Faaliyet Kar/Zararı", "Amortisman Giderleri"}
    missing_inputs = favok_inputs.difference(veri3.index)
    if missing_inputs:
        raise RuntimeError(f"{hisse} için FAVÖK kalemleri eksik: {', '.join(sorted(missing_inputs))}")
    veri3.loc["FAVÖK", :] = (
        veri3.loc["Net Faaliyet Kar/Zararı", :] + veri3.loc["Amortisman Giderleri", :]
    )

    df = veri3.T
    df.index = pd.to_datetime(df.index.astype(str) + "/01", format="%Y/%m/%d")
    df = df.sort_index()
    df = df.loc[df.index >= pd.Timestamp("2019-03-01")]
    if df.empty:
        raise RuntimeError(f"{hisse} için 2019-03 sonrası mali dönem bulunamadı.")
    return df
