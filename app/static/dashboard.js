const API = "/api/v1";
const TOKEN_KEY = "iems_token";
const ROLE_KEY = "iems_role";
const fmt = (n, d = 2) => (n == null || Number.isNaN(Number(n)) ? "—" : Number(n).toFixed(d));
const C = {
  power: "#1a6b2a",
  fuel: "#1f4e79",
  steam: "#8a5a12",
  feed: "#5a3d7a",
  carbon: "#8b1e1e",
  grid: "#d0d0d0",
  axis: "#333333",
  spark: "#7cbf4a",
  hist: "#6b1515",
};

const plantEl = document.getElementById("plant");
const errorBox = document.getElementById("errorBox");
const okBox = document.getElementById("okBox");
let timer = null;
let lastPoints = [];
let lastLive = null;
let chartMode = "carriers";

const USER_KEY = "iems_user";
const ACTIONS_KEY = "iems_actions";
let notifTimer = null;
let knownAlertIds = new Set();
let roleActions = {
  read: true,
  predict: true,
  operate: true,
  train: true,
  apply: true,
  settings: true,
};

function token() { return localStorage.getItem(TOKEN_KEY) || ""; }
function authHeaders(json = true) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  if (token()) h.Authorization = "Bearer " + token();
  const totp = document.getElementById("totp")?.value?.trim();
  if (totp) h["X-2FA-Code"] = totp;
  return h;
}
function showError(m) { errorBox.textContent = m; errorBox.classList.add("show"); okBox.classList.remove("show"); }
function showOk(m) { okBox.textContent = m; okBox.classList.add("show"); errorBox.classList.remove("show"); }
function clearMsg() { errorBox.classList.remove("show"); okBox.classList.remove("show"); }
function setStatus(k, t) {
  document.getElementById("statusDot").className = "dot " + k;
  document.getElementById("statusText").textContent = t;
}

function defaultActionsForRole(role) {
  if (role === "admin") return { read: true, predict: true, operate: true, train: true, apply: true, settings: true };
  if (role === "operator") return { read: true, predict: true, operate: true, train: true, apply: false, settings: false };
  if (role === "viewer") return { read: true, predict: false, operate: false, train: false, apply: false, settings: false };
  return { read: true, predict: true, operate: true, train: true, apply: true, settings: true };
}

function applyRoleUi() {
  const role = localStorage.getItem(ROLE_KEY);
  const user = localStorage.getItem(USER_KEY);
  try {
    const saved = localStorage.getItem(ACTIONS_KEY);
    if (saved) roleActions = { ...defaultActionsForRole(role), ...JSON.parse(saved) };
    else roleActions = defaultActionsForRole(role);
  } catch {
    roleActions = defaultActionsForRole(role);
  }
  document.querySelectorAll("[data-require]").forEach((el) => {
    const need = el.dataset.require;
    const ok = !!roleActions[need];
    el.classList.toggle("locked", !ok);
    if (el.tagName === "BUTTON" || el.tagName === "A") {
      if ("disabled" in el) el.disabled = !ok;
    }
  });
  document.getElementById("authChip").textContent = token()
    ? ((user || "user") + " · " + role)
    : "guest";
}

function refreshAuthChip() {
  applyRoleUi();
}

function syncShiftCsvLink() {
  /* plant change only — download bound below */
}

document.getElementById("btnShiftCsv").onclick = async () => {
  try {
    await downloadAuthed(
      `/operator/shift-report.csv?plant_code=${encodeURIComponent(plantEl.value)}`,
      `shift_${plantEl.value}.csv`
    );
    showOk("shift CSV downloaded");
  } catch (e) { showError(e.message); }
};

function updateNotifBadge(count) {
  const badge = document.getElementById("notifBadge");
  if (!badge) return;
  if (count > 0) {
    badge.textContent = String(count);
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

function showNotifToast(msg) {
  const box = document.getElementById("notifToast");
  if (!box) return;
  box.textContent = msg;
  box.classList.remove("hidden");
  box.classList.add("show");
  setTimeout(() => { box.classList.remove("show"); box.classList.add("hidden"); }, 4000);
}

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { ...authHeaders(!(opts.body instanceof FormData)), ...(opts.headers || {}) },
  });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!res.ok) {
    const detail = body?.detail
      ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail))
      : ("HTTP " + res.status);
    throw new Error(detail);
  }
  return body;
}

