/* ============================================================
   STATE
   ============================================================ */
const state = {
  sector: {
    data: null,          // { tables, charts, meta }
    mode: "table",       // "table" | "image"
    imgFilter: "all",    // "all" | "bar" | "heatmap"
    disclosureAccepted: false,
  },
  company: {
    data: null,
    mode: "table",       // "table" | "image"
    category: "özet",    // active category key
    valuationAcceptedReports: new Set(),
  },
  disclosure: {
    pendingAction: null,
  },
};

const VALUATION_DISCLOSURE_VERSION = "2026-08-31-v1";

/* ============================================================
   CATEGORY → TABLE/IMAGE MAPPING  (Şirket Analizi)
   ============================================================ */
const COMPANY_TABLE_MAP = {
  "özet":     [],
  "büyüme":    ["Finansal Kalem Değişimleri", "Büyüme Oranları", "Kalem Bazında Trend Endeksi (Baz = 100)", "Gelir Tablosu Kalemleri (Gerçek Çeyreklik)"],
  "karlılık":  ["Kârlılık ve Satış Yapısı"],
  "dupont":    ["DuPont Analizi"],
  "bilanço":   ["Bilanço Dengesi"],
  "dikey":     ["Dikey Bilanço Karşılaştırması", "Dikey Gelir Tablosu Karşılaştırması"],
  "likidite":  ["Likidite ve Borç Ödeme Gücü"],
  "verimlilik":["Nakit Döngüsü"],
  "nakit":     ["Nakit Akımı"],
  "değerleme": ["Çarpanlar", "Model Bazlı Değerleme Özeti", "Değerleme Yöntemleri ve Ağırlıkları", "Finansal Projeksiyon Senaryoları", "Değerleme Varsayımları"],
  "skor":      ["Toplam Skor", "Skor Kartı (Kategori Skorları)", "Piotroski F-Skoru", "Piotroski F-Skoru Detayı"],
};

/* ============================================================
   BİLGİLENDİRME NOTLARI (teorik arka plan + kaynak/alıntı)
   ============================================================ */
