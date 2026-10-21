/* AegisRisk frontend – vanilla JS, no build step. */
const BASE = (window.AEGIS_API_BASE || "").replace(/\/$/, "");
const S = { token: sessionStorage.getItem("aegis_token"), user: null, sound: false, demo: false, page: null,
            seen: new Set(), feed: [], lastSeen: null, timers: [], charts: [], map: null, selected: null, filter: "ALL", alerts: 0 };
const $ = (s, r = document) => r.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = n => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const CITIES = ["Hyderabad", "Chennai", "Bangalore", "Mumbai", "Pune", "Delhi", "Jaipur", "Kolkata"];
const MERCH = ["Groceries", "Food Delivery", "Fuel", "Utilities", "Travel", "Online Electronics", "Luxury Boutique", "Gift Cards", "Wire Transfer", "Crypto Onramp"];
const cls = s => s === "HIGH RISK" ? "HIGH" : s === "CONFIRMED_LEGIT" ? "CONFIRMED" : s;
const label = s => ({ "HIGH RISK": "High risk", REVIEW: "In review", SAFE: "Safe", BLOCKED: "Blocked", CONFIRMED_LEGIT: "Confirmed legit", OPEN: "Open", INVESTIGATING: "Investigating", CLOSED: "Closed" }[s] || s);
const colorOf = s => s === "HIGH RISK" || s === "BLOCKED" ? "#c8283f" : s === "REVIEW" ? "#c98513" : "#23805f";
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