function prep(canvas, h) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 200;
  canvas.width = Math.floor(w * dpr);
  canvas.height = Math.floor(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function drawSpark(canvas, points, key, color, h) {
  const { ctx, w } = prep(canvas, h);
  ctx.clearRect(0, 0, w, h);
  if (!points || points.length < 2) return;
  const vals = points.map((p) => Number(p[key] || 0));
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const top = 2, bottom = h - 2;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = (i / (vals.length - 1)) * w;
    const y = bottom - ((v - min) / span) * (bottom - top);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.6;
  ctx.stroke();
}

function drawAxes(ctx, left, right, top, bottom) {
  ctx.strokeStyle = C.grid;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = top + ((bottom - top) * i) / 4;
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
  }
  for (let i = 0; i <= 8; i++) {
    const x = left + ((right - left) * i) / 8;
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
  }
  ctx.strokeStyle = C.axis;
  ctx.strokeRect(left, top, right - left, bottom - top);
}

function drawMain() {
  const { ctx, w, h } = prep(document.getElementById("chartMain"), 280);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  const pts = lastPoints;
  const legend = document.getElementById("chartLegend");
  const left = 42, right = w - 12, top = 14, bottom = h - 22;
  drawAxes(ctx, left, right, top, bottom);

  if (!pts || pts.length < 2) {
    ctx.fillStyle = "#666";
    ctx.font = "600 13px Tahoma";
    ctx.textAlign = "center";
    ctx.fillText("waiting for backend stream…", (left + right) / 2, (top + bottom) / 2);
    legend.innerHTML = "";
    return;
  }

  const xAt = (i) => left + (i / (pts.length - 1)) * (right - left);
  ctx.fillStyle = "#333";
  ctx.font = "11px Consolas";
  ctx.textAlign = "right";
  ctx.fillText("Amplitude", left - 6, top + 10);

  if (chartMode === "carriers") {
    document.getElementById("chartTitle").textContent = "Energy Signal";
    const series = [
      { key: "electricity_power_mw", color: C.power, name: "Power" },
      { key: "fuel_gas_flow_km3h", color: C.fuel, name: "Fuel" },
      { key: "steam_flow_tonh", color: C.steam, name: "Steam" },
      { key: "feed_flow_tonh", color: C.feed, name: "Feed" },
    ];
    series.forEach((s) => {
      const vals = pts.map((p) => Number(p[s.key] || 0));
      const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
      ctx.beginPath();
      vals.forEach((v, i) => {
        const y = bottom - ((v - min) / span) * (bottom - top);
        if (i === 0) ctx.moveTo(xAt(i), y); else ctx.lineTo(xAt(i), y);
      });
      ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.stroke();
    });
    legend.innerHTML = series.map((s) => `<span><i class="lg lg-${s.name.toLowerCase()}"></i>${s.name}</span>`).join("");
  } else {
    document.getElementById("chartTitle").textContent = "Intensity Signal";
    function line(key, color) {
      const vals = pts.map((p) => Number(p[key] || 0));
      const min = Math.min(...vals), max = Math.max(...vals);
      const pad = (max - min) * 0.12 || 1;
      const y0 = min - pad, span = max - min + 2 * pad;
      ctx.beginPath();
      vals.forEach((v, i) => {
        const y = bottom - ((v - y0) / span) * (bottom - top);
        if (i === 0) ctx.moveTo(xAt(i), y); else ctx.lineTo(xAt(i), y);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    }
    line("energy_intensity_kgoe_ton", C.power);
    line("carbon_intensity_kgco2_ton", C.carbon);
    legend.innerHTML = `<span><i class="lg lg-power"></i>energy_intensity</span><span><i class="lg lg-carbon"></i>carbon_intensity</span>`;
  }
}

function drawGauge() {
  const { ctx, w, h } = prep(document.getElementById("chartGauge"), 180);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  const p = Math.max(0, Math.min(100, Number(lastLive?.energy_efficiency_percent) || 0));
  const cx = w / 2, cy = h * 0.78, r = Math.min(w, h) * 0.48;
  ctx.lineWidth = 14; ctx.lineCap = "round";
  ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI);
  ctx.strokeStyle = "#d8d8d8"; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI + Math.PI * (p / 100));
  ctx.strokeStyle = p > 70 ? C.power : p > 50 ? C.steam : C.carbon;
  ctx.stroke();
  ctx.fillStyle = "#111";
  ctx.font = "700 22px Consolas";
  ctx.textAlign = "center";
  ctx.fillText(fmt(p, 1) + "%", cx, cy - 8);
  ctx.font = "12px Tahoma";
  ctx.fillStyle = "#555";
  ctx.fillText("efficiency", cx, cy + 14);
}