const COMPANY_INFO_NOTES = {
  "özet": {
    title: "Özet karşılaştırma hangi dönemi esas alıyor?",
    text: [
      "Özet gelir tablosu ve bilanço, son açıklanan mali dönemi tam bir yıl önceki aynı çeyrekle karşılaştırır. Örneğin 2026/6 yalnızca 2025/6 ile, 2026/3 yalnızca 2025/3 ile kıyaslanır.",
      "Gelir tablosundaki tutarlar şirketin açıkladığı aynı kapsamlı 3-6-9-12 aylık kümülatif değerlerdir. Alttaki sütun grafikler ise kümülatif olmayan, tek başına üç aylık gerçek satış, FAVÖK ve net kâr tutarlarını gösterir.",
      "Net borç finansal borç eksi nakit olarak yorumlanır: negatif değer nakit fazlasını gösterir. Net borç değişimi negatifse iyileşme ve yeşil, pozitifse bozulma ve kırmızı gösterilir. Zarar-kâr gibi diğer kalemlerin negatiften pozitife geçişinde yüzde değişim NaN olarak sunulur.",
    ],
    source: "Karşılaştırma yöntemi: aynı mali çeyreğin yıllık değişimi (YoY).",
  },
  "büyüme": {
    title: "Büyüme sonuçlarını nasıl okumalıyım?",
    text: [
      "Bu bölüm satış, FAVÖK, kâr ve bilanço kalemlerinin zaman içinde büyüyüp büyümediğini gösterir. QoQ bir önceki çeyreğe, YoY geçen yılın aynı dönemine göre değişimi ifade eder.",
      "Gelir tablosu değişimlerinde Yıllıklandırılmış görünüm son dört çeyrek toplamındaki farkı, Dönemsel görünüm gerçek üç aylık tutarın önceki çeyreğe göre farkını, Açıklanan Kümülatif görünüm ise şirketin yayımladığı 3-6-9-12 aylık ham tutarların ardışık raporlar arasındaki farkını gösterir.",
      "Açıklanan Kümülatif görünümde gelir tablosu her yıl Mart döneminde yeniden başladığı için Aralık–Mart farkı doğal olarak bir yıl sonu sıfırlama etkisi içerir. Bu görünümü dönemsel performans yerine yayımlanan rapor büyüklüklerinin değişimini izlemek için kullanın. Bilanço kalemleri ise dönem sonu stok değerlerindeki değişimi ayrı bölümde sunulur.",
      "Önce satış büyümesine, ardından FAVÖK ve net kârın aynı yönde ilerleyip ilerlemediğine bakın. Satış artarken kâr veya nakit geriliyorsa büyümenin kalitesi zayıflıyor olabilir.",
      "Tek bir güçlü dönem yerine birkaç döneme yayılan istikrarlı eğilimi önemseyin. Mevsimselliği yüksek şirketlerde YoY görünüm genellikle daha anlamlıdır.",
    ],
    source: "Yöntem kaynağı: Fridson & Alvarez, Financial Statement Analysis (2011).",
  },
  "karlılık": {
    title: "Kârlılık sonuçlarını nasıl okumalıyım?",
    text: [
      "Marjlar, her 100 TL satışın ne kadarının brüt kâr, faaliyet kârı, FAVÖK veya net kâr olarak kaldığını gösterir. ROA varlıkların, ROE ise ortakların koyduğu sermayenin ne kadar verimli kullanıldığını ölçer.",
      "Marjların birlikte yükselmesi olumlu bir işarettir. Brüt marj düşerken net marj yükseliyorsa finansman, vergi veya tek seferlik gelirlerin etkisini ayrıca kontrol edin.",
      "Son dönemi yalnız başına değil, şirketin geçmişi ve benzer şirketlerle birlikte değerlendirin.",
      "İhracat oranı, açıklanan yurtdışı satışların yurtiçi ve yurtdışı satışlar toplamındaki payıdır. Yüksek oran döviz geliri çeşitliliği sağlayabilir; kur ve ülke riskini de birlikte değerlendirin.",
    ],
    source: "Yöntem kaynakları: Damodaran (2012); Subramanyam (2014).",
  },
  "dupont": {
    title: "ROE neden değişiyor?",
    text: [
      "DuPont analizi ROE'yi üç kaynağa ayırır: kâr marjı, varlıkların satış üretme hızı ve finansal kaldıraç.",
      "ROE artışının kâr marjı veya verimlilikten gelmesi genellikle daha sağlıklıdır. Artış ağırlıklı olarak borçlanmadan geliyorsa riski bilanço ve nakit akışıyla birlikte inceleyin.",
    ],
    source: "Yöntem kaynağı: Palepu & Healy, Business Analysis and Valuation (2013).",
  },
  "bilanço": {
    title: "Bilanço ne söylüyor?",
    text: [
      "Bu bölüm şirketin varlıklarını borçla mı, özkaynakla mı finanse ettiğini ve günlük faaliyetleri için yeterli işletme sermayesi bulunup bulunmadığını gösterir.",
      "Dikey bilanço karşılaştırması son açıklanan dönemi bir yıl önceki aynı mali çeyrekle karşılaştırır. Her kalemin Pay (%) değeri, ilgili dönem tutarının o dönemin Toplam Varlıklar tutarına bölünmesiyle hesaplanır; böylece bilançonun yapısındaki değişim şirket ölçeğinden bağımsız izlenebilir.",
      "Borçlar satış ve FAVÖK'ten daha hızlı büyüyorsa finansal risk artabilir. Varlık büyümesini tek başına olumlu kabul etmeyin; büyümenin nasıl finanse edildiğine de bakın.",
    ],
    source: "Yöntem kaynakları: IAS 1; Brealey, Myers & Allen (2020).",
  },
  "dikey": {
    title: "Dikey bilanço analizi nasıl okunmalı?",
    text: [
      "Tablo son açıklanan dönemi bir yıl önceki aynı mali çeyrekle karşılaştırır. Her kalemin Pay (%) değeri, ilgili dönem tutarının o dönemin Toplam Varlıklar tutarına bölünmesiyle hesaplanır.",
      "Gelir tablosunda Pay (%) değeri ilgili kalemin aynı dönemdeki Satış Gelirlerine oranıdır. Ara dönem tutarları şirketin açıkladığı kümülatif 3-6-9 aylık değerlerdir; çeyreklik tek dönem değerleri değildir.",
      "Bilanço değişimi yönü doğru korumak için (cari − önceki) / |önceki| × 100; gelir tablosu değişimi ise referans Excel gibi (cari / önceki − 1) × 100 formülüyle hesaplanır. Gelir ve gider kalemlerinin ekonomik anlamı farklı olabildiği için değişim hücrelerinde yön rengi kullanılmaz; önceki değer sıfırsa — gösterilir.",
      "Pay sütunlarını birlikte okuyarak yalnızca tutar değişimini değil, ilgili kalemin bilanço veya gelir tablosu içindeki ağırlığının değişip değişmediğini de değerlendirin.",
    ],
    source: "Karşılaştırma yöntemi: aynı mali çeyreğin yıllık değişimi ve toplam varlıklara göre dikey analiz.",
  },
  "likidite": {
    title: "Kısa vadeli ödeme gücü yeterli mi?",
    text: [
      "Cari oran, asit-test oranı ve nakit oranı şirketin yakın vadeli borçlarını ödeme kapasitesini farklı sıkılık düzeylerinde gösterir.",
      "Oranların yönünü birkaç dönem boyunca izleyin. 1 seviyesi yararlı bir referanstır ancak stok yapısı, tahsilat süresi ve sektör koşulları nedeniyle tek başına kesin bir eşik değildir.",
      "Faiz karşılama oranı FAVÖK'ün finansman giderlerini kaç kez karşıladığını gösterir. Yükselmesi borç servis kapasitesinin güçlendiğine, düşük veya negatif değerler ise finansman baskısına işaret edebilir.",
    ],
    source: "Yöntem kaynağı: Subramanyam & Wild (2014).",
  },
  "verimlilik": {
    title: "Şirket nakdi ne kadar hızlı döndürüyor?",
    text: [
      "Alacak, stok ve borç günleri; nakdin satıştan tahsilata uzanan süreçte ne kadar süre bağlı kaldığını gösterir. Nakit dönüşüm döngüsünün kısalması genellikle olumludur.",
      "Alacak veya stok günlerinin sürekli yükselmesi tahsilat ya da satış sorununa işaret edebilir. Borç ödeme süresindeki artışı ise tedarikçi koşulları ve nakit ihtiyacıyla birlikte yorumlayın.",
    ],
    source: "Yöntem kaynağı: Richards & Laughlin (1980).",
  },
  "nakit": {
    title: "Kâr gerçek nakde dönüşüyor mu?",
    text: [
      "Faaliyet nakit akışı ana işin ürettiği nakdi, serbest nakit akışı ise yatırımlar sonrasında kalan nakdi gösterir.",
      "Net kâr büyürken faaliyet nakdi uzun süre geride kalıyorsa kazanç kalitesini sorgulayın. Negatif serbest nakit akışı her zaman kötü değildir; güçlü yatırım dönemlerinde geçici olabilir.",
    ],
    source: "Yöntem kaynağı: Penman (2013).",
  },
  "değerleme": [
    {
      title: "Değerleme sonuçlarını nasıl kullanmalıyım?",
      text: [
        "F/K, FD/FAVÖK, PD/DD ve FD/NS çarpanları mevcut fiyatı şirketin kârı, faaliyet performansı, defter değeri veya satışlarıyla karşılaştırır.",
        "Düşük çarpan tek başına olumlu bir yatırım sonucu anlamına gelmez. Model yalnız şirketin kendi geçmiş verilerini standart kurallarla işler; kullanıcının portföyü, mali durumu, yatırım süresi veya risk tercihleri hesaba katılmaz.",
        "Model değerleri kesin fiyat hedefi değildir. Model değerleme ortalamasını temkinli ve iyimser senaryo aralığıyla, ayrıca veri ve model yeterlilik puanıyla birlikte okuyun.",
        "Mart, Haziran ve Eylül dönemlerinde açıklanan yıl içi satışlar geçmiş yıllardaki aynı dönem/yıl payıyla tamamlanır. Net kâr ve FAVÖK, cari marjlarla sağlamlaştırılmış tarihsel medyanların birleşiminden türetilir.",
        "Aralık bilançosu açıklandığında cari yıl yeniden tahmin edilmez; geçmiş yıllık büyüme, marj ve net borç dağılımlarından sonraki Aralık için 12 aylık ileri projeksiyon hazırlanır.",
        "F/K, PD/DD, FD/FAVÖK ve FD/NS yöntemleri eşit ortalanmaz. Her çarpan yalnız şirketin kendi son altı geçerli döneminden sağlamlaştırılarak hesaplanır; sektör medyanı veya sektör çıpası kullanılmaz. Zarar veya negatif FAVÖK nedeniyle anlamsızlaşan yöntem hesaplamadan çıkarılır.",
        "Piyasa fiyatına göre model farkı, model değerleme ortalaması ile analiz sırasında kullanılan fiyat arasındaki matematiksel farktır. Temettü dahil değildir ve bu ölçü alım, satım veya tutma önerisi oluşturmaz.",
      ],
      source: "Yöntem kaynağı: Damodaran, Damodaran on Valuation (2006).",
    },
    {
      title: "İleri değerleme matematiksel olarak nasıl hesaplanıyor?",
      text: [
        "Önce temkinli, baz ve iyimser finansal senaryolar kurulur. Net kâr = tahmini satış × net kâr marjı; FAVÖK = tahmini satış × FAVÖK marjı; net borç = tahmini FAVÖK × Net Borç/FAVÖK oranı olarak hesaplanır. Ara dönemde özkaynağa yalnızca henüz açıklanmamış dönemlerin tahmini kârı eklenir.",
        "Her senaryoda dört ayrı model değeri üretilir: F/K değeri = (tahmini net kâr / pay adedi) × F/K; PD/DD değeri = (tahmini özkaynak / pay adedi) × PD/DD; FD/FAVÖK değeri = (tahmini FAVÖK × FD/FAVÖK − tahmini net borç) / pay adedi; FD/NS değeri = (tahmini satış × FD/NS − tahmini net borç) / pay adedi.",
        "Şirket baz çarpanı yalnız şirketin son altı geçerli döneminden hesaplanır; son gözleme %65, şirket medyanına %35 ağırlık verir ve şirket geçmişinin %10–%90 sınırlarında tutulur. Yöntem ağırlığında gözlem sayısı, dağılım açıklığı ve son çarpanın şirket medyanından uzaklığı birlikte kullanılır.",
        "Model değerleme ortalaması = Σ(yöntem baz senaryo değeri × normalize edilmiş yöntem ağırlığı) formülüdür. Piyasa fiyatına göre model farkı, bu ortalama ile analiz sırasında kullanılan fiyat arasındaki değişimdir. Yeterlilik puanında geçmiş model değerlerinin gerçekleşen fiyatlara karşı medyan mutlak hatası %35, senaryo genişliği %25, gözlem sayısı %15, finansal geçmiş %15 ve projeksiyon girdisi %10 ağırlık taşır. Geçmiş doğrulama yoksa yeterlilik puanı yüksek seviyeye çıkamaz.",
      ],
      source: "Uygulama yöntemi: sağlamlaştırılmış tarihsel çarpanlar, finansal senaryolar ve güven ağırlıklı birleşim.",
    },
    {
      title: "Rapor kapsamı, güncelleme ve düzeltme ilkeleri",
      text: [
        "Her rapor; analiz zamanı, finansal dönem, veri kaynakları, metodoloji sürümü ve benzersiz rapor kimliğiyle yayımlanır. Yeni veriyle yeniden çalıştırılan analiz yeni bir rapor olarak değerlendirilir.",
        "Veri veya hesaplama hatası tespit edildiğinde sonuç sessizce değiştirilmez; güncel veri ve metodoloji sürümüyle yeni rapor üretilir. Veri kaynağına erişim, gecikme, eksik dönem ve kurumsal işlem düzeltmeleri sonuçları etkileyebilir.",
        "Analiz edilen şirketten alınan ücret, sponsorluk, reklam ilişkisi veya içerik hazırlayanların önemli finansal çıkarı bulunması halinde bu durum ilgili raporda ayrıca açıklanmalıdır.",
      ],
      source: "Politika: kişiselleştirilmemiş, sürümlü ve kaynakları açıklanan model raporu.",
    },
  ],
  "skor": {
    title: "Skorları nasıl yorumlamalıyım?",
    text: [
      "Toplam skor, büyüme, kârlılık, bilanço, likidite, verimlilik, nakit akışı, değerleme ve momentum göstergelerini 0–100 aralığında özetler. 80 ve üzeri çok güçlü, 65–79 güçlü, 50–64 nötr, 35–49 zayıf, 35 altı çok zayıf olarak sınıflandırılır.",
      "Önce toplam skora, ardından sonucu hangi kategorilerin yükselttiğine veya düşürdüğüne bakın. Hesaplanamayan kategoriler toplam ağırlıktan çıkarılır; bu nedenle eksik verili şirketlerde alt kırılımlar özellikle önemlidir.",
      "Piotroski F-Skoru dokuz kârlılık, borç/likidite ve verimlilik ölçütündeki yıllık iyileşmeyi sayar. Örneğin 5/9, dokuz koşulun beşinin sağlandığını gösterir. Her iki skor da incelemeyi hızlandıran bir özet olup tek başına alım-satım sinyali değildir.",
    ],
    source: "Yöntem kaynakları: Fridson & Alvarez (2011); Piotroski (2000).",
  },
};

