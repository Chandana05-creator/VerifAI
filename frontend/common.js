/* VerifAI — shared browser code: API access, login state, navigation, report + plagiarism rendering.
   All text from the server is inserted with textContent (never innerHTML) and links are checked,
   so web content cannot inject scripts into the page. */
const SAME_ORIGIN = location.protocol.startsWith("http") && location.pathname.startsWith("/ui");
const API_BASE = SAME_ORIGIN ? location.origin : "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
const pct = (x) => Math.round((Number(x) || 0) * 100);

/* ── safe, clickable links ── */
function safeUrl(u) {
  try {
    const x = new URL(String(u), location.href);
    return x.protocol === "http:" || x.protocol === "https:" ? x.href : null;
  } catch (e) { return null; }
}
function link(url, text, cls) {
  const href = safeUrl(url);
  if (!href) return el("span", cls, text);              // e.g. javascript: links are shown as plain text
  const a = el("a", cls, text);
  a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
  return a;
}

/* ── login state ── */
const getToken = () => localStorage.getItem("verifai_token");
const getUser = () => { try { return JSON.parse(localStorage.getItem("verifai_user") || "null"); } catch (e) { return null; } };
function setLogin(token, user) { localStorage.setItem("verifai_token", token); localStorage.setItem("verifai_user", JSON.stringify(user)); }
function goto(url) { location.href = url; }
function logout() { localStorage.removeItem("verifai_token"); localStorage.removeItem("verifai_user"); goto("login.html"); }
const authHeaders = () => (getToken() ? { Authorization: "Bearer " + getToken() } : {});

async function api(path, opts = {}) {
  const headers = { ...authHeaders() };
  let body;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const res = await fetch(API_BASE + "/api/v1" + path, { method: opts.method || "GET", headers, body });
  if (!res.ok) {
    let msg = "Request failed (" + res.status + ")";
    try { const j = await res.json(); if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (e) {}
    const err = new Error(msg); err.status = res.status; throw err;
  }
  return opts.raw ? res : res.json();
}
async function downloadFile(path, fallbackName) {
  const res = await api(path, { raw: true });
  const blob = await res.blob();
  const m = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "");
  const a = el("a"); a.href = URL.createObjectURL(blob); a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a); a.click(); a.remove();
}

/* ── navigation bar ── */
function renderNav(active) {
  const nav = $("nav"); if (!nav) return;
  nav.textContent = "";
  const brand = el("a", "brand"); brand.href = "index.html";
  brand.append(el("div", "logo", "V"));
  const t = el("div"); t.append(el("b", null, "VerifAI"), el("small", null, "Research · fact-check · bias · plagiarism"));
  brand.append(t); nav.append(brand);
  const pages = [["index.html", "Verify", "verify"], ["history.html", "History", "history"], ["analytics.html", "Analytics", "analytics"]];
  pages.forEach(([href, label, key]) => { const a = el("a", "nl" + (key === active ? " active" : ""), label); a.href = href; nav.append(a); });
  const u = getUser();
  if (u) {
    nav.append(el("span", "who", u.name || u.email));
    const b = el("a", "nl", "Log out"); b.href = "#"; b.onclick = (e) => { e.preventDefault(); logout(); }; nav.append(b);
  } else { const a = el("a", "nl" + (active === "login" ? " active" : ""), "Log in / Register"); a.href = "login.html"; nav.append(a); }
}

/* ── WebSocket stream ── */
function connectStream(sessionId, onEvent, onClose) {
  const ws = new WebSocket(WS_BASE + "/api/v1/ws/research/" + sessionId);
  ws.onmessage = (m) => { let ev; try { ev = JSON.parse(m.data); } catch (e) { return; } if (ev.type !== "ping") onEvent(ev, ws); };
  ws.onclose = () => onClose && onClose();
  return ws;
}

