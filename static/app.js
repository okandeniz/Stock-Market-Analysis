/* ============================================================
   STATE
   ============================================================ */
const state = {
  sector: {
    data: null,          // { tables, images, meta }
    mode: "table",       // "table" | "image"
    imgFilter: "all",    // "all" | "bar" | "heatmap"
  },
  company: {
    data: null,
    mode: "table",       // "table" | "image"
    category: "büyüme",  // active category key
  },
};

/* ============================================================
   CATEGORY → TABLE/IMAGE MAPPING  (Şirket Analizi)
   ============================================================ */
const COMPANY_TABLE_MAP = {
  "büyüme":    ["Dönemsel Farklar (Şelale)", "Büyüme Oranları"],
  "karlılık":  ["Kar Marjları"],
  "bilanço":   ["Bilanço Dengesi"],
  "likidite":  ["Likidite"],
  "verimlilik":["Nakit Döngüsü"],
  "nakit":     ["Nakit Akımı"],
  "değerleme": ["Çarpanlar", "Gelecek Dönem Değerleme"],
  "skor":      ["Skor Kartı (Kategori Skorları)"],
};

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

/* ============================================================
   RENDER HELPERS
   ============================================================ */
function renderTables(container, tables) {
  container.innerHTML = "";
  if (!tables || tables.length === 0) {
    container.innerHTML = '<p style="color:var(--muted);padding:16px">Bu kategori için tablo bulunamadı.</p>';
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

function renderFrozenTable(container, tables) {
  container.innerHTML = "";
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

function renderImages(container, images) {
  container.innerHTML = "";
  if (!images || images.length === 0) {
    container.innerHTML = '<p style="color:var(--muted);padding:16px">Bu kategori için görsel bulunamadı.</p>';
    return;
  }
  images.forEach((img) => {
    const card = document.createElement("div");
    card.className = "img-card";

    const image = document.createElement("img");
    image.src = img.url;
    image.alt = img.name || "plot";
    image.loading = "lazy";

    const cap = document.createElement("div");
    cap.className = "img-caption";
    cap.textContent = img.name || "";

    card.appendChild(image);
    card.appendChild(cap);
    container.appendChild(card);
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
  } else {
    const filtered =
      imgFilter === "all"
        ? data.images
        : data.images.filter((img) => img.category === imgFilter);
    renderImages(content, filtered);
  }
}

async function initSector() {
  const sektorSel = document.getElementById("sector-sektor");
  const turSel    = document.getElementById("sector-analiz-turu");
  const excelSel  = document.getElementById("sector-excel");
  const runBtn    = document.getElementById("run-sector");
  const status    = document.getElementById("sector-status");
  const toolbar   = document.getElementById("sector-toolbar");

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
    setStatus(status, "Çalışıyor… (bu işlem sürebilir)", null);
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
      };
      const out = await fetchJson("/api/sector/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.sector.data = out;
      toolbar.classList.remove("hidden");
      renderSector();
      setStatus(status, "Tamamlandı.", "ok");
    } catch (e) {
      setStatus(status, e.message || String(e), "error");
    } finally {
      runBtn.disabled = false;
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

  if (mode === "table") {
    const allowedNames = COMPANY_TABLE_MAP[category] || [];
    const filtered = data.tables.filter((t) => allowedNames.includes(t.name));
    renderFrozenTable(content, filtered);   // İlk kolon (tarih/Bilanço) donuk
  } else {
    const filtered = data.images.filter((img) => img.category === category);
    renderImages(content, filtered);
  }
}

async function initCompany() {
  const hisseEl    = document.getElementById("company-hisse");
  const degerEl    = document.getElementById("company-degerleme");
  const hazirWrap  = document.getElementById("company-hazir-wrap");
  const hazirEl    = document.getElementById("company-hazir");
  const evdsEl     = document.getElementById("company-evds");
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
  (opts.hazir_tahmin || []).forEach((s) => {
    const o = document.createElement("option");
    o.value = s; o.textContent = s;
    hazirEl.appendChild(o);
  });

  // EVDS alanı referansları
  const evdsBadge   = document.getElementById("evds-badge");
  const evdsOptText = document.getElementById("evds-opt-text");

  // Hazır tahmin göster/gizle + EVDS zorunluluk göstergesi
  function syncHazir() {
    const dv = (degerEl.value || "").toUpperCase();
    const hv = (hazirEl.value || "").toUpperCase();
    hazirWrap.classList.toggle("hidden", dv !== "EVET");

    // API Key yalnızca "EVET + HAYIR" kombinasyonunda zorunlu
    const needsKey = dv === "EVET" && hv === "HAYIR";
    evdsBadge.classList.toggle("hidden", !needsKey);
    evdsOptText.classList.toggle("hidden", needsKey);
    evdsEl.placeholder = needsKey
      ? "EVDS API Key zorunlu (TUFE tahmini için)"
      : "ENV yoksa buraya girin (opsiyonel)";
  }
  degerEl.addEventListener("change", syncHazir);
  hazirEl.addEventListener("change", syncHazir);
  syncHazir();

  // API Key şifre göster/gizle
  document.getElementById("show-evds-key").addEventListener("change", (e) => {
    evdsEl.type = e.target.checked ? "text" : "password";
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
    setStatus(status, "Çalışıyor… (hisse verisi/EVDS çağrıları uzun sürebilir)", null);
    runBtn.disabled = true;
    resultsArea.classList.add("hidden");
    document.getElementById("company-content").innerHTML = "";

    // Reset state
    state.company.mode = "table";
    state.company.category = "büyüme";
    document.querySelectorAll(".sidebar-toggle .pill").forEach((b) => b.classList.remove("active"));
    document.getElementById("company-mode-table").classList.add("active");
    document.querySelectorAll(".cat-btn").forEach((b) => b.classList.remove("active"));
    document.querySelector(".cat-btn[data-cat='büyüme']").classList.add("active");

    try {
      const payload = {
        hisse: (hisseEl.value || "").trim().toUpperCase(),
        degerleme: degerEl.value,
        hazir_tahmin: degerEl.value === "EVET" ? hazirEl.value : null,
        evds_api_key: (evdsEl.value || "").trim(),
      };
      const out = await fetchJson("/api/company/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.company.data = out;
      resultsArea.classList.remove("hidden");
      renderCompany();
      setStatus(status, "Tamamlandı.", "ok");
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
function initMainTabs() {
  document.querySelectorAll(".main-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".main-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const key = btn.dataset.tab;
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      document.getElementById(`tab-${key}`).classList.add("active");
    });
  });
}

/* ============================================================
   BAŞLATMA
   ============================================================ */
window.addEventListener("load", async () => {
  initMainTabs();
  try {
    await initSector();
    await initCompany();
  } catch (e) {
    console.error("Init error:", e);
  }
});