const SECTOR_INFO_NOTES = {
  "table": {
    title: "Karşılaştırma tablosuna nereden başlamalıyım?",
    text: [
      "Önce şirketlerin ölçek, kârlılık ve borçluluk farklarını karşılaştırın; ardından değerleme çarpanlarına geçin. Toplam analizi sektörün birleşik büyüklüğünü, medyan analizi ise uç değerlerden daha az etkilenen tipik şirketi referans alır.",
      "Sektör referanslı model değeri ve piyasa fiyatına göre model farkı seçilen TOPLAM veya MEDIAN referansıyla hesaplanır. Bu sonuçlar kişisel koşulları değerlendirmez ve tek başına yatırım kararı veya fırsat göstergesi oluşturmaz.",
      "Piotroski seçeneği açıksa finansal güç skoru da tabloya eklenir ve analiz biraz daha uzun sürebilir.",
    ],
    source: "Yöntem kaynağı: Damodaran, Damodaran on Valuation (2006).",
  },
  "bar": {
    title: "Sıralama grafiklerini nasıl okumalıyım?",
    text: [
      "Grafikler şirketleri piyasa değeri, satış, FAVÖK ve benzeri büyüklüklere göre sıralar. Böylece sektör liderlerini ve ölçek farklarını hızlıca görebilirsiniz.",
      "Büyük şirket her zaman daha kârlı veya piyasa fiyatı model referansına daha yakın değildir. Sıralamayı marjlar, borçluluk ve değerleme tablosuyla birlikte okuyun.",
    ],
    source: "Yöntem kaynağı: Damodaran (2006).",
  },
  "heatmap": {
    title: "Isı haritasındaki renkler ne anlama geliyor?",
    text: [
      "Renkler her şirketin seçilen ölçütte sektör içindeki göreli konumunu gösterir. Yoğun renk mutlak olarak iyi veya kötü demek değildir; hangi ölçütün gösterildiğine göre anlam değişir.",
      "Düşük değerleme çarpanları ve yüksek kârlılık oranları genellikle olumlu görünür. Yine de sıra dışı değerlerde borç, tek seferlik gelir ve veri kalitesini kontrol edin.",
    ],
    source: "Yöntem kaynakları: Damodaran (2006); Piotroski (2000).",
  },
  "sector_financials": {
    title: "Sektör finansal grafiklerini nasıl okumalıyım?",
    text: [
      "Yıllıklandırılmış fark ve trend grafikleri, seçilen TOPLAM/MEDIAN değerleme yönteminden bağımsız olarak şirketlerin yıllıklandırılmış gelir tablosu kalemlerinin toplamından hazırlanır.",
      "Eksik açıklamanın sahte düşüş yaratmaması için her kalemde referans döneme ulaşmış sabit ve karşılaştırılabilir şirket evreni kullanılır. Kapsama girmeyen şirketler dönem bilgisiyle ayrıca listelenir.",
      "Sektör marjları basit şirket marjı ortalaması değildir; sektör brüt kârı, faaliyet kârı, FAVÖK'ü ve net kârı sektör satış toplamına bölünerek hesaplanır.",
    ],
    source: "Hesaplama yöntemi: sabit şirket evrenli yıllıklandırılmış sektör toplamı.",
  },
};

function prependInfoNotes(container, notes, { prepend = true } = {}) {
  const fragment = document.createDocumentFragment();
  (notes || []).filter(Boolean).forEach((note) => {
    const box = document.createElement("div");
    box.className = "info-note";

    const title = document.createElement("div");
    title.className = "info-note-title";
    title.textContent = `ℹ️ ${note.title}`;
    box.appendChild(title);

    const paragraphs = Array.isArray(note.text) ? note.text : [note.text];
    paragraphs.filter(Boolean).forEach((para) => {
      const text = document.createElement("p");
      text.className = "info-note-text";
      text.textContent = para;
      box.appendChild(text);
    });

    if (note.source) {
      const source = document.createElement("p");
      source.className = "info-note-source";
      source.textContent = note.source;
      box.appendChild(source);
    }

    fragment.appendChild(box);
  });
  if (prepend) {
    container.insertBefore(fragment, container.firstChild);
  } else {
    container.appendChild(fragment);
  }
}

function companyInfoNotesFor(category) {
  const notes = COMPANY_INFO_NOTES[category];
  if (!notes) return [];
  return Array.isArray(notes) ? notes : [notes];
}

/* ============================================================
   UTILS
   ============================================================ */
async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
  return data;
}

function setStatus(el, msg, kind) {
  el.textContent = msg || "";
  el.classList.remove("error", "ok");
  if (kind) el.classList.add(kind);
}