async function api(path, o = {}) {
  const r = await fetch(BASE + path, { method: o.method || "GET", body: o.body ? JSON.stringify(o.body) : undefined,
    headers: { "Content-Type": "application/json", ...(S.token ? { Authorization: "Bearer " + S.token } : {}) } });
  if (r.status === 401 && S.token && !path.includes("/auth/login")) { signOut(true); throw new Error("Session expired"); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || "Request failed (" + r.status + ")");
  return d;
}
function toast(msg, kind = "") {
  const t = document.createElement("div"); t.className = "toast " + kind; t.textContent = msg;
  $("#toasts").append(t); setTimeout(() => t.remove(), 5200);
}
function countUp(el, to, fmt = v => Math.round(v).toLocaleString("en-IN")) {
  if (!el) return; const from = Number(el.dataset.v || 0); el.dataset.v = to;
  if (reduce || from === to) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = t => { const k = Math.min(1, (t - t0) / 700), e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function siren() {
  if (!S.sound) return;
  try { const a = new (window.AudioContext || window.webkitAudioContext)(); [0, .28, .56].forEach((d, i) => {
    const o = a.createOscillator(), g = a.createGain(); o.type = "square"; o.frequency.value = i % 2 ? 660 : 880;
    g.gain.value = .06; o.connect(g); g.connect(a.destination); o.start(a.currentTime + d); o.stop(a.currentTime + d + .22); }); } catch (e) {}
}

/* ================= threat map (canvas) ================= */
const POS = { Chennai: [13.08, 80.27], Hyderabad: [17.385, 78.487], Mumbai: [19.076, 72.878], Delhi: [28.614, 77.209],
  Bangalore: [12.972, 77.595], Kolkata: [22.573, 88.364], Pune: [18.52, 73.857], Jaipur: [26.912, 75.787] };
const OUTLINE = [[8.1,77.5],[10,76.2],[13,74.8],[15.5,73.8],[19,72.8],[21,72.6],[22.3,69],[23.7,68.2],[24.5,71],[27,70.2],[30,74],[32.5,75],[35,77],[35.5,78.5],[32.5,79],[30.5,81],[28,84],[27.3,88],[27.8,89],[26.8,92],[28.2,95.5],[27.5,97],[25,95],[23,93.5],[22,92],[21.5,89],[20,86.8],[17,82.5],[15,80.2],[13,80.3],[10.5,79.8],[8.5,78]];
class ThreatMap {
  constructor(cv, { ambient = true } = {}) { this.cv = cv; this.ctx = cv.getContext("2d"); this.ev = []; this.heat = {}; this.ambient = ambient;
    this.resize(); this._r = () => this.resize(); addEventListener("resize", this._r); this.run = true; this.loop(); }
  destroy() { this.run = false; removeEventListener("resize", this._r); }
  resize() { const d = devicePixelRatio || 1, w = this.cv.clientWidth, h = this.cv.clientHeight; this.cv.width = w * d; this.cv.height = h * d;
    this.ctx.setTransform(d, 0, 0, d, 0, 0); this.w = w; this.h = h; }
  p([la, lo]) { const s = Math.min(this.w / 31, this.h / 31) * .97, ox = (this.w - 31 * s) / 2, oy = (this.h - 31 * s) / 2;
    return [ox + (lo - 67) * s, oy + (36.5 - la) * s]; }
  fire(t) { const to = POS[t.location], from = POS[t.prev_location || t.location]; if (!to) return;
    const c = colorOf(t.status); this.heat[t.location] = Math.min(1, (this.heat[t.location] || 0) + (t.status === "SAFE" ? .05 : .3));
    this.ev.push({ k: "pulse", at: to, c, t0: performance.now() });
    if (from && from !== to) this.ev.push({ k: "arc", from, to, c, t0: performance.now() }); }
  loop() { if (!this.run) return; this.draw(performance.now()); if (!reduce) requestAnimationFrame(() => this.loop()); }
  draw(now) {
    const x = this.ctx; x.clearRect(0, 0, this.w, this.h);
    x.save(); x.beginPath(); OUTLINE.forEach((q, i) => { const [a, b] = this.p(q); i ? x.lineTo(a, b) : x.moveTo(a, b); }); x.closePath();
    x.fillStyle = "rgba(255,255,255,.04)"; x.fill(); x.clip();
    const g = Math.max(7, this.w / 70); x.fillStyle = "rgba(150,185,200,.28)";
    for (let i = 0; i < this.w; i += g) for (let j = 0; j < this.h; j += g) x.fillRect(i, j, 1.6, 1.6);
    x.restore(); x.beginPath(); OUTLINE.forEach((q, i) => { const [a, b] = this.p(q); i ? x.lineTo(a, b) : x.moveTo(a, b); }); x.closePath();
    x.strokeStyle = "rgba(150,185,200,.25)"; x.stroke();
    if (this.ambient && !reduce) { const a = (now / 5000) % (Math.PI * 2), c = this.p([20, 79]);
      x.beginPath(); x.moveTo(...c); x.arc(c[0], c[1], Math.max(this.w, this.h), a, a + .35); x.closePath();
      x.fillStyle = "rgba(60,180,170,.05)"; x.fill(); }
    for (const [city, ll] of Object.entries(POS)) { const [a, b] = this.p(ll), h = this.heat[city] = Math.max(0, (this.heat[city] || 0) - .0008);
      x.beginPath(); x.arc(a, b, 3 + h * 6, 0, 7); x.fillStyle = h > .25 ? `rgba(224,70,90,${.5 + h / 2})` : "#7fd1c4"; x.fill();
      x.fillStyle = "rgba(200,220,228,.7)"; x.font = "11px Instrument Sans, sans-serif"; x.fillText(city, a + 8, b + 4); }
    this.ev = this.ev.filter(e => now - e.t0 < 2400);
    for (const e of this.ev) { const k = (now - e.t0) / 2400;
      if (e.k === "pulse") { const [a, b] = this.p(e.at); x.beginPath(); x.arc(a, b, 4 + k * 38, 0, 7); x.strokeStyle = e.c; x.globalAlpha = 1 - k; x.lineWidth = 2; x.stroke(); x.globalAlpha = 1; }
      else { const A = this.p(e.from), B = this.p(e.to), m = [(A[0] + B[0]) / 2, Math.min(A[1], B[1]) - 50], kk = Math.min(1, k * 2);
        x.beginPath(); x.moveTo(...A); x.quadraticCurveTo(...m, ...B); x.strokeStyle = e.c; x.globalAlpha = (1 - k) * .8; x.lineWidth = 1.5; x.setLineDash([5, 4]); x.stroke(); x.setLineDash([]);
        const u = kk, px = (1 - u) ** 2 * A[0] + 2 * (1 - u) * u * m[0] + u * u * B[0], py = (1 - u) ** 2 * A[1] + 2 * (1 - u) * u * m[1] + u * u * B[1];
        x.beginPath(); x.arc(px, py, 3.5, 0, 7); x.fillStyle = e.c; x.globalAlpha = 1 - k * .6; x.fill(); x.globalAlpha = 1; } }
    if (reduce) return;
  }
}

/* ================= shared widgets ================= */
function gauge(score, status) {
  const len = 169.6, col = colorOf(status), off = len * (1 - Math.min(100, score) / 100);
  return `<div class="gauge" data-score="${score}"><svg viewBox="0 0 140 80"><path class="arc bg" d="M16 70 A54 54 0 0 1 124 70"/>
    <path class="arc fg" data-off="${off}" style="stroke:${col}" stroke-dasharray="${len}" stroke-dashoffset="${len}" d="M16 70 A54 54 0 0 1 124 70"/></svg>
    <div class="val"><span class="gv" data-v="0">0</span>%<small>fraud risk</small></div></div>`;
}
function animateIn(root) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    root.querySelectorAll(".gauge .fg").forEach(p => p.setAttribute("stroke-dashoffset", p.dataset.off));
    root.querySelectorAll(".gauge").forEach(g => countUp(g.querySelector(".gv"), Math.min(99, Math.round(Number(g.dataset.score)))));
    root.querySelectorAll(".factor .bar i[data-w]").forEach(i => i.style.width = i.dataset.w + "%");
    root.querySelectorAll(".mini-bar i[data-w]").forEach(i => i.style.width = i.dataset.w + "%");
  }));
}
function factors(list) {
  if (!list?.length) return `<p class="muted small">No single signal moved this score noticeably.</p>`;
  const mx = Math.max(...list.map(f => Math.abs(f.impact)), 1);
  return list.slice(0, 6).map(f => `<div class="factor"><div>${esc(f.factor)}<small>${esc(f.detail)}</small></div>
    <div class="bar"><i class="${f.direction}" data-w="${Math.abs(f.impact) / mx * 50}"></i></div>
    <b class="num">${f.impact > 0 ? "+" : ""}${f.impact}</b></div>`).join("") +
    `<p class="muted small">Points of fraud probability each signal added (red) or removed (green) versus a typical safe payment.</p>`;
}
const pill = s => `<span class="pill ${cls(s)}">${label(s)}</span>`;
function clearTimers() { S.timers.forEach(clearInterval); S.timers = []; S.charts.forEach(c => c.destroy()); S.charts = []; if (S.map) { S.map.destroy(); S.map = null; } }