function drawHist() {
  const canvas = document.getElementById("chartHist");
  const { ctx, w, h } = prep(canvas, 180);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  const left = 36, right = w - 12, top = 12, bottom = h - 24;
  drawAxes(ctx, left, right, top, bottom);

  const s1 = Math.max(0, Number(lastLive?.scope1_kgco2) || 0);
  const s2 = Math.max(0, Number(lastLive?.scope2_kgco2) || 0);
  const intensity = Math.max(0, Number(lastLive?.energy_intensity_kgoe_ton) || 0);
  const carbon = Math.max(0, Number(lastLive?.carbon_intensity_kgco2_ton) || 0);
  const power = Math.max(0, Number(lastLive?.electricity_power_mw) || 0);
  const bars = [
    { label: "S1", v: s1 / 1000 },
    { label: "S2", v: s2 / 1000 },
    { label: "EI", v: intensity / 50 },
    { label: "CI", v: carbon / 40 },
    { label: "MW", v: power / 10 },
  ];
  const max = Math.max(...bars.map((b) => b.v), 0.1);
  const gap = 10;
  const bw = ((right - left) - gap * (bars.length + 1)) / bars.length;
  bars.forEach((b, i) => {
    const x = left + gap + i * (bw + gap);
    const bh = (b.v / max) * (bottom - top - 8);
    ctx.fillStyle = C.hist;
    ctx.fillRect(x, bottom - bh, bw, bh);
    ctx.fillStyle = "#333";
    ctx.font = "11px Tahoma";
    ctx.textAlign = "center";
    ctx.fillText(b.label, x + bw / 2, bottom + 14);
  });
  ctx.fillStyle = "#333";
  ctx.font = "11px Consolas";
  ctx.textAlign = "right";
  ctx.fillText("histogram", left - 4, top + 10);
}

function drawScopes() {
  // kept for API parity / hidden canvas — histogram is the visible Scope view
  drawHist();
}

function redrawCharts() {
  drawSpark(document.getElementById("sideSpark"), lastPoints, "electricity_power_mw", C.spark, 40);
  drawMain();
  drawGauge();
  drawHist();
}

function plantLabel(code) {
  const map = { olefin: "Olefin", pta: "PTA" };
  return map[code] || (code || "—").toUpperCase();
}

function renderLive(data) {
  lastLive = data;
  const code = data.plant_code || plantEl.value;
  document.getElementById("vPlant").textContent = plantLabel(code);
  document.getElementById("vPower").textContent = fmt(data.electricity_power_mw);
  document.getElementById("vFuel").textContent = fmt(data.fuel_gas_flow_km3h);
  document.getElementById("vSteam").textContent = fmt(data.steam_flow_tonh);
  document.getElementById("vFeed").textContent = fmt(data.feed_flow_tonh);
  document.getElementById("sidePower").textContent = fmt(data.electricity_power_mw);
  document.getElementById("asOf").textContent = data.as_of ? new Date(data.as_of).toISOString().slice(11, 19) + "Z" : "—";
  document.getElementById("age").textContent = fmt(data.data_age_seconds, 1) + "s";
  document.getElementById("efficiency").textContent = "η " + fmt(data.energy_efficiency_percent, 1) + "%";
  document.getElementById("headerMeta").textContent = fmt(data.energy_intensity_kgoe_ton, 1) + " kgoe/t";
  const bar = document.getElementById("pageTitle");
  if (bar) {
    const q = data.quality ? (" · Q=" + data.quality) : "";
    const src = data.source ? (" · " + data.source) : "";
    bar.textContent = "Graph · REAL_TIME · " + plantLabel(code) + src + q;
  }
}

async function tickLive() {
  const plant = plantEl.value;
  try {
    const [live, hist] = await Promise.all([
      api(`/dashboard/energy?plant_code=${encodeURIComponent(plant)}`),
      api(`/dashboard/energy/history?plant_code=${encodeURIComponent(plant)}&minutes=15`),
    ]);
    lastPoints = hist.points || [];
    renderLive(live);
    redrawCharts();
    const k = live.stream_status === "ok" ? "ok" : live.stream_status === "stale" ? "stale" : "down";
    const q = live.quality ? (" · " + live.quality) : "";
    const src = live.source ? (" · " + live.source) : "";
    setStatus(
      k,
      k === "ok"
        ? ("backend · 1 Hz" + src + q)
        : ("stream · " + live.stream_status + src + q)
    );
    errorBox.classList.remove("show");
  } catch (e) {
    setStatus("down", "backend offline");
    showError("API: " + e.message);
  }
}