function formatDuration(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return null;
  return seconds.toLocaleString("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function formatKpiNumber(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const formatted = number.toLocaleString("tr-TR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return suffix ? `${formatted} ${suffix}` : formatted;
}

function formatKpiRange(low, high) {
  if (low === null || low === undefined || high === null || high === undefined) return "—";
  if (!Number.isFinite(Number(low)) || !Number.isFinite(Number(high))) return "—";
  return `${formatKpiNumber(low)} – ${formatKpiNumber(high)} TL`;
}

function neutralValuationPosition(status) {
  const normalized = String(status || "").trim().toLocaleLowerCase("tr-TR");
  if (["iskontolu", "az değerli"].includes(normalized)) {
    return "Piyasa fiyatı model ortalamasının altında";
  }
  if (["pahalı", "biraz yüksek"].includes(normalized)) {
    return "Piyasa fiyatı model ortalamasının üzerinde";
  }
  if (normalized === "adil") return "Piyasa fiyatı model ortalamasına yakın";
  return "Model konumu hesaplanamadı";
}

function renderValuationKpis(container, summary) {
  if (!summary) return;

  const targetPeriodReturn = Number(summary.target_period_return_pct);
  const targetPeriodValue = Number.isFinite(targetPeriodReturn)
    ? `${targetPeriodReturn > 0 ? "+%" : targetPeriodReturn < 0 ? "-%" : "%"}${formatKpiNumber(Math.abs(targetPeriodReturn))}`
    : "—";
  const panel = document.createElement("section");
  panel.className = "valuation-kpi-panel";
  panel.setAttribute("aria-label", "Model bazlı değerleme özeti");

  const heading = document.createElement("div");
  heading.className = "valuation-kpi-heading";
  const title = document.createElement("h3");
  title.textContent = "Model Bazlı Değerleme Özeti";
  const period = document.createElement("span");
  period.textContent = summary.period ? `${summary.period} · ${summary.horizon || "İleri değerleme"}` : (summary.horizon || "İleri değerleme");
  heading.append(title, period);
  panel.appendChild(heading);

  const grid = document.createElement("div");
  grid.className = "valuation-kpi-grid";
  const cards = [
    { label: "Güncel Fiyat", value: formatKpiNumber(summary.current_price, "TL") },
    { label: "Model Değerleme Ortalaması", value: formatKpiNumber(summary.average_target, "TL") },
    { label: "Piyasa Fiyatına Göre Model Farkı", value: targetPeriodValue },
    { label: "Model Değerleme Aralığı", value: formatKpiRange(summary.scenario_low, summary.scenario_high) },
    { label: "Veri ve Model Yeterliliği", value: `${summary.confidence || "—"}${Number.isFinite(Number(summary.confidence_score)) ? ` · ${formatKpiNumber(summary.confidence_score)}/100` : ""}` },
    { label: "Piyasa Fiyatının Model Aralığındaki Konumu", value: neutralValuationPosition(summary.status) },
  ];

  cards.forEach((item) => {
    const card = document.createElement("div");
    card.className = `valuation-kpi-card ${item.tone || ""}`.trim();
    const label = document.createElement("span");
    label.className = "valuation-kpi-label";
    label.textContent = item.label;
    const value = document.createElement("strong");
    value.className = "valuation-kpi-value";
    value.textContent = item.value;
    card.append(label, value);
    grid.appendChild(card);
  });

  panel.appendChild(grid);
  container.appendChild(panel);
}

function reportMetadataRows(report) {
  if (!report) return [];
  let generatedAt = report.generated_at || "—";
  if (report.generated_at) {
    const parsed = new Date(report.generated_at);
    if (!Number.isNaN(parsed.getTime())) {
      generatedAt = parsed.toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" });
    }
  }
  const rows = [
    ["Rapor Kimliği", report.report_id || "—"],
    ["Oluşturulma Zamanı", generatedAt],
    ["Finansal Veri Kaynağı", report.financial_source || "—"],
    ["Fiyat Veri Kaynağı", report.price_source || "—"],
    ["Metodoloji Sürümü", report.methodology_version || "—"],
  ];
  if (report.financial_period) rows.splice(2, 0, ["Son Finansal Dönem", report.financial_period]);
  if (report.scope) rows.splice(2, 0, ["Analiz Kapsamı", report.scope]);
  if (report.comparison_method) rows.splice(3, 0, ["Karşılaştırma Yöntemi", report.comparison_method]);
  return rows;
}

function renderReportMetadata(container, report, { prepend = false } = {}) {
  if (!report) return;
  const details = document.createElement("details");
  details.className = "report-metadata";
  details.open = true;
  const summary = document.createElement("summary");
  summary.textContent = "Rapor bilgileri ve veri kapsamı";
  details.appendChild(summary);

  const grid = document.createElement("dl");
  grid.className = "report-metadata-grid";
  reportMetadataRows(report).forEach(([labelText, valueText]) => {
    const item = document.createElement("div");
    const label = document.createElement("dt");
    const value = document.createElement("dd");
    label.textContent = labelText;
    value.textContent = valueText;
    item.append(label, value);
    grid.appendChild(item);
  });
  details.appendChild(grid);

  [report.price_time_note, report.update_policy, report.correction_policy]
    .filter(Boolean)
    .forEach((copy) => {
      const paragraph = document.createElement("p");
      paragraph.textContent = copy;
      details.appendChild(paragraph);
    });
  if (prepend) container.insertBefore(details, container.firstChild);
  else container.appendChild(details);
}

function valuationReportId() {
  return state.company.data?.meta?.rapor_bilgisi?.report_id || "unknown-report";
}

function valuationDisclosureAccepted() {
  return state.company.valuationAcceptedReports.has(valuationReportId());
}

function showValuationDisclosure() {
  const dialog = document.getElementById("valuation-disclosure-dialog");
  if (!dialog) return;
  dialog.dataset.reportId = valuationReportId();
  dialog.dataset.context = "company";
  const reportLabel = dialog.querySelector("[data-disclosure-report-id]");
  if (reportLabel) reportLabel.textContent = valuationReportId();
  if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
}

function showSectorDisclosure(onAccept) {
  const dialog = document.getElementById("valuation-disclosure-dialog");
  if (!dialog) return;
  state.disclosure.pendingAction = onAccept;
  dialog.dataset.context = "sector";
  dialog.dataset.reportId = "Çalıştırılacak sektör analiz raporu";
  const reportLabel = dialog.querySelector("[data-disclosure-report-id]");
  if (reportLabel) reportLabel.textContent = "Analiz tamamlandığında oluşturulacaktır";
  if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
}

function renderValuationDisclosurePlaceholder(container) {
  const notice = document.createElement("section");
  notice.className = "valuation-disclosure-placeholder";
  const title = document.createElement("h3");
  title.textContent = "Değerleme raporu öncesi bilgilendirme";
  const text = document.createElement("p");
  text.textContent = "Bu rapor kişiselleştirilmemiş model çıktıları içerir. Sonuçları görüntülemeden önce kapsam ve risk bilgilendirmesini okuyun.";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "primary";
  button.textContent = "Bilgilendirmeyi Görüntüle";
  button.addEventListener("click", showValuationDisclosure);
  notice.append(title, text, button);
  container.appendChild(notice);
}

function renderValuationWarning(container, message) {
  if (!message) return;
  const warning = document.createElement("section");
  warning.className = "valuation-data-warning";
  warning.setAttribute("role", "status");

  const title = document.createElement("strong");
  title.textContent = "Model bazlı değerleme gösterilemiyor";
  const text = document.createElement("p");
  text.textContent = message;
  warning.append(title, text);
  container.appendChild(warning);
}

function renderSectorCoverageNotice(container, coverage) {
  if (!coverage) return;
  const notice = document.createElement("section");
  notice.className = "sector-coverage-note";
  notice.setAttribute("role", "status");

  const title = document.createElement("strong");
  title.textContent = "Sektör dönem kapsamı";
  notice.appendChild(title);

  const reference = document.createElement("p");
  reference.textContent = `${coverage.reference_period || "—"} referans dönemli grafikler, ${coverage.reference_count || 0}/${coverage.successful_count || 0} karşılaştırılabilir şirketin sabit evreninden oluşturuldu.`;
  notice.appendChild(reference);

  if (coverage.observed_latest_period && coverage.observed_latest_period !== coverage.reference_period) {
    const latest = document.createElement("p");
    latest.textContent = `Sektörde gözlenen en güncel dönem ${coverage.observed_latest_period}; bu dönemi ${coverage.observed_latest_reporter_count || 0}/${coverage.successful_count || 0} şirket açıkladı. Kapsam yeterli olmadığı için toplam grafiklerinde ${coverage.reference_period} kullanıldı.`;
    notice.appendChild(latest);
  }

  const missing = Object.entries(coverage.observed_latest_missing || {});
  if (missing.length) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `${coverage.observed_latest_period || "Son"} dönemi henüz bulunmayan ${missing.length} şirketi göster`;
    const list = document.createElement("p");
    list.textContent = missing.map(([symbol, period]) => `${symbol} (son: ${period})`).join(", ");
    details.append(summary, list);
    notice.appendChild(details);
  } else {
    const complete = document.createElement("p");
    complete.textContent = "Başarıyla analiz edilen şirketlerin tamamında en güncel mali dönem bulunmaktadır.";
    notice.appendChild(complete);
  }

  container.insertBefore(notice, container.firstChild);
}

function formatSummaryCompact(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const absolute = Math.abs(number);
  const scales = [
    [1e12, "tr"],
    [1e9, "mr"],
    [1e6, "mn"],
    [1e3, "bin"],
  ];
  const scale = scales.find(([threshold]) => absolute >= threshold);
  if (!scale) return formatKpiNumber(number);
  return `${(number / scale[0]).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} ${scale[1]}`;
}

function formatSummaryPercent(value) {
  if (value === null || value === undefined || value === "") return "NaN";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const sign = number > 0 ? "+%" : number < 0 ? "-%" : "%";
  return `${sign}${Math.abs(number).toLocaleString("tr-TR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}`;
}