/* ================= auth & shell ================= */
let heroMap;
function startHero() {
  heroMap = new ThreatMap($("#hero-map")); const demo = [["Hyderabad", "Kolkata", "HIGH RISK"], ["Chennai", "Delhi", "REVIEW"], ["Mumbai", "Mumbai", "SAFE"], ["Bangalore", "Jaipur", "HIGH RISK"], ["Pune", "Pune", "SAFE"]];
  let i = 0; const tick = () => { const [a, b, s] = demo[i++ % demo.length]; heroMap.fire({ prev_location: a, location: b, status: s }); };
  tick(); S.heroTimer = setInterval(tick, 1800);
}
$("#login-form").addEventListener("submit", async e => {
  e.preventDefault(); const btn = $("#login-btn"), err = $("#auth-error"); err.hidden = true; btn.disabled = true; btn.textContent = "Signing in…";
  try { const d = await api("/api/auth/login", { method: "POST", body: { email: $("#email").value, password: $("#password").value } });
    S.token = d.token; sessionStorage.setItem("aegis_token", d.token); S.user = d.user; enter();
  } catch (x) { err.textContent = x.message; err.hidden = false; } finally { btn.disabled = false; btn.textContent = "Sign in"; }
});
document.querySelectorAll(".role-pick button").forEach(b => b.onclick = () => {
  document.querySelectorAll(".role-pick button").forEach(x => x.classList.toggle("on", x === b));
  $("#email").value = b.dataset.email; $("#password").value = "pass123"; });
async function signOut(silent) {
  try { if (!silent) await api("/api/auth/logout", { method: "POST" }); } catch (e) {}
  clearTimers(); sessionStorage.removeItem("aegis_token"); S.token = null; S.user = null; S.seen.clear(); S.feed = []; S.lastSeen = null;
  $("#app").hidden = true; $("#auth").hidden = false; if (!heroMap) startHero(); setTimeout(() => heroMap?.resize(), 0);
  if (silent) toast("Your session ended. Sign in again.", "warn");
}
const NAV = {
  RISK_OFFICER: [["dash", "Live overview"], ["analytics", "Fraud analytics"], ["customers", "Customers"], ["cases", "Cases"], ["model", "Model performance"], ["drift", "Model health"], ["sim", "Simulator"]],
  ADMIN: [["dash", "Live overview"], ["analytics", "Fraud analytics"], ["customers", "Customers"], ["cases", "Cases"], ["model", "Model performance"], ["drift", "Model health"], ["sim", "Simulator"], ["admin", "Users and audit"]],
  CUSTOMER: [["home", "My account"]] };
async function enter() {
  clearInterval(S.heroTimer); heroMap?.destroy(); heroMap = null;
  $("#auth").hidden = true; $("#app").hidden = false;
  const role = S.user.role, nav = NAV[role];
  $("#side").innerHTML = `<div class="brand"><i></i>AegisRisk</div>` + nav.map(([k, t]) => `<button class="nav" data-p="${k}">${t}${k === "cases" ? '<span class="badge" id="case-badge" hidden></span>' : ""}</button>`).join("") +
    `<div class="side-foot">${esc(S.user.full_name)}<br><span style="opacity:.7">${role.replace("_", " ").toLowerCase()}</span><br><button class="btn sm ghost" style="color:#cfd8dd;margin-top:.5rem" id="logout">Sign out</button></div>`;
  $("#side").onclick = e => { const b = e.target.closest(".nav"); if (b) go(b.dataset.p); };
  $("#logout").onclick = () => signOut();
  let h = { demo_mode: false }; try { h = await api("/api/health"); } catch (e) {}
  S.demo = role !== "CUSTOMER" && h.demo_mode;
  $("#top").innerHTML = `<div class="live"><span class="dot"></span><span id="live-text">Connected to ${esc(h.model || "model")} · ${esc(h.database || "")}</span></div>
    <div class="top-actions">${role === "CUSTOMER" ? "" : `<label class="switch"><input type="checkbox" id="sound"> Alarm sound</label>
    <label class="switch" title="Generates sample transactions so you can see the live feed"><input type="checkbox" id="demo" ${S.demo ? "checked" : ""}> Demo traffic</label>
    <button class="btn sm" id="export">Export CSV</button>`}</div>`;
  if (role !== "CUSTOMER") {
    $("#sound").onchange = e => { S.sound = e.target.checked; if (S.sound) siren(); };
    $("#demo").onchange = e => { S.demo = e.target.checked; };
    $("#export").onclick = exportCsv;
    S.timers.push(setInterval(async () => { if (S.demo && document.visibilityState === "visible" && S.page === "dash") { try { ingest(await api("/api/simulate", { method: "POST" })); } catch (e) {} } }, 3600));
  }
  go(nav[0][0]);
}
async function exportCsv() {
  try { const r = await fetch(BASE + "/api/export/transactions.csv", { headers: { Authorization: "Bearer " + S.token } });
    const b = await r.blob(), a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "aegisrisk_transactions.csv"; a.click(); }
  catch (e) { toast("Export failed", "bad"); }
}
const PAGES = { dash, analytics, customers, cases, model, drift, sim, admin, home };
function go(p) {
  const keep = S.timers.slice(0, 1 + (S.user.role === "CUSTOMER" ? -1 : 0)); // keep demo timer
  S.timers.slice(keep.length).forEach(clearInterval); S.timers = keep; S.charts.forEach(c => c.destroy()); S.charts = [];
  if (S.map) { S.map.destroy(); S.map = null; }
  S.page = p; document.querySelectorAll(".nav").forEach(b => b.classList.toggle("on", b.dataset.p === p));
  const v = $("#view"); v.style.animation = "none"; void v.offsetWidth; v.style.animation = ""; v.innerHTML = `<p class="muted">Loading…</p>`;
  PAGES[p]().catch(e => { v.innerHTML = `<div class="form-error">${esc(e.message)}</div>`; });
}