const sidebar = document.getElementById("sidebar");
document.getElementById("menuToggle")?.addEventListener("click", () => {
  sidebar.classList.toggle("open");
});

function setActiveView(view) {
  document.querySelectorAll(".nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  document.querySelectorAll("#mainTabs [data-view-tab]").forEach((b) => {
    if (view === "notifications") {
      b.classList.toggle("active", b.dataset.viewTab === "notifications");
    } else if (view === "live") {
      if (b.dataset.viewTab === "notifications") b.classList.remove("active");
    } else {
      b.classList.remove("active");
    }
  });
  const title = document.getElementById("pageTitle");
  if (title && view === "live") title.textContent = "Graph · REAL_TIME";
  sidebar.classList.remove("open");
  clearMsg();
  if (view === "live") requestAnimationFrame(redrawCharts);
  if (view === "notifications") loadNotifications();
  if (view === "optimize") loadControlLive();
  if (view === "carbon") loadReportingLive();
  if (view === "auth") loadConnectionLive();
}

document.querySelectorAll(".nav button").forEach((btn) => {
  btn.addEventListener("click", () => setActiveView(btn.dataset.view));
});

document.querySelectorAll("#mainTabs [data-view-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.viewTab;
    if (view === "live") {
      if (btn.dataset.mode) chartMode = btn.dataset.mode;
      if (btn.dataset.sub) chartMode = "carriers";
      setActiveView("live");
      document.querySelectorAll("#mainTabs [data-view-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      drawMain();
    } else {
      setActiveView(view);
    }
  });
});

async function loadNotifications(silent = false) {
  const body = document.getElementById("notificationsBody");
  const meta = document.getElementById("notificationsMeta");
  try {
    if (!silent) body.innerHTML = "<tr><td colspan='6'>Loading…</td></tr>";
    const rows = await api("/alerts");
    const ids = new Set(rows.map((r) => r.id));
    const fresh = [...ids].filter((id) => !knownAlertIds.has(id));
    if (knownAlertIds.size && fresh.length) {
      showNotifToast(fresh.length + " new notification(s)");
    }
    knownAlertIds = ids;
    updateNotifBadge(rows.length);
    if (meta) meta.textContent = rows.length + " open · polled live · severity map active";
    if (!rows.length) {
      body.innerHTML = "<tr><td colspan='6'>No open notifications</td></tr>";
      return;
    }
    const canResolve = !!roleActions.operate;
    body.innerHTML = rows.map((a) => {
      const sev = a.severity || "warning";
      return `<tr>
      <td><span class="sev sev-${sev}">${sev}</span></td>
      <td class="ltr">${a.id}</td><td>${a.plant_code || "—"}</td><td>${a.alert_type || "—"}</td>
      <td>${a.message || "—"}</td>
      <td>${!a.resolved_at && canResolve
        ? `<button class="btn btn-sm" data-resolve="${a.id}" data-require="operate">ack</button>`
        : (!a.resolved_at ? "view-only" : "resolved")}</td>
    </tr>`;
    }).join("");
    body.querySelectorAll("[data-resolve]").forEach((b) => {
      b.onclick = async () => {
        try {
          await api(`/alerts/${b.dataset.resolve}/resolve`, { method: "POST" });
          showOk("notification acknowledged");
          loadNotifications(true);
        } catch (e) { showError(e.message); }
      };
    });
  } catch (e) {
    if (!silent) body.innerHTML = "<tr><td colspan='6'>Failed to load notifications</td></tr>";
    if (!silent) showError(e.message);
  }
}

function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function downloadAuthed(path, filename) {
  const res = await fetch(API + path, { headers: authHeaders(false) });
  if (!res.ok) throw new Error("download failed: HTTP " + res.status);
  const blob = await res.blob();
  downloadBlob(filename, blob);
}