function renderSummaryComparisonTable(titleText, summary, rows, comparisonPeriod) {
  const card = document.createElement("section");
  card.className = "summary-table-card";
  const heading = document.createElement("h3");
  heading.textContent = titleText;
  card.appendChild(heading);

  const tableWrap = document.createElement("div");
  tableWrap.className = "summary-table-scroll";
  const table = document.createElement("table");
  table.className = "summary-compare-table";
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  const previousLabel = comparisonPeriod
    || summary.comparison_period
    || "Önceki Dönem";
  ["", summary.latest_period || "Son Dönem", previousLabel, "%"].forEach((textValue) => {
    const th = document.createElement("th");
    th.textContent = textValue;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  (rows || []).forEach((row) => {
    const tr = document.createElement("tr");
    const label = document.createElement("th");
    label.scope = "row";
    label.textContent = row.label;
    tr.appendChild(label);

    [row.current, row.previous].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value !== null && value !== undefined && Number.isFinite(Number(value))
        ? Math.round(Number(value)).toLocaleString("tr-TR")
        : "—";
      tr.appendChild(td);
    });

    const change = document.createElement("td");
    change.textContent = formatSummaryPercent(row.change_pct);
    const hasNumericChange = row.change_pct !== null && row.change_pct !== undefined;
    const numericChange = hasNumericChange ? Number(row.change_pct) : Number.NaN;
    if (Number.isFinite(numericChange)) {
      const favorable = row.inverse ? numericChange <= 0 : numericChange >= 0;
      change.className = favorable ? "summary-change-positive" : "summary-change-negative";
    }
    tr.appendChild(change);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  card.appendChild(tableWrap);
  return card;
}

function renderSummaryPlot(mount, points, valueKey, titleText, type = "bar") {
  const card = document.createElement("section");
  card.className = type === "line" ? "summary-price-card" : "summary-mini-chart-card";
  const title = document.createElement("h3");
  title.textContent = titleText;
  const plot = document.createElement("div");
  plot.className = type === "line" ? "summary-price-plot" : "summary-mini-plot";
  card.append(title, plot);
  mount.appendChild(card);

  const usable = (points || []).filter((point) => (
    point[valueKey] !== null
    && point[valueKey] !== undefined
    && Number.isFinite(Number(point[valueKey]))
  ));
  if (!usable.length) {
    plot.textContent = "Bu gösterge için yeterli dönem verisi bulunamadı.";
    plot.classList.add("summary-plot-empty");
    return;
  }
  const x = usable.map((point) => point.period);
  const y = usable.map((point) => Number(point[valueKey]));
  const trace = type === "line"
    ? {
        x, y,
        type: "scatter",
        mode: "lines+markers",
        line: { color: "#0D6628", width: 2.5 },
        marker: { color: "#6EAD50", size: 6 },
        fill: "tozeroy",
        fillcolor: "rgba(110,173,80,.16)",
        text: y.map((value) => `${formatKpiNumber(value, "TL")}`),
        hovertemplate: "%{x}<br>%{text}<extra></extra>",
      }
    : {
        x, y,
        type: "bar",
        marker: { color: y.map((value) => value >= 0 ? "#0D6628" : "#FF0000") },
        text: y.map(formatSummaryCompact),
        textangle: 0,
        textposition: "auto",
        textfont: { size: 9, color: "#17341F" },
        cliponaxis: false,
        hovertemplate: "%{x}<br>%{text}<extra></extra>",
      };
  Plotly.newPlot(plot, [trace], {
    autosize: true,
    height: type === "line" ? 235 : 245,
    margin: { l: 54, r: 16, t: 8, b: 48 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#17341F", size: 11 },
    showlegend: false,
    bargap: type === "bar" ? 0.22 : undefined,
    hovermode: "closest",
    xaxis: { showgrid: false, automargin: true, tickfont: { color: "#17341F", size: 11, family: "Arial" }, tickangle: 45 },
    yaxis: { gridcolor: "rgba(13,102,40,.12)", zerolinecolor: "rgba(13,102,40,.22)", automargin: true },
  }, OVERVIEW_PLOT_CONFIG);
}

function renderCompanySummary(container, summary) {
  if (!summary) {
    container.innerHTML = '<p style="color:var(--muted);padding:16px">Özet için yeterli mali dönem bulunamadı.</p>';
    return;
  }

  const dashboard = document.createElement("div");
  dashboard.className = "company-summary-dashboard";
  const header = document.createElement("header");
  header.className = "company-summary-header";
  const identity = document.createElement("div");
  identity.className = "company-summary-identity";
  const symbol = document.createElement("h2");
  symbol.textContent = summary.symbol || "Şirket Özeti";
  const description = document.createElement("span");
  description.textContent = "Gelir tablosu yıllık, bilanço bir önceki dönem karşılaştırması";
  identity.append(symbol, description);
  const badge = document.createElement("span");
  badge.className = "company-summary-period";
  badge.textContent = summary.latest_period || "Son Dönem";
  header.append(identity, badge);
  dashboard.appendChild(header);

  const kpiGrid = document.createElement("section");
  kpiGrid.className = "company-summary-kpis";
  const kpiDefinitions = [
    ["Fiyat", formatKpiNumber(summary.kpis?.price, "TL")],
    ["Piyasa Değeri", formatSummaryCompact(summary.kpis?.market_cap)],
    ["F/K", formatKpiNumber(summary.kpis?.pe)],
    ["PD/DD", formatKpiNumber(summary.kpis?.pb)],
    ["FD/FAVÖK", formatKpiNumber(summary.kpis?.ev_ebitda)],
  ];
  kpiDefinitions.forEach(([labelText, valueText]) => {
    const item = document.createElement("div");
    item.className = "company-summary-kpi";
    const label = document.createElement("span");
    label.textContent = labelText;
    const value = document.createElement("strong");
    value.textContent = valueText;
    item.append(label, value);
    kpiGrid.appendChild(item);
  });
  dashboard.appendChild(kpiGrid);

  // Plotly, DOM'a bağlı olmayan bir öğenin genişliğini ölçemediğinde 700 px
  // varsayılanına döner. Panoyu grafiklerden önce sayfaya bağlayarak her mini
  // grafiğin kendi kartının gerçek genişliğine göre çizilmesini sağla.
  container.appendChild(dashboard);

  renderSummaryPlot(dashboard, summary.price_history, "price", "Dönem Sonu Fiyat Eğilimi", "line");

  const canShowIncome = Boolean(summary.comparison_available);
  const canShowBalance = Boolean(summary.balance_comparison_available);
  if (!canShowIncome && !canShowBalance) {
    const warning = document.createElement("p");
    warning.className = "summary-comparison-warning";
    warning.textContent = `${summary.latest_period || "Son dönem"} için karşılaştırma dönemi bulunamadı; özet tablolar gösterilemedi.`;
    dashboard.appendChild(warning);
  } else {
    if (!canShowIncome) {
      const warning = document.createElement("p");
      warning.className = "summary-comparison-warning";
      warning.textContent = `${summary.latest_period || "Son dönem"} için tam bir yıl önceki aynı mali çeyrek bulunamadı; gelir tablosu karşılaştırması gösterilemedi.`;
      dashboard.appendChild(warning);
    }
    const tables = document.createElement("div");
    tables.className = "company-summary-tables";
    if (canShowIncome) {
      tables.append(
        renderSummaryComparisonTable(
          "Özet Gelir Tablosu",
          summary,
          summary.income_rows,
          summary.comparison_period,
        ),
      );
    }
    if (canShowBalance) {
      tables.append(
        renderSummaryComparisonTable(
          "Özet Bilanço",
          summary,
          summary.balance_rows,
          summary.balance_comparison_period,
        ),
      );
    }
    dashboard.appendChild(tables);
  }

  const charts = document.createElement("div");
  charts.className = "company-summary-quarterly";
  dashboard.appendChild(charts);
  renderSummaryPlot(charts, summary.quarterly, "sales", "Çeyreklik Satışlar");
  renderSummaryPlot(charts, summary.quarterly, "ebitda", "Çeyreklik FAVÖK");
  renderSummaryPlot(charts, summary.quarterly, "net_income", "Çeyreklik Net Kâr");
}

/* ============================================================
   RENDER HELPERS
   ============================================================ */
function renderTables(container, tables, { clear = true } = {}) {
  if (clear) container.innerHTML = "";
  if (!tables || tables.length === 0) {
    if (clear) {
      container.innerHTML = '<p style="color:var(--muted);padding:16px">Bu kategori için tablo bulunamadı.</p>';
    }
    return;
  }
  tables.forEach((t) => {
    const block = document.createElement("div");
    block.className = "block";

    const title = document.createElement("div");
    title.className = "block-title";
    title.textContent = t.name || "Tablo";

    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    wrap.innerHTML = t.html || "";

    block.appendChild(title);
    block.appendChild(wrap);
    container.appendChild(block);
  });
}

function renderFrozenTable(container, tables, { clear = true } = {}) {
  if (clear) container.innerHTML = "";
  if (!tables || tables.length === 0) return;
  tables.forEach((t) => {
    const block = document.createElement("div");
    block.className = "block";

    const title = document.createElement("div");
    title.className = "block-title";
    title.textContent = t.name || "Tablo";

    const wrap = document.createElement("div");
    // table-frozen => first column gets position:sticky via CSS
    wrap.className = "table-wrap table-frozen";
    wrap.innerHTML = t.html || "";

    block.appendChild(title);
    block.appendChild(wrap);
    container.appendChild(block);
  });
}

let chartDivCounter = 0;

const OVERVIEW_PLOT_CONFIG = {
  responsive: true,
  displaylogo: false,
  displayModeBar: false,
  staticPlot: false,
  scrollZoom: false,
  doubleClick: false,
};

const ZOOM_PLOT_CONFIG = {
  responsive: true,
  displaylogo: false,
  displayModeBar: true,
  scrollZoom: true,
  doubleClick: "reset",
  modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
};

function cloneFigure(figure) {
  return JSON.parse(JSON.stringify(figure));
}

function withOverviewLayout(layout) {
  const next = Object.assign({}, layout || {});
  next.dragmode = false;
  return next;
}

function renderCharts(container, charts, { clear = true, emptyMessage = true } = {}) {
  if (clear) container.innerHTML = "";
  if (!charts || charts.length === 0) {
    if (clear && emptyMessage) {
      container.innerHTML = '<p style="color:var(--muted);padding:16px">Bu kategori için grafik bulunamadı.</p>';
    }
    return;
  }

  const plots = [];
  const renderedToggleGroups = new Set();
  const sectionContainers = new Map();
  charts.forEach((chart) => {
    const toggleMeta = chart.figure?.layout?.meta || {};
    const toggleGroup = toggleMeta.chart_toggle_group;
    if (toggleGroup && renderedToggleGroups.has(toggleGroup)) return;

    let chartViews = [chart];
    if (toggleGroup) {
      chartViews = charts
        .filter((item) => item.figure?.layout?.meta?.chart_toggle_group === toggleGroup)
        .sort((a, b) => (
          (a.figure?.layout?.meta?.chart_toggle_order || 0)
          - (b.figure?.layout?.meta?.chart_toggle_order || 0)
        ));
      renderedToggleGroups.add(toggleGroup);
    }

    const primaryMeta = chartViews[0]?.figure?.layout?.meta || {};
    const sectionKey = primaryMeta.analysis_section;
    let chartMount = container;
    if (sectionKey) {
      if (!sectionContainers.has(sectionKey)) {
        const section = document.createElement("section");
        section.className = "chart-analysis-section";
        section.dataset.analysisSection = sectionKey;

        const sectionTitle = document.createElement("h3");
        sectionTitle.className = "chart-analysis-section-title";
        sectionTitle.textContent = primaryMeta.analysis_section_title || "Finansal Değişim Analizi";
        section.appendChild(sectionTitle);
        container.appendChild(section);
        sectionContainers.set(sectionKey, section);
      }
      chartMount = sectionContainers.get(sectionKey);
    }

    const card = document.createElement("div");
    card.className = "chart-card";

    let toggleBar = null;
    if (chartViews.length > 1) {
      toggleBar = document.createElement("div");
      toggleBar.className = "chart-view-toggle pill-group";
      chartViews.forEach((view, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `pill sm${index === 0 ? " active" : ""}`;
        button.textContent = view.figure?.layout?.meta?.chart_toggle_label || `Grafik ${index + 1}`;
        button.dataset.chartViewIndex = String(index);
        toggleBar.appendChild(button);
      });
      card.appendChild(toggleBar);
    }

    const divId = `plotly-chart-${chartDivCounter++}`;
    const plotDiv = document.createElement("div");
    plotDiv.id = divId;
    plotDiv.className = "chart-plot";

    const hint = document.createElement("div");
    hint.className = "chart-zoom-hint";
    hint.textContent = "🔍";

    card.appendChild(plotDiv);
    card.appendChild(hint);
    chartMount.appendChild(card);
    plots.push({ divId, chartViews, card, toggleBar });
  });

  plots.forEach(({ divId, chartViews, card, toggleBar }) => {
    let activeFigure = chartViews[0]?.figure;
    if (!activeFigure) return;
    const gd = document.getElementById(divId);
    Plotly.newPlot(
      divId,
      activeFigure.data || [],
      withOverviewLayout(activeFigure.layout),
      OVERVIEW_PLOT_CONFIG
    );

    if (toggleBar) {
      toggleBar.querySelectorAll("button[data-chart-view-index]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const index = Number(button.dataset.chartViewIndex);
          const nextFigure = chartViews[index]?.figure;
          if (!nextFigure) return;
          activeFigure = nextFigure;
          toggleBar.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
          button.classList.add("active");
          Plotly.react(
            divId,
            activeFigure.data || [],
            withOverviewLayout(activeFigure.layout),
            OVERVIEW_PLOT_CONFIG
          );
        });
      });
    }

    // Ana listede zoom yok; tıklama yalnızca büyütme modalını açar.
    card.addEventListener("click", (e) => {
      if (e.target.closest(".modebar") || e.target.closest(".legend") || e.target.closest(".chart-view-toggle")) return;
      const focused = extractClickedSubplot(activeFigure, gd, e.clientX, e.clientY);
      openChartZoom(focused || activeFigure);
    });
  });
}