/* ================= officer: live overview ================= */
async function dash() {
  $("#view").innerHTML = `
    <div class="page-head"><div><h2>Live overview</h2><p class="muted" style="margin:.2rem 0 0">Newest payments first. Click one to see why it was scored that way.</p></div></div>
    <div class="statbar">
      <div class="stat"><b id="s-total" data-v="0">0</b><span>Payments scored</span></div>
      <div class="stat"><b id="s-fraud" data-v="0" style="color:var(--high)">0</b><span>Flagged high risk or blocked</span></div>
      <div class="stat"><b id="s-rate" data-v="0">0%</b><span>Flag rate</span></div>
      <div class="stat"><b id="s-risk" data-v="0">₹0</b><span>Value in flagged or review</span></div>
    </div>
    <div class="grid-main">
      <div class="stack">
        <div class="radar"><canvas id="map"></canvas><div class="cap">Payments by city · arcs show a jump from the customer's usual city</div>
          <div class="legend"><span><i style="background:#23805f"></i>safe</span><span><i style="background:#c98513"></i>review</span><span><i style="background:#c8283f"></i>high risk</span></div></div>
        <div class="panel"><div class="panel-h"><h3>Payment stream</h3><div class="row">
          ${["ALL", "HIGH RISK", "REVIEW"].map(f => `<button class="btn sm ${f === S.filter ? "primary" : ""}" data-f="${f}">${f === "ALL" ? "All" : label(f)}</button>`).join("")}</div></div>
          <div class="stream" id="feed"></div></div>
      </div>
      <div class="panel sticky" id="detail"><div class="empty">Select a payment to see its score, the signals behind it, and actions you can take.</div></div>
    </div>`;
  S.map = new ThreatMap($("#map"));
  $("#view").querySelectorAll("[data-f]").forEach(b => b.onclick = () => { S.filter = b.dataset.f; dash(); });
  S.feed = []; S.seen.clear();
  const rows = await api("/api/transactions?limit=40"); rows.forEach(r => S.seen.add(r.id)); S.feed = rows; S.lastSeen = rows[0]?.created_at || null;
  renderFeed(); refreshStats(); refreshBadge();
  if (rows[0] && !S.selected) selectTxn(rows[0].id);
  S.timers.push(setInterval(poll, 4000));
}
async function poll() {
  if (S.page !== "dash" || document.visibilityState !== "visible") return;
  try { const rows = await api("/api/transactions?limit=30" + (S.lastSeen ? "&since=" + encodeURIComponent(S.lastSeen) : "")); rows.reverse().forEach(ingest); } catch (e) {}
}
function ingest(t) {
  if (S.seen.has(t.id)) return; S.seen.add(t.id); S.feed.unshift(t); S.feed = S.feed.slice(0, 80);
  if (!S.lastSeen || (t.created_at || "") > S.lastSeen) S.lastSeen = t.created_at || S.lastSeen;
  if (!t.created_at) S.lastSeen = S.lastSeen;
  if (S.page !== "dash") return;
  S.map?.fire(t); renderFeed(t.id); clearTimeout(S._st); S._st = setTimeout(() => { refreshStats(); refreshBadge(); }, 400);
  if (t.status === "HIGH RISK") { toast(`High risk: ${inr(t.amount)} from ${t.customer_name} in ${t.location}`, "bad"); siren(); }
}
function renderFeed(fresh) {
  const el = $("#feed"); if (!el) return;
  const list = S.feed.filter(t => S.filter === "ALL" || t.status === S.filter || (S.filter === "HIGH RISK" && t.status === "BLOCKED"));
  el.innerHTML = list.length ? list.map(t => `<button class="txn ${cls(t.status)} ${t.id === fresh ? "fresh" : ""} ${t.id === S.selected ? "sel" : ""}" data-id="${esc(t.id)}">
    <span class="rail"></span><span><span class="t1">${esc(t.customer_name)} · ${inr(t.amount)}</span><br><span class="t2">${esc(t.merchant)} · ${esc(t.location)} · ${esc(t.time)} · ${esc(t.id)}</span></span>
    <span><span class="score num">${Math.min(99, Math.round(t.risk_score))}%</span><br>${pill(t.status)}</span></button>`).join("") : `<div class="empty">Nothing here yet. Turn on Demo traffic or use the Simulator.</div>`;
  el.onclick = e => { const b = e.target.closest(".txn"); if (b) selectTxn(b.dataset.id); };
}
async function refreshStats() {
  try { const s = await api("/api/stats"); countUp($("#s-total"), s.total_transactions); countUp($("#s-fraud"), s.fraud_detected);
    countUp($("#s-rate"), s.fraud_rate, v => v.toFixed(1) + "%"); countUp($("#s-risk"), s.amount_at_risk, v => v >= 1e7 ? "₹" + (v / 1e7).toFixed(2) + " Cr" : v >= 1e5 ? "₹" + (v / 1e5).toFixed(1) + " L" : inr(v));
    $("#live-text").textContent = `Live · ${s.model} · ${s.txn_last_minute} payment(s) in the last minute`; } catch (e) {}
}
async function refreshBadge() {
  try { const c = (await api("/api/cases")).filter(x => x.status !== "CLOSED").length, b = $("#case-badge"); if (b) { b.hidden = !c; b.textContent = c; } } catch (e) {}
}
async function selectTxn(id) {
  S.selected = id; document.querySelectorAll(".txn").forEach(b => b.classList.toggle("sel", b.dataset.id === id));
  const box = $("#detail"); if (!box) return;
  let t = S.feed.find(x => x.id === id); try { t = await api("/api/transactions/" + encodeURIComponent(id)); } catch (e) {}
  if (!t) return;
  box.innerHTML = `<div class="panel-b">
    <div class="row" style="justify-content:space-between"><h3>${inr(t.amount)} at ${esc(t.merchant)}</h3>${pill(t.status)}</div>
    <p class="muted small" style="margin:.2rem 0 .8rem">${esc(t.customer_name)} · ${esc(t.id)} · ${esc(t.action)}</p>
    ${gauge(t.risk_score, t.status)}
    ${t.rules?.length ? `<h4 style="margin-top:1rem">Rules triggered</h4><div class="chips">${t.rules.map(r => `<span class="chip">${esc(r)}</span>`).join("")}</div>` : ""}
    <h4 style="margin:1rem 0 .2rem">Why this score</h4>${factors(t.shap_factors)}
    <dl class="kv" style="margin-top:1rem"><dt>Location</dt><dd>${esc(t.location)} (usual: ${esc(t.prev_location)})</dd><dt>Device</dt><dd>${esc(t.device)}</dd>
      <dt>Time</dt><dd>${esc(t.time)}</dd><dt>Payments in 2 min</dt><dd>${t.recent_count}</dd><dt>Anomaly score</dt><dd>${t.anomaly_score}</dd><dt>Model</dt><dd>${esc(t.model_version)}</dd></dl>
    <div class="row" style="margin-top:1rem">
      <button class="btn danger sm" data-a="block">Block card</button><button class="btn sm" data-a="case">Open case</button>
      <button class="btn sm" data-a="FRAUD">Mark as fraud</button><button class="btn sm" data-a="LEGITIMATE">Mark as legitimate</button></div></div>`;
  animateIn(box);
  box.onclick = async e => { const a = e.target.closest("[data-a]")?.dataset.a; if (!a) return;
    try { if (a === "block") { await api(`/api/transactions/${id}/block`, { method: "POST" }); toast("Card blocked and case opened"); }
      else if (a === "case") { const c = await api("/api/cases", { method: "POST", body: { txn_id: id } }); toast("Case " + c.case_id + " is open"); }
      else { const r = await api("/api/feedback", { method: "POST", body: { txn_id: id, label: a } }); toast(`Saved. ${r.feedback_total} label(s) ready for the next retrain.`); }
      const i = S.feed.findIndex(x => x.id === id); if (i >= 0) { S.feed[i] = await api("/api/transactions/" + id); renderFeed(); } selectTxn(id); refreshBadge(); refreshStats();
    } catch (x) { toast(x.message, "bad"); } };
}

