/* VerifAI extension popup. Works with the VerifAI server (default http://localhost:8000).
   Server text is inserted with textContent and links are checked, so web content cannot inject script. */
const DEFAULT_SERVER = "http://localhost:8000";
let server = DEFAULT_SERVER, running = false, errors = [], gotResult = false, ctx = { text: "", pageUrl: "" };
const $ = (id) => document.getElementById(id);
const pct = (x) => Math.round((Number(x) || 0) * 100);
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function safeUrl(u) { try { const x = new URL(String(u)); return x.protocol === "http:" || x.protocol === "https:" ? x.href : null; } catch (e) { return null; } }
function link(url, text) { const h = safeUrl(url); if (!h) return el("span", null, text); const a = el("a", null, text); a.href = h; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; }
function msg(text, info) { const m = $("msg"); m.textContent = text; m.className = "msg" + (info ? " info" : ""); m.hidden = !text; }

/* ── settings ── */
async function loadSettings() {
  const s = await chrome.storage.local.get({ server: DEFAULT_SERVER });
  server = String(s.server || DEFAULT_SERVER).replace(/\/+$/, ""); $("server").value = server;
}
async function saveSettings() {
  let v = $("server").value.trim().replace(/\/+$/, "");
  const u = safeUrl(v); if (!u) { $("settingsmsg").textContent = "Enter an address like http://localhost:8000"; return; }
  const origin = new URL(u).origin;
  if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
    const ok = await chrome.permissions.request({ origins: [origin + "/*"] });
    if (!ok) { $("settingsmsg").textContent = "Permission was not granted for " + origin; return; }
  }
  server = origin; await chrome.storage.local.set({ server }); $("server").value = server;
  $("settingsmsg").textContent = "Saved."; $("settings").hidden = true;
}

/* ── what to check ── */
async function getContext() {
  const p = new URLSearchParams(location.search);
  if (p.has("text") || p.has("pageUrl")) return { text: p.get("text") || "", pageUrl: p.get("pageUrl") || "", auto: p.get("auto") || "" };
  let text = "", pageUrl = "";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    pageUrl = (tab && tab.url) || "";
    if (tab && tab.id !== undefined) {
      const r = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => String(window.getSelection()) });
      text = (r && r[0] && r[0].result) || "";
    }
  } catch (e) { /* restricted pages (chrome://, the Web Store) cannot be read — the user can still type */ }
  return { text, pageUrl, auto: "" };
}

/* ── run + stream ── */
async function post(path, body) {
  const res = await fetch(server + "/api/v1" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) { let m = "Server answered " + res.status; try { const j = await res.json(); if (j.detail) m = typeof j.detail === "string" ? j.detail : m; } catch (e) {} throw new Error(m); }
  return res.json();
}
function steps(names) { $("steps").textContent = ""; names.forEach(([id, label]) => { const s = el("span", "step", label); s.id = "st-" + id; $("steps").append(s); }); }
function step(id, status, tip) { const s = $("st-" + id); if (s) { s.className = "step " + status; if (tip) s.title = tip; } }

async function start(kind) {
  if (running) return;
  const text = $("text").value.trim();
  let path, body, flow;
  if (kind === "page") {
    if (!safeUrl(ctx.pageUrl)) return msg("This page cannot be checked (only normal http/https pages).");
    path = "/research/url"; body = { url: ctx.pageUrl, mode: "quick" };
  } else if (kind === "plag") {
    if (text.split(/\s+/).length < 15) return msg("Paste at least about 15 words to check for plagiarism.");
    path = "/plagiarism"; body = { text };
  } else {
    if (text.length < 3) return msg("Select some text on the page, or type a claim first.");
    if (text.length >= 80) { path = "/research/text"; body = { text, mode: "quick" }; } else { path = "/research"; body = { query: text, mode: "quick" }; }
  }
  flow = kind === "plag" ? [["plagiarism", "Plagiarism check"]]
    : [[kind === "page" || path.endsWith("/text") ? "ingest" : "research", kind === "page" || path.endsWith("/text") ? "Input" : "Research"], ["factcheck", "Fact-check"], ["critic", "Critic"], ["bias_detector", "Bias"], ["summarizer", "Summary"]];
  running = true; gotResult = false; errors = []; msg(""); $("result").textContent = ""; steps(flow);
  ["verify", "page", "plag"].forEach((b) => ($(b).disabled = true));
  try {
    const r = await post(path, body);
    const ws = new WebSocket(server.replace(/^http/, "ws") + "/api/v1/ws/research/" + r.session_id);
    ws.onmessage = (m) => { let ev; try { ev = JSON.parse(m.data); } catch (e) { return; } onEvent(ev, ws, r.session_id); };
    ws.onclose = () => finish();
    ws.onerror = () => msg("Could not open the live connection to " + server);
  } catch (e) {
    msg(/fetch|Failed|NetworkError/i.test(e.message) ? "Cannot reach the VerifAI server at " + server + ". Is it running (start.bat)?" : e.message);
    finish();
  }
}
function finish() { running = false; ["verify", "page", "plag"].forEach((b) => ($(b).disabled = false)); }