function renderReportsTable(rows) {
  const body = document.getElementById("reportsBody");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = "<tr><td colspan='8'>No reports</td></tr>";
    return;
  }
  body.innerHTML = rows.map((r) => `<tr>
    <td class="ltr">${r.id}</td>
    <td>${r.plant_code}</td>
    <td>${r.period_type}</td>
    <td class="ltr">${fmt(r.scope1_kgco2, 1)}</td>
    <td class="ltr">${fmt(r.scope2_kgco2, 1)}</td>
    <td class="ltr">${fmt(r.scope3_kgco2, 1)}</td>
    <td class="ltr">${r.assurance_status || "draft"}</td>
    <td>
      <button type="button" class="btn btn-sm" data-pack="${r.id}" data-fmt="html">ESG pack</button>
      <button type="button" class="btn btn-sm" data-pack="${r.id}" data-fmt="csv">Pack CSV</button>
      <button type="button" class="btn btn-sm" data-sub="${r.id}" data-require="operate">submit</button>
      <button type="button" class="btn btn-sm" data-apr="${r.id}" data-require="operate">approve</button>
      <button type="button" class="btn btn-sm" data-lck="${r.id}" data-require="settings">lock</button>
    </td>
  </tr>`).join("");
  applyRoleUi();
  body.querySelectorAll("[data-pack]").forEach((b) => {
    b.onclick = async () => {
      try {
        await downloadAuthed(
          `/carbon/reports/${b.dataset.pack}/pack?format=${b.dataset.fmt}`,
          `esg_pack_${b.dataset.pack}.${b.dataset.fmt === "html" ? "html" : "csv"}`
        );
        showOk("ESG pack download started");
      } catch (e) { showError(e.message); }
    };
  });
  body.querySelectorAll("[data-sub]").forEach((b) => {
    b.onclick = async () => {
      try {
        carbonOut.textContent = JSON.stringify(await api(`/carbon/reports/${b.dataset.sub}/submit`, {
          method: "POST", body: JSON.stringify({ comment: "shift submit" }),
        }), null, 2);
        showOk("submitted for review");
        const listed = await api(`/carbon/reports?plant_code=${encodeURIComponent(plantEl.value)}`);
        renderReportsTable(listed);
      } catch (e) { showError(e.message); }
    };
  });
  body.querySelectorAll("[data-apr]").forEach((b) => {
    b.onclick = async () => {
      try {
        carbonOut.textContent = JSON.stringify(await api(`/carbon/reports/${b.dataset.apr}/approve`, {
          method: "POST", body: JSON.stringify({ comment: "assurance approve" }),
        }), null, 2);
        showOk("approved");
        const listed = await api(`/carbon/reports?plant_code=${encodeURIComponent(plantEl.value)}`);
        renderReportsTable(listed);
      } catch (e) { showError(e.message); }
    };
  });
  body.querySelectorAll("[data-lck]").forEach((b) => {
    b.onclick = async () => {
      try {
        carbonOut.textContent = JSON.stringify(await api(`/carbon/reports/${b.dataset.lck}/lock`, {
          method: "POST", body: JSON.stringify({ comment: "lock for market" }),
        }), null, 2);
        showOk("locked");
        const listed = await api(`/carbon/reports?plant_code=${encodeURIComponent(plantEl.value)}`);
        renderReportsTable(listed);
      } catch (e) { showError(e.message); }
    };
  });
}

document.getElementById("btnPredict").onclick = async () => {
  try {
    predictOut.textContent = JSON.stringify(await api("/ml/predict", {
      method: "POST",
      body: JSON.stringify({ plant_code: plantEl.value, model: modelSel.value, horizon_minutes: 60 }),
    }), null, 2);
    showOk("predict ok");
  } catch (e) { showError(e.message); }
};
document.getElementById("btnTrain").onclick = async () => {
  try {
    predictOut.textContent = JSON.stringify(await api("/ml/train", {
      method: "POST",
      body: JSON.stringify({ plant_code: plantEl.value, model: modelSel.value }),
    }), null, 2);
    showOk("train ok");
  } catch (e) { showError(e.message); }
};
document.getElementById("btnWhatIf").onclick = async () => {
  try {
    predictOut.textContent = JSON.stringify(await api("/ml/what-if", {
      method: "POST",
      body: JSON.stringify({
        plant_code: plantEl.value, model: modelSel.value,
        reactor_temp_c: 400 + Number(wiTemp.value),
        feed_flow_tonh: 100 + Number(wiFeed.value),
        fuel_gas_flow_km3h: 100, steam_flow_tonh: 30, electricity_power_mw: 15,
      }),
    }), null, 2);
  } catch (e) { showError(e.message); }
};

