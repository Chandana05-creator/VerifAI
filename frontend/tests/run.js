/* Runs the real pages in a simulated browser (jsdom) with a fake server and fake WebSocket.
   Usage:  cd frontend/tests && npm install && npm test */
const fs = require("fs"), path = require("path"), assert = require("assert");
const { JSDOM } = require("jsdom");
const ROOT = path.join(__dirname, "..");
const COMMON = fs.readFileSync(path.join(ROOT, "common.js"), "utf8");

let passed = 0, failed = 0;
async function test(name, fn) {
  try { await fn(); passed++; console.log("  PASS  " + name); }
  catch (e) { failed++; console.log("  FAIL  " + name + "\n        " + (e.stack || e).toString().split("\n").slice(0, 4).join("\n        ")); }
}
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));
const json = (body, status = 200, headers = {}) => ({ ok: status < 400, status, json: async () => body, headers: { get: (k) => headers[k.toLowerCase()] || null }, blob: async () => ({}) });

class MockWS {
  static last = null;
  constructor(url) { this.url = url; MockWS.last = this; this.closed = false; }
  close() { this.closed = true; if (this.onclose) this.onclose(); }
  emit(ev) { this.onmessage({ data: JSON.stringify(ev) }); }
}

/* Load a page: strips <script src> / <link>, creates the DOM, then runs common.js and the page's inline script. */
async function load(file, { search = "", routes = {}, token = null } = {}) {
  let html = fs.readFileSync(path.join(ROOT, file), "utf8");
  const inline = (html.match(/<script>([\s\S]*?)<\/script>/) || [, ""])[1];
  html = html.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<link[^>]*>/g, "");
  const dom = new JSDOM(html, { url: "http://localhost:8000/ui/" + file + search, runScripts: "dangerously", pretendToBeVisual: true });
  const w = dom.window, calls = [];
  w.fetch = async (url, opts = {}) => {
    const p = url.replace("http://localhost:8000/api/v1", ""), key = (opts.method || "GET") + " " + p.split("?")[0];
    calls.push({ key, path: p, opts });
    const h = routes[key] || routes[p.split("?")[0]];
    if (!h) return json({ detail: "no fake route for " + key }, 404);
    return h(opts, p);
  };
  w.WebSocket = MockWS; w.alert = (m) => (w.__alert = m); w.confirm = () => true; w.prompt = () => "bad source";
  w.navigator.clipboard = { writeText: async (t) => (w.__clip = t) };
  if (token) { w.localStorage.setItem("verifai_token", token); w.localStorage.setItem("verifai_user", JSON.stringify({ name: "Asha", email: "a@x.com" })); }
  const run = (code) => { const s = w.document.createElement("script"); s.textContent = code; w.document.body.append(s); };
  run(COMMON); w.goto = (u) => { w.__goto = u; }; run(inline);
  await tick();
  return { w, d: w.document, calls, run };
}

const REPORT = {
  executive_summary: "Nuclear power has a low death rate.", reliability: { score: 0.82, label: "High reliability" },
  summary_originality: { verdict: "Original wording", max_overlap_pct: 4 },
  key_findings: [{ finding: "Nuclear is among the safest sources.", confidence: 0.9, caveat: null }],
  all_claims: [
    { idx: 0, text: "Nuclear causes fewer deaths per TWh than coal.", verdict: "VERIFIED", confidence: 0.9,
      critic: { outcome: "upheld", confidence_before: 0.9, confidence_after: 0.95, query: "nuclear deaths counter evidence" },
      contradiction: null, evidence_refs: [{ n: 1, url: "https://reuters.com/a", verdict: "SUPPORTS", quote: "a quote" }, { n: 2, url: "javascript:alert(1)", verdict: "REFUTES", quote: "" }] },
    { idx: 1, text: "<img src=x onerror=alert(1)> Coal emits more CO2.", verdict: "DISPUTED", confidence: 0.5, critic: null,
      contradiction: { supporting_source: {}, refuting_source: {} }, evidence_refs: [] }],
  source_scores: [{ url: "https://reuters.com/a", domain: "reuters.com", credibility: 96, political_lean: 0, lean_label: "Centre" }, { __fleet__: {} }],
  citation_items: [{ n: 1, title: "Reuters energy", domain: "reuters.com", url: "https://reuters.com/a", apa: "reuters.com. (2026). Reuters." },
                   { n: 2, title: "Bad link", domain: "x", url: "javascript:alert(1)", apa: "x" }],
};
const PLAG = { originality_percent: 62, similarity_percent: 38, risk: "Moderate", passages_checked: 5, passages_total: 6, coverage_percent: 80, word_count: 150,
  sources: [{ n: 1, url: "https://copy.example/p", title: "Copy page", domain: "copy.example", passages: 2, max_overlap: 0.9 }],
  segments: [{ text: "Copied bit. ", status: "verbatim", score: 0.9, source_n: 1 }, { text: "Fine bit. ", status: "original", score: 0 }, { text: "Skipped. ", status: "gap" }],
  disclaimer: "A clean result is not proof." };