function onEvent(ev, ws, sid) {
  if (ev.type === "agent_update") step(ev.agent, ev.status === "done" ? "done" : ev.status === "error" ? "error" : "running", ev.message);
  else if (ev.type === "error") { step(ev.agent, "error", ev.message); errors.push(ev.agent + ": " + ev.message); }
  else if (ev.type === "final_report") { gotResult = true; showReport(ev.payload, sid); }
  else if (ev.type === "plagiarism_report") { gotResult = true; step("plagiarism", "done"); showPlag(ev.payload, sid); }
  else if (ev.type === "pipeline_complete") {
    if (errors.length) msg("Some steps reported errors: " + errors.slice(0, 2).join(" | "));
    else if (!gotResult) msg("The run finished without a result.");
    ws.close();
  }
}

function openFull(sid) { const d = el("div", "small"); d.append(link(server + "/ui/report.html?id=" + sid, "Open the full report in VerifAI →")); return d; }

function showReport(rep, sid) {
  const root = $("result"); root.textContent = "";
  const card = el("div", "card"), rel = rep.reliability || {};
  if (rel.score !== undefined) { card.append(el("div", "big", pct(rel.score) + "%"), el("div", "small", "overall reliability — " + (rel.label || ""))); }
  card.append(el("p", null, rep.executive_summary || ""));
  root.append(card, el("h3", null, "Claims"));
  (rep.all_claims || []).forEach((c) => {
    const d = el("div", "claim"); d.append(el("div", null, c.text || ""));
    const m = el("div", "meta"), tr = el("div", "track"), f = el("div", "fill");
    f.style.width = pct(c.confidence) + "%"; f.style.background = c.verdict === "VERIFIED" ? "var(--ok)" : c.verdict === "DISPUTED" ? "var(--warn)" : "var(--bad)"; tr.append(f);
    m.append(el("span", "badge " + c.verdict, c.verdict), tr, el("span", "small", pct(c.confidence) + "%"));
    if (c.critic && c.critic.outcome) m.append(el("span", "badge " + c.critic.outcome, "critic: " + c.critic.outcome));
    d.append(m); root.append(d);
  });
  const cites = rep.citation_items || [];
  if (cites.length) { root.append(el("h3", null, "Sources")); cites.slice(0, 12).forEach((c) => { const d = el("div", "cite"); d.append(el("span", "small", "[" + c.n + "] "), link(c.url, c.title || c.url)); root.append(d); }); }
  root.append(openFull(sid));
}

function showPlag(res, sid) {
  const root = $("result"); root.textContent = "";
  const card = el("div", "card");
  card.append(el("div", "big", res.originality_percent + "% original"), el("span", "badge " + res.risk, res.risk + " risk"),
    el("div", "small", "Checked " + res.passages_checked + " of " + res.passages_total + " passages"));
  root.append(card, el("h3", null, "Matching sources"));
  if (!(res.sources || []).length) root.append(el("div", "small", "No matching sources found."));
  (res.sources || []).forEach((s) => { const d = el("div", "cite"); d.append(el("span", "small", "[" + s.n + "] "), link(s.url, s.title || s.domain), el("span", "small", " — up to " + pct(s.max_overlap) + "% overlap")); root.append(d); });
  root.append(openFull(sid));
}

/* ── start-up ── */
(async function init() {
  await loadSettings();
  $("gear").onclick = () => { $("settings").hidden = !$("settings").hidden; };
  $("save").onclick = saveSettings;
  $("verify").onclick = () => start("text"); $("page").onclick = () => start("page"); $("plag").onclick = () => start("plag");
  ctx = await getContext(); $("text").value = ctx.text;
  if (ctx.auto === "text" && ctx.text) start("text"); else if (ctx.auto === "page") start("page");
})();