/* ================= officer: analytics / customers / cases ================= */
function chart(id, cfg) { const c = new Chart($(id), cfg); S.charts.push(c); return c; }
async function analytics() {
  const d = await api("/api/analytics");
  const defs = [["fraud_by_day", "By day of week"], ["fraud_by_hour", "By time of day"], ["fraud_by_location", "By city"], ["fraud_by_device", "By device"], ["fraud_by_amount", "By amount"], ["fraud_by_merchant", "By merchant"]];
  $("#view").innerHTML = `<div class="page-head"><h2>Fraud analytics</h2><p class="muted">Counts of high-risk, blocked and in-review payments, calculated from stored transactions.</p></div>
    <div class="charts">${defs.map(([k, t]) => `<div class="panel"><div class="panel-h"><h3>${t}</h3></div><div class="panel-b"><canvas id="c-${k}" height="200"></canvas></div></div>`).join("")}</div>`;
  defs.forEach(([k], i) => chart("#c-" + k, { type: "bar", data: { labels: d[k].labels, datasets: [{ data: d[k].data, backgroundColor: i % 2 ? "#0f5c63" : "#c8283f", borderRadius: 3 }] },
    options: { indexAxis: ["fraud_by_device", "fraud_by_merchant", "fraud_by_location"].includes(k) ? "y" : "x", plugins: { legend: { display: false } }, animation: { duration: reduce ? 0 : 900 }, scales: { x: { grid: { display: false } }, y: { grid: { color: "#e3e5de" }, beginAtZero: true } } } }));
}
async function customers() {
  const rows = await api("/api/customers");
  $("#view").innerHTML = `<div class="page-head"><h2>Customers</h2></div><div class="panel scroll-x"><table class="tbl"><thead><tr><th>Customer</th><th>Usual city</th><th>Usual device</th><th>Normal spend</th><th>Payments</th><th>Flagged</th><th>Card</th></tr></thead>
    <tbody>${rows.map(c => `<tr class="click" data-id="${c.customer_id}"><td><b>${esc(c.full_name)}</b><br><span class="muted small">${c.customer_id}</span></td><td>${esc(c.home_city)}</td><td>${esc(c.usual_device)}</td>
    <td>${inr(c.normal_min)} – ${inr(c.normal_max)}</td><td>${c.txn_count}</td><td>${c.flagged ? `<b style="color:var(--high)">${c.flagged}</b>` : 0}</td><td>${pill(c.card_status === "BLOCKED" ? "BLOCKED" : "SAFE").replace("Safe", "Active")}</td></tr>`).join("")}</tbody></table></div>
    <div id="cust-detail" style="margin-top:1rem"></div>`;
  $("#view").querySelector("tbody").onclick = async e => { const tr = e.target.closest("tr"); if (!tr) return; document.querySelectorAll("tr.click").forEach(r => r.classList.toggle("hl", r === tr));
    const d = await api("/api/customers/" + tr.dataset.id), c = d.customer, w = d.worst;
    $("#cust-detail").innerHTML = `<div class="cols-2"><div class="panel"><div class="panel-h"><h3>Normal behaviour</h3></div><div class="panel-b"><dl class="kv"><dt>Spending range</dt><dd>${inr(c.normal_min)} – ${inr(c.normal_max)}</dd><dt>Usual city</dt><dd>${esc(c.home_city)}</dd><dt>Usual device</dt><dd>${esc(c.usual_device)}</dd><dt>Balance</dt><dd>${inr(c.balance)}</dd></dl></div></div>
      <div class="panel"><div class="panel-h"><h3>Riskiest recent payment</h3></div><div class="panel-b">${w ? `<dl class="kv"><dt>Amount</dt><dd>${inr(w.amount)} <span class="muted">(${(w.amount / c.normal_max).toFixed(1)}× usual max)</span></dd><dt>City</dt><dd>${esc(w.location)}</dd><dt>Device</dt><dd>${esc(w.device)}</dd><dt>Score</dt><dd>${w.risk_score}% ${pill(w.status)}</dd></dl>` : "No payments yet."}</div></div></div>`;
    $("#cust-detail").scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "nearest" }); };
}
async function cases() {
  const rows = await api("/api/cases");
  $("#view").innerHTML = `<div class="page-head"><h2>Cases</h2><p class="muted">High-risk payments open a case automatically.</p></div><div class="panel scroll-x"><table class="tbl"><thead><tr><th>Case</th><th>Payment</th><th>Customer</th><th>Amount</th><th>Score</th><th>Priority</th><th>Status</th><th></th></tr></thead>
    <tbody>${rows.map(c => `<tr><td><b>${c.case_id}</b></td><td>${esc(c.txn_id)}</td><td>${esc(c.customer_name)}</td><td>${inr(c.amount)}</td><td>${Math.min(99, Math.round(c.risk_score))}%</td><td>${esc(c.priority)}</td>
    <td><select data-c="${c.case_id}" style="width:auto">${["OPEN", "INVESTIGATING", "CLOSED"].map(s => `<option ${s === c.status ? "selected" : ""} value="${s}">${label(s)}</option>`).join("")}</select></td>
    <td><button class="btn sm" data-i="${esc(c.txn_id)}">Inspect</button></td></tr>`).join("") || `<tr><td colspan="8" class="empty">No cases yet.</td></tr>`}</tbody></table></div>`;
  $("#view").onchange = async e => { const s = e.target.closest("[data-c]"); if (!s) return; try { await api("/api/cases/" + s.dataset.c, { method: "POST", body: { status: s.value } }); toast(`${s.dataset.c} is now ${label(s.value).toLowerCase()}`); refreshBadge(); } catch (x) { toast(x.message, "bad"); } };
  $("#view").onclick = e => { const b = e.target.closest("[data-i]"); if (b) { S.selected = b.dataset.i; go("dash"); } };
}