(async () => {
  console.log("\n== shared rendering (common.js) ==");
  await test("report: clickable evidence, citations, critic badge, feedback buttons", async () => {
    const { d, w, run } = await load("report.html", { search: "?id=x", routes: { "GET /reports/x": () => json({ id: "x", query: "Is nuclear safe?", kind: "question", created_at: "2026-10-01T10:00:00", report: REPORT, metrics: { total_seconds: 12, llm_calls: 5, tokens_in: 1000, tokens_out: 500, searches: 7 }, is_owner: true, share_token: null }) } });
    const a = [...d.querySelectorAll("#report a")].filter((x) => x.href === "https://reuters.com/a");
    assert.ok(a.length >= 3, "reuters link appears in evidence, sources and citations");
    a.forEach((x) => { assert.strictEqual(x.target, "_blank"); assert.ok(x.rel.includes("noopener")); });
    assert.ok(d.querySelector(".ref.SUPPORTS").textContent.includes("[1] supports"));
    assert.ok(d.body.textContent.includes("Critic: upheld") && d.body.textContent.includes("90% → 95%"));
    assert.strictEqual(d.querySelectorAll(".claim .fb button").length, 4, "👍👎 on both claims");
    assert.ok(d.body.textContent.includes("Completed in 12 s · 5 model calls · 1,500 tokens · 7 searches"));
  });
  await test("report: unsafe javascript: links and HTML in claim text stay inert", async () => {
    const { d } = await load("report.html", { search: "?id=x", routes: { "GET /reports/x": () => json({ id: "x", query: "q", kind: "question", created_at: "2026-10-01T10:00:00", report: REPORT, metrics: null, is_owner: true }) } });
    assert.ok(![...d.querySelectorAll("a")].some((x) => (x.getAttribute("href") || "").startsWith("javascript")), "no javascript: href");
    assert.strictEqual(d.querySelectorAll("#report img").length, 0, "no injected <img>");
    assert.ok(d.body.textContent.includes("<img src=x onerror=alert(1)>"), "shown as plain text");
  });
  await test("plagiarism report: originality, highlighted segments, source links", async () => {
    const { d } = await load("report.html", { search: "?id=p", routes: { "GET /reports/p": () => json({ id: "p", query: "text", kind: "plagiarism", created_at: "2026-10-01T10:00:00", report: PLAG, metrics: null, is_owner: true }) } });
    assert.ok(d.querySelector(".big").textContent === "62%" && d.querySelector(".badge.Moderate"));
    assert.ok(d.querySelector(".seg-verbatim") && d.querySelector(".seg-original") && d.querySelector(".seg-gap"));
    assert.strictEqual(d.querySelector("#src-1 a").href, "https://copy.example/p");
    assert.strictEqual(d.querySelector("sup a").getAttribute("href"), "#src-1");
  });
  await test("shared link page is read-only (no export / feedback / metrics)", async () => {
    const { d, calls } = await load("report.html", { search: "?share=tok123", routes: { "GET /share/tok123": () => json({ id: "x", query: "q", kind: "question", created_at: "2026-10-01T10:00:00", report: REPORT, metrics: null, is_owner: false }) } });
    assert.ok(calls.some((c) => c.key === "GET /share/tok123"));
    assert.strictEqual(d.querySelectorAll("#actions button").length, 0);
    assert.strictEqual(d.querySelectorAll(".fb").length, 0);
    assert.ok(d.body.textContent.includes("shared, read-only"));
  });
  await test("report page shows a friendly message when the report is not found", async () => {
    const { d } = await load("report.html", { search: "?id=nope", routes: { "GET /reports/nope": () => json({ detail: "x" }, 404) } });
    assert.ok(d.querySelector("#banner.show").textContent.includes("not found"));
  });

  console.log("\n== Verify page (index.html) ==");
  await test("question run: calls the API, streams events, renders report, export / share / feedback work", async () => {
    const routes = { "POST /research": () => json({ session_id: "s1", status: "started" }),
      "GET /reports/s1/export": () => json({}, 200, { "content-disposition": 'attachment; filename="r.pdf"' }),
      "POST /reports/s1/share": () => json({ token: "tk", path: "/ui/report.html?share=tk" }), "POST /feedback": () => json({ saved: true }) };
    const { d, w, calls } = await load("index.html", { routes });
    d.getElementById("q").value = "Is nuclear safe?"; d.getElementById("go").click(); await tick();
    assert.deepStrictEqual(JSON.parse(calls.find((c) => c.key === "POST /research").opts.body), { query: "Is nuclear safe?", mode: "deep" });
    const ws = MockWS.last; assert.ok(ws.url.endsWith("/api/v1/ws/research/s1"), ws.url);
    assert.ok([...d.querySelectorAll(".agent b")].map((b) => b.textContent).join() === "Research,Fact-check,Critic,Bias detector,Summarizer");
    ws.emit({ type: "agent_update", agent: "research", status: "running", message: "Searching…" }); 
    assert.ok(d.getElementById("card-research").classList.contains("running"));
    ws.emit({ type: "agent_update", agent: "research", status: "done", message: "6 sources retrieved" });
    ws.emit({ type: "agent_update", agent: "critic", status: "done", message: "Challenged 2 claims" });
    ws.emit({ type: "final_report", agent: "summarizer", status: "done", payload: REPORT });
    ws.emit({ type: "pipeline_complete", payload: { total_seconds: 20, llm_calls: 9, tokens_in: 2000, tokens_out: 700, searches: 11 } });
    assert.ok(d.getElementById("card-research").classList.contains("done") && ws.closed);
    assert.ok(!d.getElementById("result").hidden && d.querySelector("#report .summary").textContent.includes("low death rate"));
    assert.ok(d.getElementById("stats").textContent.includes("2,700 tokens"));
    const btn = (t) => [...d.querySelectorAll("#actions button, #actions a")].find((b) => b.textContent === t);
    btn("Export PDF").click(); await tick(); assert.ok(calls.some((c) => c.path === "/reports/s1/export?format=pdf"));
    btn("Share link").click(); await tick(); assert.ok(w.__clip.endsWith("/ui/report.html?share=tk"));
    d.querySelector("#actions .fb button").click(); await tick();
    assert.deepStrictEqual(JSON.parse(calls.find((c) => c.key === "POST /feedback").opts.body), { session_id: "s1", rating: 1, claim_idx: null, comment: null });
  });
  await test("link / text / image / plagiarism tabs call the right endpoints", async () => {
    const routes = { "POST /research/url": () => json({ session_id: "u1" }), "POST /research/text": () => json({ session_id: "t1" }),
      "POST /research/image": () => json({ session_id: "i1" }), "POST /plagiarism": () => json({ session_id: "p1" }) };
    const { d, w, calls } = await load("index.html", { routes });
    const go = async (tab) => { d.getElementById("tab-" + tab).click(); d.getElementById("go").disabled = false; d.getElementById("go").click(); await tick(); };
    d.getElementById("u").value = "https://news.example/a"; await go("url");
    assert.ok(calls.some((c) => c.key === "POST /research/url") && [...d.querySelectorAll(".agent b")][0].textContent === "Input");
    d.getElementById("t").value = "x".repeat(60); await go("text"); assert.ok(calls.some((c) => c.key === "POST /research/text"));
    await go("image"); assert.ok(d.getElementById("banner").textContent.includes("Choose an image"));
    d.getElementById("p").value = "word ".repeat(30); await go("plag");
    assert.ok(calls.some((c) => c.key === "POST /plagiarism") && d.getElementById("mode").style.display === "none");
    const ws = MockWS.last; assert.ok(ws.url.endsWith("/ws/research/p1"));
    ws.emit({ type: "plagiarism_report", agent: "plagiarism", payload: PLAG }); ws.emit({ type: "pipeline_complete", payload: {} });
    assert.ok(d.querySelector("#report .big").textContent === "62%");
  });
  await test("server errors and failed agents are shown to the user", async () => {
    const { d, calls } = await load("index.html", { routes: { "POST /research": () => json({ detail: "Too many requests — wait a moment." }, 429) } });
    d.getElementById("q").value = "anything"; d.getElementById("go").click(); await tick();
    assert.ok(d.getElementById("banner").textContent.includes("Too many requests") && !d.getElementById("go").disabled);
    const r2 = await load("index.html", { routes: { "POST /research": () => json({ session_id: "e1" }) } });
    r2.d.getElementById("q").value = "q"; r2.d.getElementById("go").click(); await tick();
    MockWS.last.emit({ type: "error", agent: "factcheck", message: "404 models/x is not found" });
    MockWS.last.emit({ type: "pipeline_complete", payload: {} });
    assert.ok(r2.d.getElementById("card-factcheck").classList.contains("error"));
    assert.ok(r2.d.getElementById("banner").textContent.includes("404 models/x"));
  });

  console.log("\n== login, history, analytics ==");
  await test("login stores the token and goes to the Verify page; register validates the password", async () => {
    const routes = { "POST /auth/login": () => json({ access_token: "jwt1" }), "GET /auth/me": () => json({ id: "1", email: "a@x.com", name: "Asha" }) };
    const { d, w, calls } = await load("login.html", { routes });
    d.getElementById("email").value = "a@x.com"; d.getElementById("pw").value = "secret123"; d.getElementById("submit").click(); await tick(50);
    assert.strictEqual(w.localStorage.getItem("verifai_token"), "jwt1");
    assert.strictEqual(JSON.parse(w.localStorage.getItem("verifai_user")).name, "Asha");
    assert.strictEqual(w.__goto, "index.html");
    const r = await load("login.html", { routes }); r.d.getElementById("t-reg").click(); r.d.getElementById("pw").value = "123";
    r.d.getElementById("email").value = "b@x.com"; r.d.getElementById("submit").click(); await tick();
    assert.ok(r.d.getElementById("err").textContent.includes("at least 6"));
  });
  await test("history lists past runs, opens reports, deletes entries", async () => {
    const sessions = [{ id: "a", query: "Is nuclear safe?", kind: "question", claim_count: 3, avg_confidence: 0.8, has_report: true, shared: true, created_at: "2026-10-01T10:00:00" },
                      { id: "b", query: "pasted essay…", kind: "plagiarism", claim_count: 2, avg_confidence: 0.3, has_report: true, shared: false, created_at: "2026-10-02T10:00:00" }];
    const { d, calls } = await load("history.html", { token: "jwt", routes: { "GET /history": () => json({ sessions }), "DELETE /history/a": () => json({ deleted: true }) } });
    const rows = [...d.querySelectorAll("#rows tr")].map((r) => r.textContent);
    assert.strictEqual(rows.length, 2); assert.ok(rows[0].includes("3 claims · avg 80% · shared") && rows[1].includes("70% original"));
    assert.strictEqual(d.querySelector("#rows a").getAttribute("href"), "report.html?id=a");
    d.querySelector("#rows button").click(); await tick(); assert.ok(calls.some((c) => c.key === "DELETE /history/a"));
  });
  await test("history and analytics send visitors who are not logged in to the login page", async () => {
    for (const page of ["history.html", "analytics.html"]) { const { w, calls } = await load(page, { routes: {} }); assert.strictEqual(w.__goto, "login.html", page); assert.strictEqual(calls.length, 0, "no API call without a token"); }
    const { w, calls } = await load("history.html", { token: "expired", routes: { "GET /history": () => json({ detail: "x" }, 401) } });
    assert.strictEqual(w.__goto, "login.html"); assert.strictEqual(w.localStorage.getItem("verifai_token"), null, "expired login is cleared");
  });
  await test("analytics dashboard shows KPIs, charts and feedback", async () => {
    const summary = { totals: { runs: 12, fact_checks: 9, plagiarism_checks: 3, by_input: { question: 6, url: 2, plagiarism: 3 } },
      speed: { avg_seconds: 31.5, median_seconds: 29, agent_avg_seconds: { research: 8, factcheck: 14, critic: 6 } },
      usage: { avg_model_calls: 11, avg_tokens: 14200, total_tokens: 170000, avg_searches: 9 },
      quality: { verdicts: { VERIFIED: 14, DISPUTED: 5, UNVERIFIED: 3 }, avg_claim_confidence: 0.71, critic_outcomes: { upheld: 6, downgraded: 2 }, error_rate_percent: 8.3 },
      feedback: { up: 7, down: 2, helpful_percent: 77.8, recent_comments: [{ rating: -1, comment: "wrong source", claim_idx: 0 }] },
      runs_per_day: Array.from({ length: 14 }, (_, i) => ({ date: "2026-10-" + (i + 1), runs: i % 4 })), models: { strong: "gemini-2.5-flash", fast: "gemini-2.5-flash-lite" } };
    const { d } = await load("analytics.html", { token: "jwt", routes: { "GET /analytics/summary": () => json(summary) } });
    const t = d.body.textContent;
    assert.ok(t.includes("31.5 s") && t.includes("14,200") && t.includes("77.8%") && t.includes("wrong source") && t.includes("gemini-2.5-flash-lite"));
    assert.strictEqual(d.querySelectorAll(".cols .c").length, 14);
    assert.ok(d.querySelectorAll(".bars .b").length >= 9);
  });
  await test("navigation shows the user name and log out when logged in", async () => {
    const { d, w } = await load("history.html", { token: "jwt", routes: { "GET /history": () => json({ sessions: [] }) } });
    assert.ok(d.getElementById("nav").textContent.includes("Asha") && d.getElementById("nav").textContent.includes("Log out"));
  });

  console.log("\n" + passed + " passed, " + failed + " failed");
  process.exit(failed ? 1 : 0);
})();