async function renderRecs(list) {
  const body = document.getElementById("recsBody");
  if (!list.length) { body.innerHTML = "<tr><td colspan='6'>no recommendations</td></tr>"; return; }
  body.innerHTML = list.map((r) => {
    const saving = r.realized_saving_kwh_per_h != null
      ? `real ${fmt(r.realized_saving_kwh_per_h)}`
      : `est ${fmt(r.estimated_energy_saving_kwh_per_h)}`;
    const actions = r.id ? [
      `<button class="btn btn-sm" data-sim="${r.id}" data-require="operate">sim</button>`,
      `<button class="btn btn-sm" data-acc="${r.id}" data-require="operate">accept</button>`,
      `<button class="btn btn-sm" data-rej="${r.id}" data-require="operate">reject</button>`,
      `<button class="btn btn-sm" data-apr="${r.id}" data-require="operate">approve</button>`,
      `<button class="btn btn-sm" data-apl="${r.id}" data-require="apply">apply</button>`,
      `<button class="btn btn-sm" data-imp="${r.id}" data-require="operate">impact</button>`,
      `<button class="btn btn-sm" data-aud="${r.id}" data-require="operate">audit</button>`,
    ].join(" ") : "";
    return `<tr>
    <td class="ltr">${r.id ?? "—"}</td>
    <td class="ltr">${r.status || "pending"}</td>
    <td>${r.title || "—"}</td>
    <td class="ltr cell-wrap">${JSON.stringify(r.current || {})} → ${JSON.stringify(r.proposed || {})}</td>
    <td class="ltr">${saving} kWh/h</td>
    <td>${actions}</td>
  </tr>`;
  }).join("");
  applyRoleUi();
  body.querySelectorAll("[data-sim]").forEach((b) => {
    b.onclick = async () => {
      try { optOut.textContent = JSON.stringify(await api(`/optimization/recommendations/${b.dataset.sim}/simulate`, { method: "POST", body: "{}" }), null, 2); }
      catch (e) { showError(e.message); }
    };
  });
  body.querySelectorAll("[data-acc],[data-rej]").forEach((b) => {
    b.onclick = async () => {
      const decision = b.hasAttribute("data-acc") ? "accepted" : "rejected";
      const id = b.dataset.acc || b.dataset.rej;
      try {
        optOut.textContent = JSON.stringify(await api(`/optimization/recommendations/${id}/feedback`, {
          method: "POST",
          body: JSON.stringify({ decision, operator: localStorage.getItem(USER_KEY) || localStorage.getItem(ROLE_KEY) || "operator" }),
        }), null, 2);
        showOk("feedback saved");
      } catch (e) { showError(e.message); }
    };
  });
  body.querySelectorAll("[data-apr]").forEach((b) => {
    b.onclick = async () => {
      try {
        optOut.textContent = JSON.stringify(await api(`/optimization/recommendations/${b.dataset.apr}/approve`, {
          method: "POST", body: JSON.stringify({ comment: "shift approve" }),
        }), null, 2);
        showOk("approved");
      } catch (e) { showError(e.message); }
    };
  });
  body.querySelectorAll("[data-apl]").forEach((b) => {
    b.onclick = async () => {
      try {
        optOut.textContent = JSON.stringify(await api(`/optimization/recommendations/${b.dataset.apl}/apply`, {
          method: "POST", body: JSON.stringify({ dry_run: true }),
        }), null, 2);
        showOk("apply (dry-run) ok");
      } catch (e) { showError(e.message); }
    };
  });
  body.querySelectorAll("[data-imp]").forEach((b) => {
    b.onclick = async () => {
      try {
        optOut.textContent = JSON.stringify(await api(`/optimization/recommendations/${b.dataset.imp}/impact`), null, 2);
        showOk("impact measured");
      } catch (e) { showError(e.message); }
    };
  });
  body.querySelectorAll("[data-aud]").forEach((b) => {
    b.onclick = async () => {
      try {
        optOut.textContent = JSON.stringify(await api(`/optimization/recommendations/${b.dataset.aud}/audit`), null, 2);
      } catch (e) { showError(e.message); }
    };
  });
}

document.getElementById("btnAnalyze").onclick = async () => {
  try {
    await runAnalyze();
    showOk("analyze ok");
  } catch (e) { showError(e.message); }
};
document.getElementById("btnRecs").onclick = async () => {
  try {
    const rows = await api(`/optimization/recommendations?plant_code=${encodeURIComponent(plantEl.value)}`);
    optOut.textContent = JSON.stringify(rows, null, 2);
    await renderRecs(rows);
    const saveEl = document.getElementById("optSave");
    const countEl = document.getElementById("optCount");
    if (countEl) countEl.textContent = String(rows.length);
    if (saveEl) {
      saveEl.textContent = fmt(rows.reduce((s, r) => s + Number(r.estimated_energy_saving_kwh_per_h || 0), 0));
    }
  } catch (e) { showError(e.message); }
};