/* ================= officer: model pages ================= */
async function model() {
  const m = await api("/api/model/metrics"), cm = m.confusion, top = m.importance[0]?.importance || 1;
  $("#view").innerHTML = `<div class="page-head"><h2>Model performance</h2><p class="muted">Measured on a held-out test set of synthetic transactions. Retrain on your own labelled data before relying on these numbers.</p></div>
    <div class="panel scroll-x"><table class="tbl"><thead><tr><th>Model</th><th>Role</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>ROC-AUC</th><th>PR-AUC</th></tr></thead><tbody>
    ${m.benchmarks.map(b => `<tr class="${b.role.startsWith("Active") ? "hl" : ""}"><td><b>${esc(b.model)}</b></td><td>${esc(b.role)}</td><td>${b.accuracy}%</td><td>${b.precision}%</td><td>${b.recall}%</td><td>${b.f1}%</td><td>${b.roc_auc}%</td><td>${b.pr_auc}%</td></tr>`).join("")}</tbody></table></div>
    <div class="cols-2" style="margin-top:1rem"><div class="panel"><div class="panel-h"><h3>Confusion matrix (active model)</h3></div><div class="panel-b"><div class="cm">
      <div class="g">${cm.tn}<small>Safe, approved</small></div><div class="b">${cm.fp}<small>Safe, wrongly flagged</small></div><div class="b">${cm.fn}<small>Fraud, missed</small></div><div class="g">${cm.tp}<small>Fraud, caught</small></div></div></div></div>
      <div class="panel"><div class="panel-h"><h3>What the model relies on</h3></div><div class="panel-b">${m.importance.map(f => `<div class="factor" style="grid-template-columns:11rem 1fr 3rem"><span>${esc(f.feature)}</span><div class="mini-bar"><i data-w="${f.importance / top * 100}"></i></div><b class="num">${(f.importance * 100).toFixed(0)}%</b></div>`).join("")}</div></div></div>`;
  animateIn($("#view"));
}
async function drift() {
  const d = await api("/api/monitoring"), col = d.health === "GOOD" ? "SAFE" : d.health === "WATCH" ? "REVIEW" : "HIGH RISK";
  $("#view").innerHTML = `<div class="page-head"><div><h2>Model health</h2><p class="muted" style="margin:.2rem 0 0">Population Stability Index compares recent payments with the training data. Under 0.10 is stable, over 0.25 means retrain.</p></div><span class="pill ${cls(col)}" style="font-size:.95rem">${d.health === "GOOD" ? "Stable" : d.health === "WATCH" ? "Watch closely" : "Retrain now"}</span></div>
    <div class="cols-2"><div class="panel"><div class="panel-h"><h3>Drift by signal</h3><span class="muted small">${d.n_recent} recent payments</span></div><div class="panel-b">
      ${d.features.map(f => `<div class="factor" style="grid-template-columns:13rem 1fr 3.5rem"><span>${esc(f.feature)}</span><div class="mini-bar"><i data-w="${Math.min(100, f.psi / .3 * 100)}" style="background:${f.psi >= .25 ? "var(--high)" : f.psi >= .1 ? "var(--review)" : "var(--safe)"}"></i></div><b class="num">${f.psi.toFixed(2)}</b></div>`).join("")}</div></div>
    <div class="panel"><div class="panel-h"><h3>Retrain with analyst feedback</h3></div><div class="panel-b">
      <dl class="kv"><dt>Active model</dt><dd>${esc(d.model)}</dd><dt>Last trained</dt><dd>${esc(d.last_trained)}</dd><dt>Training rows</dt><dd>${d.training_samples.toLocaleString("en-IN")}</dd><dt>Analyst labels waiting</dt><dd>${d.feedback_labels}</dd></dl>
      <button class="btn primary" id="retrain" style="margin-top:1rem">Retrain model now</button><div class="log" id="rlog" style="margin-top:1rem"><p>Ready. Labels you give with Mark as fraud or legitimate are added to training.</p></div></div></div></div>`;
  animateIn($("#view"));
  $("#retrain").onclick = async e => { const b = e.target, log = $("#rlog"); b.disabled = true; log.innerHTML = "";
    const say = t => log.insertAdjacentHTML("beforeend", `<p>› ${t}</p>`); say("Collecting analyst feedback labels…"); say("Training Logistic Regression, Random Forest, boosted trees and Isolation Forest…");
    try { const r = await api("/api/retrain", { method: "POST" }); say(`Used ${r.feedback_used} feedback row(s).`);
      say(`PR-AUC ${r.before.pr_auc}% → ${r.after.pr_auc}% · Recall ${r.before.recall}% → ${r.after.recall}%`); say(`Deployed ${esc(r.model)}.`); toast("Model retrained and deployed"); setTimeout(drift, 1800);
    } catch (x) { say("Failed: " + esc(x.message)); b.disabled = false; } };
}