/* ── feedback 👍 👎 ── */
function feedbackButtons(sessionId, claimIdx) {
  const box = el("span", "fb");
  [["👍", 1], ["👎", -1]].forEach(([icon, rating]) => {
    const b = el("button", null, icon); b.type = "button"; b.title = rating > 0 ? "Helpful" : "Not helpful";
    b.onclick = async () => {
      let comment = null;
      if (rating < 0) comment = prompt("What was wrong? (optional)") || null;
      try {
        await api("/feedback", { method: "POST", body: { session_id: sessionId, rating, claim_idx: claimIdx, comment } });
        box.querySelectorAll("button").forEach((x) => x.classList.remove("sent")); b.classList.add("sent");
      } catch (e) { alert(e.message); }
    };
    box.append(b);
  });
  return box;
}

/* ── fact-check report ── */
function heading(text) { return el("h2", null, text); }
function bar(value01, color) {
  const tr = el("div", "track"), f = el("div", "fill");
  f.style.width = pct(value01) + "%"; f.style.background = color; tr.append(f); return tr;
}
const verdictColor = (v) => (v === "VERIFIED" ? "var(--ok)" : v === "DISPUTED" ? "var(--warn)" : "var(--bad)");

function renderClaim(c, sessionId) {
  const d = el("div", "claim");
  d.append(el("div", "t", c.text || ""));
  const m = el("div", "meta");
  m.append(el("span", "badge " + c.verdict, c.verdict), bar(c.confidence, verdictColor(c.verdict)), el("span", "pct", pct(c.confidence) + "%"));
  if (sessionId) m.append(feedbackButtons(sessionId, c.idx));
  d.append(m);
  if (c.critic && c.critic.outcome) {
    const k = c.critic, box = el("div", "critic");
    box.append(el("span", "badge " + k.outcome, "Critic: " + k.outcome), document.createTextNode(
      "  confidence " + pct(k.confidence_before) + "% → " + pct(k.confidence_after) + "%  ·  searched for counter-evidence: “" + (k.query || "") + "”"));
    d.append(box);
  }
  if (c.contradiction) d.append(el("div", "conflict", "Sources disagree on this claim — both supporting and refuting evidence were found."));
  if ((c.evidence_refs || []).length) {
    const refs = el("div", "refs"); refs.append(el("span", null, "Evidence:"));
    c.evidence_refs.forEach((r) => {
      const a = link(r.url, "[" + r.n + "] " + (r.verdict || "").toLowerCase(), "ref " + r.verdict);
      if (r.quote) a.title = r.quote;
      refs.append(a);
    });
    d.append(refs);
  }
  return d;
}

function renderReport(root, rep, opts = {}) {
  root.textContent = "";
  const sid = opts.sessionId || null;
  if (!rep) { root.append(el("div", "empty", "No report available.")); return; }
  root.append(heading("Summary"), el("div", "summary", rep.executive_summary || "(no summary)"));
  const rel = rep.reliability || {};
  if (rel.score !== undefined) {
    const s = el("div", "score"); s.append(el("strong", null, pct(rel.score) + "%"), el("span", null, "overall reliability — " + (rel.label || "")));
    root.append(s);
  }
  if (rep.summary_originality) {
    const o = rep.summary_originality;
    root.append(el("div", "note", "Wording check: " + o.verdict + " (highest overlap with a source: " + o.max_overlap_pct + "%)"));
  }
  if ((rep.key_findings || []).length) {
    root.append(heading("Key findings"));
    rep.key_findings.forEach((k) => {
      const f = el("div", "finding"); f.append(el("div", null, k.finding || ""),
        el("div", "note", "confidence " + pct(k.confidence) + "%" + (k.caveat ? "  ·  " + k.caveat : ""))); root.append(f);
    });
  }
  if ((rep.areas_of_uncertainty || []).length) {
    root.append(heading("Areas of uncertainty"));
    rep.areas_of_uncertainty.forEach((k) => { const f = el("div", "finding"); f.append(el("b", null, k.topic || ""), el("div", "note", k.explanation || "")); root.append(f); });
  }
  root.append(heading("Claim verification"));
  (rep.all_claims || []).forEach((c) => root.append(renderClaim(c, sid)));
  if (!(rep.all_claims || []).length) root.append(el("div", "note", "No claims were verified."));

  const scored = (rep.source_scores || []).filter((s) => !s.__fleet__);
  if (scored.length) {
    root.append(heading("Sources — credibility & bias"));
    scored.forEach((s) => {
      const r = el("div", "src");
      r.append(link(s.url, s.domain || s.url, null));
      const cr = el("div"); cr.append(el("div", null, "Credibility " + Math.round(s.credibility || 0) + "/100"), bar((s.credibility || 0) / 100, "var(--accent)"));
      const ln = el("div"); const lean = el("div", "lean"), mk = el("i"); mk.style.left = Math.max(0, Math.min(100, ((Number(s.political_lean) || 0) + 100) / 2)) + "%"; lean.append(mk);
      ln.append(el("div", null, "Lean: " + (s.lean_label || "Centre")), lean);
      r.append(cr, ln); root.append(r);
    });
  }
  const cites = rep.citation_items || [];
  root.append(heading("Citations"));
  if (!cites.length) root.append(el("div", "note", "No citations."));
  cites.forEach((c) => {
    const d = el("div", "cite"); d.id = "cite-" + c.n;
    d.append(el("span", "n", "[" + c.n + "]"), link(c.url, c.title || c.url, null), el("small", null, c.apa || c.domain || ""));
    root.append(d);
  });
}