async function runAnalyze() {
  const out = await api("/optimization/analyze", {
    method: "POST",
    body: JSON.stringify({
      plant_codes: [plantEl.value, plantEl.value === "olefin" ? "pta" : "olefin"],
      simulate: true, persist: true,
    }),
  });
  optOut.textContent = JSON.stringify(out, null, 2);
  await renderRecs(out.advice || []);
  const saveEl = document.getElementById("optSave");
  const countEl = document.getElementById("optCount");
  if (saveEl) saveEl.textContent = fmt(out.total_estimated_saving_kwh_per_h);
  if (countEl) countEl.textContent = String((out.advice || []).length);
  try {
    const live = await api(`/dashboard/energy?plant_code=${encodeURIComponent(plantEl.value)}`);
    const p = document.getElementById("optPower");
    const e = document.getElementById("optEff");
    if (p) p.textContent = fmt(live.electricity_power_mw);
    if (e) e.textContent = fmt(live.energy_efficiency_percent);
  } catch { /* ignore */ }
  return out;
}

async function loadControlLive() {
  try {
    await runAnalyze();
  } catch (e) {
    optOut.textContent = "Control live load failed: " + e.message;
    showError(e.message);
  }
}

async function loadReportingLive() {
  try {
    const scopes = await api(`/carbon/scopes?plant_code=${encodeURIComponent(plantEl.value)}`);
    carbonOut.textContent = JSON.stringify(scopes, null, 2);
    const s1 = document.getElementById("cS1");
    const s2 = document.getElementById("cS2");
    const cint = document.getElementById("cInt");
    if (s1) s1.textContent = fmt(scopes.scope1_kgco2, 1);
    if (s2) s2.textContent = fmt(scopes.scope2_kgco2, 1);
    if (cint) cint.textContent = fmt(scopes.carbon_intensity_kgco2_ton, 2);
    let listed = await api(`/carbon/reports?plant_code=${encodeURIComponent(plantEl.value)}`);
    if (!listed.length) {
      await api("/carbon/reports/generate", {
        method: "POST",
        body: JSON.stringify({ plant_codes: [plantEl.value], period_types: ["daily"], completed_only: false }),
      });
      listed = await api(`/carbon/reports?plant_code=${encodeURIComponent(plantEl.value)}`);
    }
    const crep = document.getElementById("cRep");
    if (crep) crep.textContent = String(listed.length);
    renderReportsTable(listed);
  } catch (e) {
    carbonOut.textContent = "Reporting live load failed: " + e.message;
    showError(e.message);
  }
}

async function loadConnectionLive() {
  const out = document.getElementById("connectOut");
  try {
    const status = await api("/ingestion/plant-connect/status");
    const me = token() ? await api("/auth/me").catch(() => null) : null;
    const health = await fetch("/health").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const payload = { connection: status, me, health };
    if (out) out.textContent = JSON.stringify(payload, null, 2);
    const mode = document.getElementById("connMode");
    const feeder = document.getElementById("connFeeder");
    const opc = document.getElementById("connOpc");
    const stream = document.getElementById("connStream");
    if (mode) mode.textContent = status.plant_connect ? "Plant Connect" : "Demo / sim";
    if (feeder) feeder.textContent = status.demo_feeder ? "ON" : "off";
    if (opc) opc.textContent = status.opc_session_connected ? "up" : "idle";
    const live0 = (status.live && status.live[0]) || null;
    if (stream) stream.textContent = live0 ? (live0.stream || live0.source || "ok") : "—";
    if (me && document.getElementById("authOut")) {
      authOut.textContent = JSON.stringify(me, null, 2);
    }
  } catch (e) {
    if (out) out.textContent = "Connection load failed: " + e.message;
    showError(e.message);
  }
}