/* ================= officer: simulator ================= */
const PRESETS = { "Everyday purchase": { amount: 650, merchant: "Groceries", location: "Hyderabad", device: "Mobile Banking App", time: "06:20 PM", recent_count: 1 },
  "Card-testing burst": { amount: 2400, merchant: "Gift Cards", location: "Hyderabad", device: "Unknown Chrome Browser", time: "11:40 PM", recent_count: 5 },
  "Account takeover": { amount: 85000, merchant: "Online Electronics", location: "Kolkata", device: "Unknown Device", time: "03:31 AM", recent_count: 3 } };
async function sim() {
  const cs = await api("/api/customers"); const opt = a => a.map(x => `<option>${x}</option>`).join("");
  $("#view").innerHTML = `<div class="page-head"><h2>Simulator</h2><p class="muted">Change any field to see the score update. Inject sends it into the live feed.</p></div>
    <div class="row" style="margin-bottom:1rem">${Object.keys(PRESETS).map(k => `<button class="btn sm" data-p="${k}">${k}</button>`).join("")}</div>
    <div class="grid-main"><div class="panel"><div class="panel-b"><div class="form-grid" id="sf">
      <label>Customer<select id="f-customer_id">${cs.map(c => `<option value="${c.customer_id}">${esc(c.full_name)}</option>`).join("")}</select></label>
      <label>Amount (₹)<input id="f-amount" type="number" min="1" value="650"></label>
      <label>Merchant<select id="f-merchant">${opt(MERCH)}</select></label>
      <label>City<select id="f-location">${opt(CITIES)}</select></label>
      <label>Device<select id="f-device"><option>Mobile Banking App</option><option>iPhone 15 Pro</option><option>Samsung S24</option><option>Unknown Chrome Browser</option><option>Unknown Device</option><option>Android Emulator</option></select></label>
      <label>Time<input id="f-time" value="06:20 PM"></label><label>Payments in last 2 min<input id="f-recent_count" type="number" min="1" max="10" value="1"></label></div>
      <div class="row" style="margin-top:1rem"><button class="btn primary" id="inject">Inject into live feed</button><span class="muted small" id="sim-msg"></span></div></div></div>
    <div class="panel" id="sim-out"><div class="empty">Scoring…</div></div></div>`;
  const val = () => Object.fromEntries([...$("#sf").querySelectorAll("[id^=f-]")].map(e => [e.id.slice(2), e.value]));
  const score = async persist => { const body = { ...val(), persist }; body.amount = Number(body.amount); body.recent_count = Number(body.recent_count);
    const t = await api("/api/predict", { method: "POST", body }); return t; };
  const show = t => { const o = $("#sim-out"); o.innerHTML = `<div class="panel-b"><div class="row" style="justify-content:space-between"><h3>${esc(t.action)}</h3>${pill(t.status)}</div>${gauge(t.risk_score, t.status)}
    ${t.rules?.length ? `<div class="chips">${t.rules.map(r => `<span class="chip">${esc(r)}</span>`).join("")}</div>` : ""}<h4 style="margin:.8rem 0 .2rem">Why this score</h4>${factors(t.shap_factors)}</div>`; animateIn(o); };
  let tm; const run = () => { clearTimeout(tm); tm = setTimeout(async () => { try { show(await score(false)); } catch (x) { $("#sim-out").innerHTML = `<div class="form-error" style="margin:1rem">${esc(x.message)}</div>`; } }, 250); };
  $("#sf").addEventListener("input", run); $("#sf").addEventListener("change", run); run();
  $("#view").querySelectorAll("[data-p]").forEach(b => b.onclick = () => { const p = PRESETS[b.dataset.p]; Object.entries(p).forEach(([k, v]) => $("#f-" + k).value = v); run(); });
  $("#inject").onclick = async e => { e.target.disabled = true; try { const t = await score(true); S.seen.add(t.id); toast(`Injected ${t.id}: ${label(t.status)} (${Math.round(t.risk_score)}%)`, t.status === "HIGH RISK" ? "bad" : ""); if (t.status === "HIGH RISK") siren(); } catch (x) { toast(x.message, "bad"); } e.target.disabled = false; };
}