/* ── plagiarism report ── */
function renderPlagiarism(root, res) {
  root.textContent = "";
  if (!res) { root.append(el("div", "empty", "No result.")); return; }
  const g = el("div", "gauge");
  const big = el("div"); big.append(el("div", "big", res.originality_percent + "%"), el("div", "note", "original"));
  const mid = el("div"); mid.append(el("span", "badge " + res.risk, res.risk + " risk"), el("div", "note", "Similarity index " + res.similarity_percent + "%"));
  const right = el("div", "note", "Checked " + res.passages_checked + " of " + res.passages_total + " passages (" + res.coverage_percent + "% of " + res.word_count + " words)");
  g.append(big, mid, right); root.append(g);

  root.append(heading("Matching sources"));
  if (!(res.sources || []).length) root.append(el("div", "note", "No matching sources were found on the web."));
  (res.sources || []).forEach((s) => {
    const d = el("div", "cite"); d.id = "src-" + s.n;
    d.append(el("span", "n", "[" + s.n + "]"), link(s.url, s.title || s.domain, null),
      el("small", null, s.domain + " — " + s.passages + " passage(s), up to " + pct(s.max_overlap) + "% overlap")); root.append(d);
  });

  root.append(heading("Your text, highlighted"));
  const lg = el("div", "legend");
  [["seg-verbatim", "Copied (near-identical)"], ["seg-partial", "Similar wording"], ["seg-original", "Checked, original"], ["seg-gap", "Not checked"]]
    .forEach(([c, t]) => lg.append(el("span", c, t)));
  root.append(lg);
  const box = el("div", "plag-text");
  (res.segments || []).forEach((sg) => {
    const sp = el("span", "seg-" + sg.status, sg.text);
    if (sg.status === "verbatim" || sg.status === "partial") sp.title = pct(sg.score) + "% overlap";
    box.append(sp);
    if (sg.source_n) { const sup = el("sup"), a = el("a", null, "[" + sg.source_n + "]"); a.href = "#src-" + sg.source_n; sup.append(a); box.append(sup); }
  });
  root.append(box);
  if (res.disclaimer) root.append(el("div", "note", res.disclaimer));
}

/* ── small helpers used by several pages ── */
function formatMetrics(m) {
  if (!m) return "";
  const tokens = (m.tokens_in || 0) + (m.tokens_out || 0);
  return "Completed in " + (m.total_seconds || 0) + " s · " + (m.llm_calls || 0) + " model calls · " + tokens.toLocaleString() + " tokens · " + (m.searches || 0) + " searches";
}
function whenText(iso) { try { return new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleString(); } catch (e) { return iso; } }
async function shareReport(sessionId) {
  const r = await api("/reports/" + sessionId + "/share", { method: "POST" });
  const url = location.origin + r.path;
  try { await navigator.clipboard.writeText(url); } catch (e) {}
  return url;
}