/* ============================================================
   GRAFİK BÜYÜTME (ZOOM) MODALI
   ============================================================ */

function stripHtml(text) {
  return String(text == null ? "" : text).replace(/<[^>]+>/g, "").trim();
}

/**
 * Tıklanan subplot'un başlığını bulur. Eski mantık yalnızca yatay mesafeye
 * baktığı için aynı sütundaki üst panel başlığını (örn. Satış Gelirleri)
 * alt panel (örn. Net Faaliyet Kar/Zararı) için de seçebiliyordu.
 */
function resolveSubplotTitle(anns, best, traces) {
  const midX = (best.xd[0] + best.xd[1]) / 2;
  const topY = best.yd[1];

  // 1) Konum: başlık bu panelin üst kenarının hemen üstünde ve x aralığında olmalı
  let bestAnn = null;
  let bestScore = Infinity;
  (anns || []).forEach((a) => {
    if (!a || a.text == null) return;
    if (typeof a.x !== "number" || typeof a.y !== "number") return;
    if (a.x < best.xd[0] - 0.03 || a.x > best.xd[1] + 0.03) return;
    // Üst satırdaki başlıkları ele: yalnızca bu panelin tepesine yakın olanlar
    if (a.y < topY - 0.03 || a.y > topY + 0.22) return;
    const score = Math.abs(a.x - midX) * 2 + Math.abs(a.y - topY);
    if (score < bestScore) {
      bestScore = score;
      bestAnn = a;
    }
  });
  if (bestAnn) return stripHtml(bestAnn.text);

  // 2) Eksen sırası → make_subplots başlık sırası (xaxis, xaxis2, ...)
  const idx = best.xKey === "xaxis"
    ? 0
    : (parseInt(String(best.xKey).replace("xaxis", ""), 10) - 1);
  const titleLike = (anns || []).filter((a) => a && a.text != null && a.showarrow === false);
  if (Number.isFinite(idx) && idx >= 0 && idx < titleLike.length) {
    return stripHtml(titleLike[idx].text);
  }

  // 3) hovertemplate içindeki <extra>kalem adı</extra>
  const ht = traces && traces[0] && traces[0].hovertemplate;
  if (typeof ht === "string") {
    const m = ht.match(/<extra>([^<]*)<\/extra>/);
    if (m && m[1]) return stripHtml(m[1]);
  }
  return null;
}

function extractClickedSubplot(figure, gd, clientX, clientY) {
  const fullLayout = (gd && gd._fullLayout) || {};
  const srcLayout = figure.layout || {};
  const data = figure.data || [];
  if (!data.length) return null;

  const plotEl = gd || null;
  if (!plotEl) return null;
  const rect = plotEl.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;

  const size = fullLayout._size;
  let paperX;
  let paperY;
  if (size && size.w > 0 && size.h > 0) {
    paperX = (clientX - rect.left - size.l) / size.w;
    paperY = 1 - (clientY - rect.top - size.t) / size.h;
  } else {
    paperX = (clientX - rect.left) / rect.width;
    paperY = 1 - (clientY - rect.top) / rect.height;
  }

  const axisKeys = Object.keys(fullLayout).filter((k) => /^[xy]axis\d*$/.test(k));
  const xAxes = axisKeys.filter((k) => k.startsWith("xaxis"));
  const yAxisCount = axisKeys.filter((k) => k.startsWith("yaxis")).length;
  if (xAxes.length <= 1 && yAxisCount <= 1) return null;

  function axisIdFromKey(key) {
    if (key === "xaxis") return "x";
    if (key === "yaxis") return "y";
    return key.replace("axis", "");
  }

  function domainOf(axisKey) {
    const ax = fullLayout[axisKey];
    const d = ax && ax.domain;
    return Array.isArray(d) && d.length === 2 ? d : null;
  }

  let best = null;
  let bestDist = Infinity;
  for (const xKey of xAxes) {
    const suffix = xKey === "xaxis" ? "" : xKey.replace("xaxis", "");
    const yKey = suffix === "" ? "yaxis" : `yaxis${suffix}`;
    if (!fullLayout[yKey]) continue;

    const xd = domainOf(xKey);
    const yd = domainOf(yKey);
    if (!xd || !yd) continue;

    const inX = paperX >= xd[0] - 0.02 && paperX <= xd[1] + 0.02;
    const inY = paperY >= yd[0] - 0.02 && paperY <= yd[1] + 0.02;
    if (!inX || !inY) continue;

    const cx = (xd[0] + xd[1]) / 2;
    const cy = (yd[0] + yd[1]) / 2;
    const dist = (paperX - cx) ** 2 + (paperY - cy) ** 2;
    if (dist < bestDist) {
      bestDist = dist;
      best = { xKey, yKey, xId: axisIdFromKey(xKey), yId: axisIdFromKey(yKey), xd, yd };
    }
  }
  if (!best) return null;

  const traces = data
    .filter((t) => (t.xaxis || "x") === best.xId && (t.yaxis || "y") === best.yId)
    .map((t) => {
      const copy = Object.assign({}, t);
      delete copy.xaxis;
      delete copy.yaxis;
      return copy;
    });
  if (!traces.length) return null;

  const titleText = resolveSubplotTitle(
    fullLayout.annotations || srcLayout.annotations || [],
    best,
    traces
  );

  function cleanAxis(axisKey) {
    const src = srcLayout[axisKey] || {};
    const keep = {};
    ["title", "tickangle", "type", "tickfont", "tickformat", "tickmode", "tickvals", "ticktext", "nticks",
      "showgrid", "gridcolor", "zeroline", "zerolinecolor", "color",
      "linecolor", "automargin", "categoryorder", "categoryarray"].forEach((k) => {
      if (src[k] !== undefined) keep[k] = src[k];
    });
    return keep;
  }

  const newLayout = {
    autosize: true,
    title: titleText
      ? {
          text: titleText,
          font: (srcLayout.title && srcLayout.title.font) || srcLayout.font || undefined,
        }
      : undefined,
    paper_bgcolor: srcLayout.paper_bgcolor,
    plot_bgcolor: srcLayout.plot_bgcolor,
    font: srcLayout.font,
    margin: { l: 70, r: 40, t: titleText ? 70 : 50, b: 90 },
    showlegend: traces.some((t) => t.name && t.showlegend !== false),
    dragmode: "zoom",
    hovermode: srcLayout.hovermode || "closest",
    xaxis: cleanAxis(best.xKey),
    yaxis: cleanAxis(best.yKey),
  };

  return cloneFigure({ data: traces, layout: newLayout });
}

