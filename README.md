# Finansal Mercek

BIST (Borsa İstanbul) şirketleri için **sektör bazlı karşılaştırma** ve **tek şirket bazlı derinlemesine finansal analiz** yapan, Jupyter Notebook tabanlı analiz mantığını interaktif bir **FastAPI web uygulaması** üzerinden sunan bir araç.

Veriler `isyatirim.com.tr` (bilanço/gelir tablosu) ve `yfinance` (fiyat) kaynaklarından otomatik çekilir; sonuçlar tarayıcıda **Plotly** ile interaktif grafikler ve tablolar halinde gösterilir.

---

## İçindekiler

- [Genel Bakış](#genel-bakış)
- [Özellikler](#özellikler)
  - [Sektör Analizi](#sektör-analizi)
  - [Şirket Analizi](#şirket-analizi)
  - [Bilgilendirme Notları](#bilgilendirme-notları)
- [Ürün Kapsamı ve Uyum Tasarımı](#ürün-kapsamı-ve-uyum-tasarımı)
- [Mimari](#mimari)
- [Proje Yapısı](#proje-yapısı)
- [Kurulum](#kurulum)
- [Çalıştırma](#çalıştırma)
- [Performans ve Bekleme Süresi](#performans-ve-bekleme-süresi)
- [Testler](#testler)
- [Çıktılar](#çıktılar)
- [Notebook'ları Doğrudan Kullanmak](#notebookları-doğrudan-kullanmak)

---

## Genel Bakış

Proje iki ana modülden oluşur:

1. **Sektör Analizi** — Seçilen bir sektördeki tüm şirketleri, aynı anda değerleme çarpanları, kârlılık oranları ve finansal sağlık skorları üzerinden karşılaştırır.
2. **Şirket Analizi** — Tek bir şirketi; özet finansal görünüm, büyüme, kârlılık, DuPont ayrıştırması, bilanço yapısı, likidite, faaliyet verimliliği, nakit akımı, değerleme ve genel finansal skor kartı (+ Piotroski F-Skoru) üzerinden dönemsel olarak inceler.

Temel finansal dönüşüm ve grafik fonksiyonları iki Jupyter Notebook'ta (`Sektor Analizi.ipynb`, `Sirket Analiz.ipynb`) bulunur. Web uygulaması bu fonksiyonları "headless" yükler; istek orkestrasyonu, kural ve senaryo tabanlı ileri değerleme, şirket özet panosu, tablo biçimlendirme ve bazı ortak finansal metrikler ise test edilebilir `app/` modüllerinde yürütülür. Notebook veya Python modüllerinden biri değiştiğinde uygulama güncel kodu kullanır.

---

## Özellikler

### Sektör Analizi

Seçilen sektördeki tüm şirketler için tek bir karşılaştırma tablosu ve üç grafik grubu üretir:

- **Karşılaştırma tablosu**: PD, FD, Satış Gelirleri, FAVÖK, Ana Ortaklık Payları gibi mutlak büyüklükler; F/K, FD/FAVÖK, FD/NS, PD/DD gibi değerleme çarpanları; brüt/net kâr marjı; faiz karşılama ve ihracat oranları; DuPont bileşenleri (Net Kâr Marjı, Aktif Devir Hızı, Özkaynak Çarpanı, ROE); Piotroski F-Skoru. "SEKTÖR TOPLAM" ve "SEKTÖR Median" satırları, seçilen analiz türüne (TOPLAM/MEDIAN) göre her şirket için **sektör referanslı model değeri** ve **piyasa fiyatına göre model farkı** hesaplar.
- **Bar Grafikler**: Mutlak büyüklüklerin (PD, FD, Satış, FAVÖK, Piotroski F-Skoru) şirketler arası sıralamalı karşılaştırması.
- **Heatmap**: Değerleme çarpanlarının ve oranların (F/K, FD/FAVÖK, PD/DD, brüt/net kâr marjı, DuPont bileşenleri) satır bazlı persentil renklendirmesiyle karşılaştırması.
- **Sektör Finansalları**: Şirketlerin yıllıklandırılmış gelir tablosu toplamlarından sektör fark, baz 100 trend endeksi ve satış ağırlıklı brüt/faaliyet/FAVÖK/net kâr marjı grafikleri. TOPLAM/MEDIAN değerleme seçimi bu grafikleri değiştirmez.

Veri çekimi, sektördeki şirketler için kontrollü biçimde paralel yapılır. Tek bir şirketin dört dönemlik mali tablo paketleri de eşzamanlı indirilir; süreç genelindeki bağlantı sınırı veri kaynağının aşırı yüklenmesini önler.

Sektör finansal grafiklerinde eksik açıklamanın sahte düşüş üretmemesi için şirketlerin çoğunluğunun ulaştığı en güncel referans dönem belirlenir ve her kalemde bu döneme ulaşmış sabit şirket evreni kullanılır. En güncel dönemi henüz açıklamayan şirketler son mali dönemleriyle birlikte kullanıcıya gösterilir; veri kaynağı hataları bu listeden ayrı raporlanır.

### Şirket Analizi

Seçilen tek şirket için 10 kategoride dönemsel (çeyreklik) analiz sunar:

| Kategori | İçerik |
|---|---|
| **Özet** | Son dönem KPI'ları, dönem sonu fiyat eğilimi, aynı çeyrek yıllık gelir tablosu/bilanço karşılaştırması ve son beş gerçek çeyreğin satış–FAVÖK–net kâr grafikleri |
| **Büyüme** | QoQ/YoY oranları, trend endeksi ve gelir tablosu değişimlerinin **Yıllıklandırılmış**, **Dönemsel** ve **Açıklanan Kümülatif (3-6-9-12 aylık ham)** görünümleri; bilanço stok kalemleri ayrı bölümde |
| **Kârlılık** | Brüt/faaliyet/FAVÖK/net kâr marjı, ROA, ROE ve veri kaynağında mevcutsa ihracat oranı |
| **DuPont** | ROE'nin Net Kâr Marjı × Aktif Devir Hızı × Özkaynak Çarpanı bileşenlerine dönemsel ayrıştırılması |
| **Bilanço** | Varlık/yükümlülük/özkaynak dengesi, net işletme sermayesi |
| **Likidite** | Cari oran, likidite (asit-test) oranı, nakit oranı, net borç, Net Borç/FAVÖK ve faiz karşılama oranı |
| **Verimlilik** | Alacak/stok/borç devir hızları, nakit dönüşüm döngüsü (CCC) |
| **Nakit Akışı** | Faaliyet/yatırım/finansman nakit akımları, serbest nakit akımı (FCF) |
| **Değerleme** | F/K, FD/FAVÖK, PD/DD ve FD/Satışlar çarpanları; şirketin kendi tarihsel çarpanları, mevsimsellik ve geçmiş hata doğrulamasıyla ileri değerleme |
| **Skor** | 0-100 arası ağırlıklı finansal skor kartı (kârlılık/bilanço/likidite/verimlilik alt skorları) + **Piotroski F-Skoru** (9 kriter, detaylı kriter tablosu ile) |

#### Özet karşılaştırmasının dönem ve işaret kuralları

- Son açıklanan dönem tam bir yıl önceki **aynı mali çeyrekle** karşılaştırılır: `2026/6 → 2025/6`, `2026/3 → 2025/3`. Eş dönem yoksa başka bir çeyrek kullanılmaz; karşılaştırmanın hazırlanamadığı bildirilir.
- Özet gelir tablosu şirketin açıkladığı aynı kapsamlı 3-6-9-12 aylık kümülatif tutarları, alttaki grafikler ise kümülatif olmayan gerçek üç aylık tutarları kullanır.
- Zarar → kâr gibi negatif tabandan pozitife geçen gelir tablosu kalemlerinde klasik yüzde değişim yanıltıcı olduğundan `NaN` gösterilir.
- **Net borç = finansal borç − nakit** olarak yorumlanır. Negatif net borç nakit fazlasıdır. Net borç değişimi negatifse iyileşme/yeşil, pozitifse bozulma/kırmızı gösterilir. Örneğin `-13,2 → -23,1`, `-%75,1` ve yeşildir.

Skor kartı ve Piotroski F-Skoru, mutlak TL tutarları yerine **oran bazlı** hesaplama kullanır; bu sayede şirket büyüklüğünden ve sektörden bağımsız, karşılaştırılabilir sonuç üretir.

İleri değerleme istatistiksel zaman serisi modeli çalıştırmaz. Mart, Haziran ve Eylül dönemlerinde şirketin açıkladığı yıl içi satış toplamı, önceki tamamlanmış yıllardaki aynı dönem/yıl satış payının sağlamlaştırılmış medyanıyla yıl sonuna taşınır. Cari net kâr ve FAVÖK marjları tarihsel yıllık medyanlarla dengelenir; standart sapmanın otomatik olarak iki kat eklenmesi gibi iyimserliği zorlayan kurallar kullanılmaz.

Aralık bilançosu geldiğinde cari yıl yeniden tahmin edilmez. Son tamamlanan yılın büyümesi ve marjları geçmiş yıllık dağılımla dengelenerek sonraki Aralık için 12 aylık ileri satış, net kâr, FAVÖK, net borç ve özkaynak projeksiyonu hazırlanır. Özkaynak köprüsü ara dönemlerde yalnızca henüz açıklanmamış çeyreklerin kâr/zararını; Aralık sonrasında ise geçmiş özkaynak hareketlerinden türetilen elde tutma oranıyla gelecek yıl kârını ekler.

F/K, PD/DD, FD/FAVÖK ve **FD/NS** hedefleri eşit ortalanmaz. Satışlar bütün sermaye sağlayıcılarına ait olduğu için PD/NS yerine FD/NS kullanılır; tahmini firma değerinden net borç düşülerek özkaynak değeri ve hisse başı hedef bulunur. Her yöntemin tarihsel örnek sayısı ve çarpan dağılımının istikrarı güven ağırlığına dönüştürülür; negatif kâr veya FAVÖK nedeniyle anlamsızlaşan yöntem ağırlık dışı bırakılır.

Şirket baz çarpanı yalnız şirketin kendi son altı geçerli gözleminden hesaplanır; son döneme `%65`, şirket medyanına `%35` ağırlık verir ve şirket geçmişinin `%10–%90` sınırlarında tutulur. Sektör medyanı veya sektör çıpası değerleme hesabına katılmaz.

Kullanıcı arayüzünde tek bir “hedef fiyat” veya “iskontolu/pahalı” hükmü yerine temkinli–baz–iyimser **model değerleme aralığı**, model değerleme ortalaması ve piyasa fiyatına göre matematiksel model farkı gösterilir. Bu fark temettü içermez ve alım, satım veya tutma önerisi olarak sunulmaz. Hesaplama motorundaki iç bantlar geriye dönük test uyumluluğu için korunurken yönlendirici sınıflar kullanıcıya gösterilmez.

Güven puanı istatistiksel gerçekleşme olasılığı değildir ancak artık yalnız örnek sayısına dayanmaz. Uygun geçmiş Aralık dönemlerinde model yalnız o tarihte mevcut verilerle çalıştırılır, sonraki Aralık gerçekleşen fiyatıyla karşılaştırılır ve medyan mutlak yüzde hata güven puanında `%35` ağırlık taşır. Senaryo genişliği `%25`, çarpan gözlem sayısı `%15`, tamamlanmış yıl sayısı `%15` ve projeksiyon girdisi `%10` ağırlıktadır. Geriye dönük doğrulama penceresi yoksa puan “Yüksek” seviyesine çıkamaz.

Yeni halka arz edilmiş veya finansal geçmişi henüz yeterince oluşmamış şirketlerde değerleme zorlanmaz. En az iki tamamlanmış geçmiş mali yıl ya da en az dört geçerli çarpan gözlemi bulunmadığında şirket analizinin diğer bölümleri gösterilmeye devam eder; değerleme alanında yeterli veri bulunmadığını açıklayan bir uyarı sunulur.

Hisse bölünmelerinde fiyat ve pay adedi aynı baza getirilir. Yahoo Finance `Stock Splits` olayları kullanılarak bölünme öncesi fiyatlar güncel pay bazına indirilir, geçmiş ödenmiş sermaye ise aynı katsayıyla artırılır. Veri sağlayıcı fiyatı veya sermayeyi daha önce geriye dönük düzeltmişse kopuş kontrolü ikinci bir düzeltmeyi engeller. Değerleme çarpanlarında temettü etkisini de içeren `Adj Close` yerine yalnız bölünme bazında düzeltilmiş fiyat kullanılır; `Adj Close` toplam getiri hesabında ayrı tutulur.

Değerleme çarpanları son altı geçerli çeyreğin güncel rejiminden üretilir. Baz çarpan, son gözleme daha yüksek; yakın dönem medyanına dengeleyici ağırlık verir. Böylece geçici tek dönem etkisi yumuşatılırken, uzak geçmişte kalmış aşırı çarpanların bugünkü hedef fiyatı bozması sınırlandırılır.

### Bilgilendirme Notları

Her kategorinin/görünümün üstünde, o analizin ne ölçtüğünü ve neden önemli olduğunu özetleyen, akademik/uygulayıcı kaynak alıntısı içeren kısa bir bilgi notu gösterilir (örn. Piotroski F-Skoru için Piotroski (2000), DuPont için Donaldson Brown/DuPont de Nemours, değerleme çarpanları için Damodaran). Bu notlar tamamen frontend'de (`static/app.js`) tanımlıdır, backend hesaplamasını etkilemez.

## Ürün Kapsamı ve Uyum Tasarımı

Finansal Mercek, aynı veri ve metodoloji sürümünde bütün kullanıcılara aynı sonucu veren **kişiselleştirilmemiş finansal analiz ve modelleme aracı** olarak tasarlanmıştır. Uygulama kullanıcının mali durumunu, portföyünü, yatırım süresini, yatırım amacını veya risk-getiri tercihlerini toplamaz ve bu bilgilere göre öneri üretmez. Emir iletimi, portföy dağılımı, “al/sat/tut” talimatı ve kullanıcıya özel bildirim kapsam dışındadır.

- Sektör referanslı model değerleri ile şirket değerleme raporları görüntülenmeden önce kapsam ve risk bilgilendirmesi gösterilir.
- Her şirket/sektör raporu benzersiz rapor kimliği, oluşturulma zamanı, veri kaynakları, finansal dönem/kapsam, metodoloji sürümü, güncelleme ve düzeltme politikası taşır.
- Değerleme arayüzünde yönlendirici “iskontolu/pahalı” etiketleri kullanılmaz; sonuçlar piyasa fiyatının model ortalaması/aralığına göre nötr biçimde ifade edilir.
- Tahmin, varsayım ve fiyatların garanti olmadığı; kaynak gecikmesi, eksik dönem ve kurumsal işlem düzeltmelerinin sonucu etkileyebileceği açıkça belirtilir.
- Çıkar çatışması, sponsorlu içerik, veri lisansları, kullanıcı sözleşmesi ve KVKK belgeleri için giriş ekranında ticari yayın öncesi kontrol alanı bulunur.
- Isı haritalarının mevcut göreli renk ölçekleri ve renk anlamları değiştirilmemiştir.

Bu teknik önlemler hukuki görüş veya SPK faaliyet izni yerine geçmez. Ticari yayından önce III-37.1 kapsamındaki zorunlu uyarı metni, işletmeci kimliği, sözleşmeler, KVKK belgeleri, çıkar çatışması politikası ve piyasa verisi lisansları sermaye piyasası hukukçusu tarafından doğrulanmalıdır.

---

## Mimari

```
Tarayıcı (templates/index.html + static/app.js)
        │  fetch() ile JSON istek/yanıt
        ▼
FastAPI (app/main.py)
        │
        ├── app/analysis_sector.py  ──► Sektor Analizi.ipynb  (mod.sektor_analizi)
        │                                    │
        └── app/analysis_company.py ──► Sirket Analiz.ipynb   (mod.oran_rasyo_hesaplama,
                                             │                  mod.financial_scorecard, ...)
                                             ▼
                                   app/financial_metrics.py
                                (Piotroski F-Skoru, DuPont — her iki notebook'ta ortak kullanılır)
```

- **`app/notebook_runtime.py`**: `.ipynb` dosyasının kod hücrelerini okuyup izole bir Python modülü olarak `exec` eder (`if __name__ == "__main__":` bloğu web akışında otomatik atlanır). Notebook içindeki `show(fig)` çağrıları monkeypatch'lenerek Plotly figürleri, tarayıcıda açmak yerine JSON olarak yakalanır.
- **`app/valuation.py`**: Ara dönem mevsimselliğini, 12 aylık ileri Aralık projeksiyonunu, marj/net borç senaryolarını ve güven ağırlıklı çarpan değerlemesini yürütür.
- **`app/forecasting.py` / `app/tufe_cache.py`**: Eski notebook uyumluluğu için korunur; web uygulamasının ileri değerleme akışında kullanılmaz.
- **`app/table_format.py`**: Web tablolarında Türkçe sayı gösterimini, Excel çıktılarında ise gerçek sayısal hücre formatlarını merkezi olarak uygular.
- **`app/plotly_theme.py`**: Tüm grafiklerde ortak açık tema (`#ECF1E5` zemin, yeşil vurgu ve kırmızı risk renkleri), renk paleti ve `format_tr_number()` ile Türkçe binlik/ondalık sayı formatlaması sağlar.
- **`app/financial_metrics.py`**: Piotroski F-Skoru, DuPont ayrıştırması, faiz karşılama/ihracat oranları, gerçek çeyreklik akış hazırlama, yıl sonu mutabakatı ve güvenli `yfinance` erişiminin ortak kaynağıdır.
- **`balancesheet.py`**: `isyatirim.com.tr` üzerinden bilanço/gelir tablosu verisi çeker; bağlantı havuzu, kontrollü paralellik, 5 dakikalık süreç içi önbellek ve geçici ağ hatalarına karşı üstel geri çekilmeli yeniden deneme mantığı içerir.

---

## Proje Yapısı

```
├── app/
│   ├── main.py                 FastAPI uygulaması, route tanımları
│   ├── analysis_sector.py      Sektör analizi orkestrasyon + Plotly bar/heatmap üretimi
│   ├── analysis_company.py     Şirket analizi orkestrasyon + tablo/skor HTML üretimi
│   ├── financial_metrics.py    Ortak metrikler + çeyreklik/yıl sonu mutabakatı + fiyat erişimi
│   ├── valuation.py            Mevsimsellik + senaryo + güven ağırlıklı değerleme
│   ├── forecasting.py          Eski notebook uyumluluğu (web değerlemesinde kullanılmaz)
│   ├── tufe_cache.py           Eski notebook uyumluluğu
│   ├── table_format.py         HTML/Excel sayı biçimlendirme
│   ├── plotly_theme.py         Grafik teması + Türkçe sayı formatlama
│   └── notebook_runtime.py     Notebook'u headless çalıştırma + Plotly figür yakalama
├── templates/index.html        Tek sayfa arayüz (Giriş / Sektör Analizi / Şirket Analizi sekmeleri)
├── static/
│   ├── app.js                  Frontend mantığı (fetch, özet/KPI render, grafikler, bilgi notları)
│   ├── app.css                 Açık tema ve responsive stiller
│   └── outputs/                (gitignore'lu) çalışma zamanında üretilen dosyalar
├── Sektor Analizi.ipynb        Sektör finansal dönüşüm ve notebook fonksiyonları
├── Sirket Analiz.ipynb         Şirket finansal dönüşüm ve notebook fonksiyonları
├── balancesheet.py             isyatirim.com.tr'den bilanço/gelir tablosu çekimi (retry'lı)
├── temel_ozet.xlsx             Şirket → sektör eşlemesi (sektör seçim listesi buradan üretilir)
├── static/outputs/sektorler/   Çalışma zamanında üretilen Excel çıktıları (gitignore'lu)
├── requirements.txt            Sabitlenmiş çalışma zamanı bağımlılıkları
└── requirements-dev.txt        Test/doğrulama bağımlılıkları
```

---

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

Geliştirme ve test ortamı için:

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

## Çalıştırma

```bash
uvicorn app.main:app --reload --port 8000
```

Tarayıcıdan `http://127.0.0.1:8000` adresini açın. Açılış sayfası uygulamanın ne yaptığını ve hangi analizleri sunduğunu özetler; üstteki sekmelerden **Sektör Analizi** veya **Şirket Analizi**'ne geçebilirsiniz.

## Performans ve Bekleme Süresi

- İş Yatırım mali tablo yanıtları ve Yahoo Finance indirmeleri süreç içinde **5 dakika** önbelleğe alınır. Aynı veri kısa süre içinde yeniden istendiğinde ikinci çalışma belirgin biçimde hızlanır; uygulama yeniden başlatılırsa önbellek sıfırlanır.
- Sektör şirketleri ve tek şirkete ait mali tablo dönem paketleri kontrollü biçimde paralel çalıştırılır. İleri değerleme pahalı model eğitimi yapmadığı için veri hazırlığından sonra kısa sürede tamamlanır.
- Sonuç durumunda toplam süre; şirket analizinde ayrıca veri ve değerleme süreleri gösterilir. İlk çalışma İş Yatırım veya Yahoo Finance bağlantı hızına bağlı olarak sonraki çalışmalardan uzun sürebilir.

## Testler

Test paketi; API doğrulamalarını, aynı çeyrek şirket özetini, net borç işaret/renk kurallarını, ara dönem mevsimselliğini, Aralık sonrası 12 aylık ileri değerlemeyi, tablo biçimlendirmeyi, önbellek davranışını ve frontend sözleşmelerini kapsar.

```bash
python -m unittest discover -s tests -v
```

`pytest` kuruluysa daha kısa çıktı için `python -m pytest -q` da kullanılabilir. Son proje kontrolünde **88 test** başarıyla geçmiştir.

## Çıktılar

- Sektör analizinde **"Excel Kaydı = EVET"** seçilirse, sonuç tablosu `static/outputs/sektorler/<sektör adı>.xlsx` olarak kaydedilir.
- Bazı hisseler veri kaynağı nedeniyle başarısız olursa analiz kalan hisselerle tamamlanır; başarılı/başarısız hisse sayıları ve başarısız semboller API yanıtının `meta` alanında raporlanır. Hiçbir hisse analiz edilemezse istek hata döndürür.
- Web tabloları Türkçe gösterim kullanır: büyük tutarlar `1.234.567`, oran ve fiyatlar `12,34`, dönemler `2026-03`, eksik değerler `—` biçiminde sunulur. Bu dönüşüm yalnızca gösterimi etkiler; hesaplama verileri sayısal kalır.
- Excel çıktıları sayıları metne çevirmeden `#,##0` / `#,##0.00` hücre biçimleriyle kaydeder; başlık satırı sabitlenir ve otomatik filtre eklenir.
- Grafikler sunucu tarafında dosyaya yazılmaz; Plotly figürleri doğrudan JSON olarak tarayıcıya gönderilir ve tarayıcıda render edilir. Ana grafikler tıklanarak büyütülebilir; özet panosundaki mini grafikler kart genişliğine göre duyarlı biçimde boyutlanır.
- Model bazlı değerlemede dört yöntemin senaryo değerleri, yeterlilik ağırlıkları, finansal projeksiyon senaryoları ve kullanılan varsayımlar ayrı tablolarda gösterilir.

## Notebook'ları Doğrudan Kullanmak

Her iki ana notebook da (`Sektor Analizi.ipynb`, `Sirket Analiz.ipynb`) Jupyter üzerinde bağımsız olarak da çalıştırılabilir — dosyanın sonundaki `if __name__ == "__main__":` bloğu, terminal girişli (interaktif `input()`) bağımsız bir CLI akışı sağlar. Web uygulaması bu bloğu atlar ve yalnızca fonksiyon tanımlarını (hücre kaynak kodunu) kullanır.