document.getElementById("btnScopes").onclick = async () => {
  try {
    const scopes = await api(`/carbon/scopes?plant_code=${encodeURIComponent(plantEl.value)}`);
    carbonOut.textContent = JSON.stringify(scopes, null, 2);
    const s1 = document.getElementById("cS1");
    const s2 = document.getElementById("cS2");
    const cint = document.getElementById("cInt");
    if (s1) s1.textContent = fmt(scopes.scope1_kgco2, 1);
    if (s2) s2.textContent = fmt(scopes.scope2_kgco2, 1);
    if (cint) cint.textContent = fmt(scopes.carbon_intensity_kgco2_ton, 2);
  }
  catch (e) { showError(e.message); }
};
document.getElementById("btnGenReport").onclick = async () => {
  try {
    const out = await api("/carbon/reports/generate", {
      method: "POST",
      body: JSON.stringify({ plant_codes: [plantEl.value], period_types: ["daily"], completed_only: false }),
    });
    carbonOut.textContent = JSON.stringify(out, null, 2);
    showOk("report generated");
    const listed = await api(`/carbon/reports?plant_code=${encodeURIComponent(plantEl.value)}`);
    const crep = document.getElementById("cRep");
    if (crep) crep.textContent = String(listed.length);
    renderReportsTable(listed);
  } catch (e) { showError(e.message); }
};
document.getElementById("btnListReports").onclick = async () => {
  try {
    const rows = await api(`/carbon/reports?plant_code=${encodeURIComponent(plantEl.value)}`);
    carbonOut.textContent = JSON.stringify(rows, null, 2);
    const crep = document.getElementById("cRep");
    if (crep) crep.textContent = String(rows.length);
    renderReportsTable(rows);
  } catch (e) { showError(e.message); }
};
document.getElementById("btnMarket").onclick = async () => {
  try { carbonOut.textContent = JSON.stringify(await api(`/carbon/market/sync?plant_code=${encodeURIComponent(plantEl.value)}`, { method: "POST" }), null, 2); }
  catch (e) { showError(e.message); }
};
document.getElementById("btnMarketHist").onclick = async () => {
  try { carbonOut.textContent = JSON.stringify(await api(`/carbon/market/syncs?plant_code=${encodeURIComponent(plantEl.value)}`), null, 2); }
  catch (e) { showError(e.message); }
};

document.getElementById("btnConnectRefresh")?.addEventListener("click", () => loadConnectionLive());

async function refreshMe() {
  if (!token()) {
    applyRoleUi();
    return;
  }
  try {
    const me = await api("/auth/me");
    localStorage.setItem(USER_KEY, me.username);
    localStorage.setItem(ROLE_KEY, me.role);
    localStorage.setItem(ACTIONS_KEY, JSON.stringify(me.actions || {}));
    roleActions = me.actions || defaultActionsForRole(me.role);
    applyRoleUi();
    if (document.getElementById("authOut")) {
      authOut.textContent = JSON.stringify(me, null, 2);
    }
  } catch {
    applyRoleUi();
  }
}

document.getElementById("btnLogin").onclick = async () => {
  try {
    const body = { username: user.value, password: pass.value };
    if (totp.value.trim()) body.totp_code = totp.value.trim();
    const out = await api("/auth/login", { method: "POST", body: JSON.stringify(body) });
    localStorage.setItem(TOKEN_KEY, out.access_token);
    localStorage.setItem(ROLE_KEY, out.role);
    localStorage.setItem(USER_KEY, user.value);
    await refreshMe();
    authOut.textContent = JSON.stringify(out, null, 2);
    showOk("login ok — role UI applied");
    loadNotifications(true);
  } catch (e) { showError(e.message); }
};
document.getElementById("btnLogout").onclick = () => {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(ACTIONS_KEY);
  roleActions = defaultActionsForRole(null);
  applyRoleUi();
  showOk("logged out");
};
document.getElementById("btnPatchSettings").onclick = async () => {
  try {
    authOut.textContent = JSON.stringify(await api("/settings", {
      method: "PATCH",
      body: JSON.stringify({ stale_data_seconds: 8 }),
    }), null, 2);
    showOk("settings patched");
  } catch (e) { showError(e.message); }
};
document.getElementById("btnMe").onclick = () => refreshMe();

document.getElementById("btnShiftSummary").onclick = async () => {
  try {
    const out = await api(`/operator/shift-summary?plant_code=${encodeURIComponent(plantEl.value)}`);
    const meta = document.getElementById("shiftMeta");
    const list = document.getElementById("shiftChecklist");
    if (meta) {
      meta.textContent = `open notifications: ${out.open_notifications} · stream: ${out.plant?.stream_status || "—"} · power: ${fmt(out.plant?.electricity_power_mw)} MW`;
    }
    if (list && out.checklist) {
      list.innerHTML = out.checklist.map((c) => `<li>${c}</li>`).join("");
    }
    showOk("shift briefing loaded");
  } catch (e) { showError(e.message); }
};

document.getElementById("loadNotifications").onclick = () => loadNotifications(false);
document.getElementById("refreshNotifications").onclick = () => loadNotifications(false);
document.getElementById("refreshBtn").onclick = tickLive;
plantEl.onchange = () => { syncShiftCsvLink(); tickLive(); };
window.addEventListener("resize", redrawCharts);

function registerPwa() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
}

refreshAuthChip();
refreshMe();
syncShiftCsvLink();
registerPwa();
setInterval(() => {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString("en-GB", { hour12: false });
}, 1000);
tickLive();
timer = setInterval(tickLive, 1000);
loadNotifications(true);
notifTimer = setInterval(() => loadNotifications(true), 20000);