function withZoomNavigation(layout, data) {
  const next = Object.assign({}, layout || {}, {
    autosize: true,
    dragmode: "zoom",
  });
  delete next.height;
  delete next.width;

  // Altta sürüklenen yatay slicer (rangeslider) — mouse pan yerine
  // sağa/sola gezinmeyi kolaylaştırır. Çoklu x ekseni varsa hepsine uygula.
  const xKeys = Object.keys(next).filter((k) => /^xaxis\d*$/.test(k));
  if (xKeys.length === 0) xKeys.push("xaxis");

  xKeys.forEach((key) => {
    const axis = Object.assign({}, next[key] || {});
    axis.rangeslider = Object.assign({}, axis.rangeslider || {}, {
      visible: true,
      thickness: 0.12,
      bgcolor: "rgba(236,241,229,0.88)",
      bordercolor: "rgba(13,102,40,0.24)",
      borderwidth: 1,
    });
    axis.automargin = true;
    next[key] = axis;
  });

  // İlk açılışta tüm seriyi sıkıştırmak yerine son ~12 noktayı göster;
  // kalanına slicer ile kaydırılabilir.
  const firstTrace = (data || []).find((t) => Array.isArray(t.x) && t.x.length > 0);
  if (firstTrace && firstTrace.x.length > 12) {
    const xs = firstTrace.x;
    const start = xs[Math.max(0, xs.length - 12)];
    const end = xs[xs.length - 1];
    next.xaxis = Object.assign({}, next.xaxis || {}, { range: [start, end] });
  }

  // Slicer için alt margin artır
  next.margin = Object.assign({}, next.margin || {}, {
    b: Math.max((next.margin && next.margin.b) || 80, 110),
  });

  return next;
}

function openChartZoom(figure) {
  if (!figure) return;
  const overlay = document.getElementById("chart-zoom-overlay");
  const content = document.getElementById("chart-zoom-content");
  content.innerHTML = "";

  const plotDiv = document.createElement("div");
  plotDiv.id = "chart-zoom-plot";
  plotDiv.className = "chart-zoom-plot";
  content.appendChild(plotDiv);

  overlay.classList.remove("hidden");

  const safe = cloneFigure(figure);
  const layout = withZoomNavigation(safe.layout, safe.data);

  // Overlay görünür olduktan sonra çiz; aksi halde yükseklik 0 kalıp boş modal oluşuyor.
  requestAnimationFrame(() => {
    const compactViewport = window.innerWidth <= 640 || window.innerHeight <= 520;
    const minimumHeight = compactViewport ? 240 : 420;
    const fallbackSpace = window.innerHeight - (compactViewport ? 80 : 140);
    const h = Math.max(minimumHeight, Math.floor(content.clientHeight || fallbackSpace));
    plotDiv.style.width = "100%";
    plotDiv.style.height = `${h}px`;
    Plotly.newPlot(plotDiv.id, safe.data || [], layout, ZOOM_PLOT_CONFIG).then(() => {
      Plotly.Plots.resize(plotDiv);
    });
  });
}

function closeChartZoom() {
  const overlay = document.getElementById("chart-zoom-overlay");
  const content = document.getElementById("chart-zoom-content");
  const plot = document.getElementById("chart-zoom-plot");
  if (plot) {
    try { Plotly.purge(plot); } catch (e) { /* yoksay */ }
  }
  content.innerHTML = "";
  overlay.classList.add("hidden");
}

function initChartZoom() {
  const overlay = document.getElementById("chart-zoom-overlay");
  document.getElementById("chart-zoom-close").addEventListener("click", closeChartZoom);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeChartZoom();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.classList.contains("hidden")) closeChartZoom();
  });
}

/* ============================================================
   SEKTÖR ANALİZİ
   ============================================================ */
function renderSector() {
  const { data, mode, imgFilter } = state.sector;
  if (!data) return;

  const content = document.getElementById("sector-content");
  const imgFilterBar = document.getElementById("sector-img-filter-bar");

  // Görsel alt filtresi sadece image modunda görünür
  if (mode === "image") {
    imgFilterBar.classList.remove("hidden");
  } else {
    imgFilterBar.classList.add("hidden");
  }

  if (mode === "table") {
    renderFrozenTable(content, data.tables);
    prependInfoNotes(content, [SECTOR_INFO_NOTES.table]);
  } else {
    const filtered =
      imgFilter === "all"
        ? data.charts
        : data.charts.filter((chart) => chart.category === imgFilter);
    renderCharts(content, filtered);
    const notes =
      imgFilter === "all"
        ? [SECTOR_INFO_NOTES.bar, SECTOR_INFO_NOTES.heatmap, SECTOR_INFO_NOTES.sector_financials]
        : [SECTOR_INFO_NOTES[imgFilter]];
    prependInfoNotes(content, notes);
  }
  renderReportMetadata(content, data.meta?.rapor_bilgisi, { prepend: true });
  renderSectorCoverageNotice(content, data.meta?.sektor_donem_kapsami);
}

async function initSector() {
  const sektorSel    = document.getElementById("sector-sektor");
  const turSel       = document.getElementById("sector-analiz-turu");
  const excelSel     = document.getElementById("sector-excel");
  const piotroskiEl  = document.getElementById("sector-piotroski");
  const runBtn       = document.getElementById("run-sector");
  const status       = document.getElementById("sector-status");
  const toolbar      = document.getElementById("sector-toolbar");

  // Seçenekleri yükle
  const opts = await fetchJson("/api/sector/options");
  (opts.sektorler || []).forEach((s) => {
    const o = document.createElement("option");
    o.value = s; o.textContent = s;
    sektorSel.appendChild(o);
  });
  (opts.analiz_turu || []).forEach((s) => {
    const o = document.createElement("option");
    o.value = s; o.textContent = s;
    turSel.appendChild(o);
  });
  (opts.excel_kaydet || []).forEach((s) => {
    const o = document.createElement("option");
    o.value = s; o.textContent = s;
    excelSel.appendChild(o);
  });

  // Mod pill'leri
  document.querySelectorAll("#sector-toolbar .pill[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#sector-toolbar .pill[data-mode]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.sector.mode = btn.dataset.mode;
      renderSector();
    });
  });

  // Görsel alt filtresi
  document.querySelectorAll("#sector-img-filter-bar .pill[data-img-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#sector-img-filter-bar .pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.sector.imgFilter = btn.dataset.imgFilter;
      renderSector();
    });
  });

  // Analizi çalıştır
  runBtn.addEventListener("click", async () => {
    if (!state.sector.disclosureAccepted) {
      showSectorDisclosure(() => runBtn.click());
      return;
    }
    const sureMesaji = piotroskiEl.checked
      ? " Piotroski F-Skoru da hesaplandığı için işlem biraz daha uzun sürebilir."
      : " Bu işlem birkaç dakika sürebilir.";
    setStatus(status, `Şirket verileri hazırlanıyor…${sureMesaji}`, null);
    runBtn.disabled = true;
    toolbar.classList.add("hidden");
    document.getElementById("sector-content").innerHTML = "";

    // Reset state
    state.sector.mode = "table";
    state.sector.imgFilter = "all";
    document.querySelectorAll("#sector-toolbar .pill[data-mode]").forEach((b) => b.classList.remove("active"));
    document.getElementById("sector-mode-table").classList.add("active");
    document.querySelectorAll("#sector-img-filter-bar .pill").forEach((b) => b.classList.remove("active"));
    document.querySelector("#sector-img-filter-bar .pill[data-img-filter='all']").classList.add("active");

    try {
      const payload = {
        sektor: sektorSel.value,
        analiz_turu: turSel.value,
        excel_durum: excelSel.value,
        piotroski_hesapla: piotroskiEl.checked,
      };
      const out = await fetchJson("/api/sector/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.sector.data = out;
      toolbar.classList.remove("hidden");
      renderSector();
      const failedCount = Object.keys(out.meta?.basarisiz_hisseler || {}).length;
      const requestedCount = out.meta?.istenen_hisse_sayisi;
      const successfulCount = out.meta?.basarili_hisse_sayisi;
      const totalDuration = formatDuration(out.meta?.sureler_saniye?.toplam);
      const durationText = totalDuration ? ` Süre: ${totalDuration} sn.` : "";
      const completionText = failedCount
        ? `Kısmi tamamlandı: ${successfulCount}/${requestedCount} hisse başarılı, ${failedCount} hisse başarısız.${durationText}`
        : `Tamamlandı: ${successfulCount}/${requestedCount} hisse analiz edildi.${durationText}`;
      setStatus(status, completionText, failedCount ? null : "ok");
    } catch (e) {
      setStatus(status, e.message || String(e), "error");
    } finally {
      runBtn.disabled = false;
      state.sector.disclosureAccepted = false;
    }
  });
}