/* ================= admin ================= */
async function admin() {
  const d = await api("/api/admin/users");
  $("#view").innerHTML = `<div class="page-head"><h2>Users and audit</h2></div><div class="cols-2">
    <div class="panel"><div class="panel-h"><h3>Users</h3></div><div class="scroll-x"><table class="tbl"><thead><tr><th>Name</th><th>Email</th><th>Role</th></tr></thead><tbody>${d.users.map(u => `<tr><td>${esc(u.full_name)}</td><td>${esc(u.email)}</td><td>${esc(u.role.replace("_", " ").toLowerCase())}</td></tr>`).join("")}</tbody></table></div>
      <form class="panel-b form-grid" id="uform" style="border-top:1px solid var(--line)"><label>Full name<input name="full_name" required></label><label>Email<input name="email" type="email" required></label>
      <label>Role<select name="role"><option value="RISK_OFFICER">Risk officer</option><option value="CUSTOMER">Customer</option><option value="ADMIN">Admin</option></select></label><label>Password (8+ characters)<input name="password" type="password" minlength="8" required></label>
      <button class="btn primary" style="align-self:end">Create user</button></form></div>
    <div class="panel"><div class="panel-h"><h3>Audit log</h3></div><div class="stream scroll-x"><table class="tbl"><tbody>${d.audit.map(a => `<tr><td><b>${esc(a.action)}</b><br><span class="muted small">${esc(a.detail)}</span></td><td class="muted small">${esc(a.actor)}<br>${esc((a.created_at || "").replace("T", " ").slice(0, 19))}</td></tr>`).join("")}</tbody></table></div></div></div>`;
  $("#uform").onsubmit = async e => { e.preventDefault(); try { await api("/api/admin/users", { method: "POST", body: Object.fromEntries(new FormData(e.target)) }); toast("User created"); admin(); } catch (x) { toast(x.message, "bad"); } };
}

/* ================= customer ================= */
async function home() {
  const d = await api("/api/customer/me"), c = d.customer;
  $("#view").innerHTML = `<div class="page-head"><h2>Hello, ${esc(c.full_name.split(" ")[0])}</h2></div>
    <div id="alerts" class="stack" style="margin-bottom:1rem">${d.alerts.map(a => `<div class="alert-banner ${a.status === "REVIEW" ? "review" : ""}"><b>${a.status === "HIGH RISK" ? "We stopped a payment" : "We're checking a payment"}</b>
      <p style="margin:.3rem 0 .7rem">${inr(a.amount)} at ${esc(a.merchant)} from ${esc(a.location)} on ${esc(a.device)} at ${esc(a.time)}. Was this you?</p>
      <div class="row"><button class="btn primary sm" data-r="YES_IT_WAS_ME" data-id="${esc(a.id)}">Yes, it was me</button><button class="btn danger sm" data-r="BLOCK_CARD" data-id="${esc(a.id)}">No, block my card</button></div></div>`).join("")}</div>
    <div class="grid-main"><div class="stack">
      <div class="card3d"><div class="row" style="justify-content:space-between"><span>Savings account</span>${c.card_status === "BLOCKED" ? '<span class="pill BLOCKED">Card blocked</span>' : '<span class="pill SAFE">Card active</span>'}</div>
        <b id="bal" data-v="0">₹0</b><div class="row" style="justify-content:space-between"><span>•••• •••• •••• ${esc(c.card_last4)}</span><span>${esc(c.full_name)}</span></div></div>
      <div class="panel"><div class="panel-h"><h3>Recent activity</h3></div><div class="stream">${d.transactions.map(t => `<div class="txn ${cls(t.status)}" style="cursor:default"><span class="rail"></span><span><span class="t1">${esc(t.merchant)} · ${inr(t.amount)}</span><br><span class="t2">${esc(t.location)} · ${esc(t.time)}</span></span>${pill(t.status)}</div>`).join("") || '<div class="empty">No activity yet.</div>'}</div></div></div>
    <div class="panel sticky"><div class="panel-h"><h3>Make a payment</h3></div><div class="panel-b"><form id="pay" class="stack">
      <label>Amount (₹)<input name="amount" type="number" min="1" required value="500"></label><label>Merchant<select name="merchant">${MERCH.map(m => `<option>${m}</option>`).join("")}</select></label>
      <label>Where are you?<select name="location">${CITIES.map(m => `<option ${m === c.home_city ? "selected" : ""}>${m}</option>`).join("")}</select></label>
      <label>Device<select name="device"><option>This device</option><option>Unknown Device</option><option>Unknown Chrome Browser</option></select></label>
      <button class="btn primary">Pay now</button></form>
      <p class="muted small">Try ₹70,000 at Crypto Onramp from Kolkata on an unknown device.</p><div id="verdict"></div></div></div></div>`;
  countUp($("#bal"), c.balance, inr); animateIn($("#view"));
  $("#pay").onsubmit = async e => { e.preventDefault(); const b = e.target.querySelector("button"); b.disabled = true;
    try { const t = await api("/api/customer/pay", { method: "POST", body: Object.fromEntries(new FormData(e.target)) });
      const msg = t.status === "SAFE" ? "Payment approved" : t.status === "REVIEW" ? "Payment on hold while we check it" : "Payment stopped for your safety";
      $("#verdict").innerHTML = `<div class="verdict">${gauge(t.risk_score, t.status)}<div class="big" style="color:${colorOf(t.status)}">${msg}</div>${t.rules.length ? `<div class="chips" style="justify-content:center">${t.rules.map(r => `<span class="chip">${esc(r)}</span>`).join("")}</div>` : ""}</div>`;
      animateIn($("#verdict")); setTimeout(home, 3200);
    } catch (x) { toast(x.message, "bad"); } b.disabled = false; };
  $("#alerts").onclick = async e => { const b = e.target.closest("[data-r]"); if (!b) return; try { await api("/api/customer/respond", { method: "POST", body: { txn_id: b.dataset.id, action: b.dataset.r } }); toast(b.dataset.r === "BLOCK_CARD" ? "Card blocked. Our team has opened a case." : "Thanks, payment confirmed."); home(); } catch (x) { toast(x.message, "bad"); } };
}

/* ================= boot ================= */
(async function boot() {
  if (S.token) { try { S.user = await api("/api/auth/me"); return enter(); } catch (e) { sessionStorage.removeItem("aegis_token"); S.token = null; } }
  startHero();
})();