/* ============================================================
   ŞİRKET ANALİZİ
   ============================================================ */
function renderCompany() {
  const { data, mode, category } = state.company;
  if (!data) return;

  const content = document.getElementById("company-content");
  content.innerHTML = "";

  const allowedNames = COMPANY_TABLE_MAP[category] || [];
  const filteredTables = data.tables.filter((t) => allowedNames.includes(t.name));
  const filteredCharts = data.charts.filter((chart) => chart.category === category);
  const isSummary = category === "özet";
  const isTableOnly = category === "dikey";
  const report = data.meta?.rapor_bilgisi;
  const valuationRequiresDisclosure = (
    category === "değerleme"
    && Boolean(report?.valuation_created)
    && !valuationDisclosureAccepted()
  );
  document.querySelector(".company-sidebar .sidebar-toggle")?.classList.toggle("hidden", isSummary || isTableOnly);

  if (valuationRequiresDisclosure) {
    renderValuationDisclosurePlaceholder(content);
    requestAnimationFrame(showValuationDisclosure);
    return;
  }

  // Skor: grafik modunda da tablolar + bilgi notu görünsün (bu kategoride grafik yok).
  const showTables = !isSummary && (mode === "table" || category === "skor" || isTableOnly);
  const showCharts = !isSummary && !isTableOnly && mode === "image";

  if (isSummary) {
    renderCompanySummary(content, data.meta?.sirket_ozeti);
  }

  if (category === "değerleme") {
    renderReportMetadata(content, report);
    renderValuationWarning(content, data.meta?.degerleme_uyarisi);
  }

  if (showTables) {
    renderFrozenTable(content, filteredTables, { clear: false });
  }
  if (showCharts) {
    if (category === "değerleme") {
      renderValuationKpis(content, data.meta?.yil_sonu_degerleme_kpi);
    }
    renderCharts(content, filteredCharts, {
      clear: false,
      emptyMessage: category !== "skor",
    });
  }

  prependInfoNotes(content, companyInfoNotesFor(category), { prepend: !isSummary });
}

function initValuationDisclosure() {
  const dialog = document.getElementById("valuation-disclosure-dialog");
  const acceptButton = document.getElementById("valuation-disclosure-accept");
  const backButton = document.getElementById("valuation-disclosure-back");
  if (!dialog || !acceptButton || !backButton) return;

  acceptButton.addEventListener("click", () => {
    if (dialog.dataset.context === "sector") {
      state.sector.disclosureAccepted = true;
      const pendingAction = state.disclosure.pendingAction;
      state.disclosure.pendingAction = null;
      dialog.close();
      if (typeof pendingAction === "function") pendingAction();
      return;
    }
    const reportId = dialog.dataset.reportId || valuationReportId();
    state.company.valuationAcceptedReports.add(reportId);
    try {
      localStorage.setItem(
        `fm-valuation-disclosure:${reportId}`,
        JSON.stringify({
          accepted_at: new Date().toISOString(),
          disclosure_version: VALUATION_DISCLOSURE_VERSION,
        })
      );
    } catch (error) {
      // Tarayıcı depolaması kapalı olsa da mevcut oturumda kabul kaydı korunur.
    }
    dialog.close();
    renderCompany();
  });

  const returnToSummary = () => {
    if (dialog.dataset.context === "sector") {
      state.disclosure.pendingAction = null;
      if (dialog.open) dialog.close();
      return;
    }
    if (dialog.open) dialog.close();
    state.company.category = "özet";
    document.querySelectorAll(".cat-btn").forEach((button) => button.classList.remove("active"));
    document.querySelector(".cat-btn[data-cat='özet']")?.classList.add("active");
    renderCompany();
  };
  backButton.addEventListener("click", returnToSummary);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    returnToSummary();
  });
}

async function initCompany() {
  const hisseEl    = document.getElementById("company-hisse");
  const degerEl    = document.getElementById("company-degerleme");
  const runBtn     = document.getElementById("run-company");
  const status     = document.getElementById("company-status");
  const resultsArea= document.getElementById("company-results-area");

  // Seçenekleri yükle
  const opts = await fetchJson("/api/company/options");
  (opts.degerleme || []).forEach((s) => {
    const o = document.createElement("option");
    o.value = s; o.textContent = s;
    degerEl.appendChild(o);
  });
  // Mod toggle (Tablo / Görsel)
  document.querySelectorAll(".sidebar-toggle .pill[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".sidebar-toggle .pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.company.mode = btn.dataset.mode;
      renderCompany();
    });
  });

  // Kategori butonları
  document.querySelectorAll(".cat-btn[data-cat]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cat-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.company.category = btn.dataset.cat;
      renderCompany();
    });
  });

  // Analizi çalıştır
  runBtn.addEventListener("click", async () => {
    const hisse = (hisseEl.value || "").trim().toUpperCase();
    if (!hisse) {
      setStatus(status, "Analize başlamak için bir BIST hisse kodu girin.", "error");
      hisseEl.focus();
      return;
    }
    setStatus(status, "Finansal veriler hazırlanıyor… Seçimlerinize göre bu işlem birkaç dakika sürebilir.", null);
    runBtn.disabled = true;
    resultsArea.classList.add("hidden");
    document.getElementById("company-content").innerHTML = "";

    // Reset state
    state.company.mode = "table";
    state.company.category = "özet";
    document.querySelectorAll(".sidebar-toggle .pill").forEach((b) => b.classList.remove("active"));
    document.getElementById("company-mode-table").classList.add("active");
    document.querySelectorAll(".cat-btn").forEach((b) => b.classList.remove("active"));
    document.querySelector(".cat-btn[data-cat='özet']").classList.add("active");

    try {
      const payload = {
        hisse,
        degerleme: degerEl.value,
      };
      const out = await fetchJson("/api/company/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.company.data = out;
      resultsArea.classList.remove("hidden");
      renderCompany();
      const timings = out.meta?.sureler_saniye || {};
      const totalDuration = formatDuration(timings.toplam);
      const dataDuration = formatDuration(timings.finansal_veri_ve_fiyat);
      const forecastDuration = formatDuration(timings.tahmin_ve_degerleme);
      const timingParts = [];
      if (totalDuration) timingParts.push(`toplam ${totalDuration} sn`);
      if (dataDuration) timingParts.push(`veri ${dataDuration} sn`);
      if (forecastDuration && Number(timings.tahmin_ve_degerleme) > 0) {
        timingParts.push(`değerleme ${forecastDuration} sn`);
      }
      const timingText = timingParts.length ? ` Süre: ${timingParts.join(" · ")}.` : "";
      setStatus(status, `${hisse} analizi tamamlandı.${timingText} Sonuçları aşağıdaki kategorilerden inceleyebilirsiniz.`, "ok");
    } catch (e) {
      setStatus(status, e.message || String(e), "error");
    } finally {
      runBtn.disabled = false;
    }
  });
}

/* ============================================================
   ANA SEKMELER
   ============================================================ */
function switchMainTab(key) {
  document.querySelectorAll(".main-tab").forEach((b) => b.classList.remove("active"));
  const targetTab = document.querySelector(`.main-tab[data-tab="${key}"]`);
  if (targetTab) targetTab.classList.add("active");
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  document.getElementById(`tab-${key}`).classList.add("active");
}

function initMainTabs() {
  document.querySelectorAll(".main-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchMainTab(btn.dataset.tab));
  });
  // Giriş sayfasındaki "Analize Başla" kısayol butonları
  document.querySelectorAll("[data-goto-tab]").forEach((btn) => {
    btn.addEventListener("click", () => switchMainTab(btn.dataset.gotoTab));
  });
}

/* ============================================================
   BAŞLATMA
   ============================================================ */
window.addEventListener("load", async () => {
  initMainTabs();
  initChartZoom();
  initValuationDisclosure();
  try {
    await initSector();
    await initCompany();
  } catch (e) {
    console.error("Init error:", e);
  }
});
