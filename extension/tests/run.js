/* Runs the extension popup in a simulated browser with fake chrome APIs, a fake server and a fake WebSocket.
   Usage:  cd extension/tests && npm install && npm test */
const fs = require("fs"), path = require("path"), assert = require("assert");
const { JSDOM } = require("jsdom");
const ROOT = path.join(__dirname, "..");
let passed = 0, failed = 0;
async function test(name, fn) { try { await fn(); passed++; console.log("  PASS  " + name); } catch (e) { failed++; console.log("  FAIL  " + name + "\n        " + (e.stack || e).toString().split("\n").slice(0, 4).join("\n        ")); } }
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));
const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
class MockWS { static last = null; constructor(u) { this.url = u; MockWS.last = this; this.closed = false; } close() { this.closed = true; if (this.onclose) this.onclose(); } emit(ev) { this.onmessage({ data: JSON.stringify(ev) }); } }

async function load({ search = "", routes = {}, store = {}, selection = "", tabUrl = "https://news.example/story", permission = true } = {}) {
  let html = fs.readFileSync(path.join(ROOT, "popup.html"), "utf8");
  const code = fs.readFileSync(path.join(ROOT, "popup.js"), "utf8");
  html = html.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<link[^>]*>/g, "");
  const dom = new JSDOM(html, { url: "chrome-extension://abc/popup.html" + search, runScripts: "dangerously", pretendToBeVisual: true });
  const w = dom.window, calls = [], saved = { ...store };
  w.chrome = {
    storage: { local: { get: async (d) => ({ ...d, ...saved }), set: async (o) => Object.assign(saved, o) } },
    tabs: { query: async () => [{ id: 7, url: tabUrl }] },
    scripting: { executeScript: async () => [{ result: selection }] },
    permissions: { request: async (p) => { w.__perm = p; return permission; } },
  };
  w.fetch = async (url, opts = {}) => { const p = url.replace(/^https?:\/\/[^/]+\/api\/v1/, ""); calls.push({ path: p, body: opts.body ? JSON.parse(opts.body) : null, url }); const h = routes[p]; return h ? h() : json({ detail: "no route " + p }, 404); };
  w.WebSocket = MockWS;
  const s = w.document.createElement("script"); s.textContent = code; w.document.body.append(s);
  await tick(); return { w, d: w.document, calls, saved };
}
const REPORT = { executive_summary: "Nuclear power has a low death rate.", reliability: { score: 0.8, label: "High reliability" },
  all_claims: [{ idx: 0, text: "Nuclear causes fewer deaths than coal.", verdict: "VERIFIED", confidence: 0.9, critic: { outcome: "upheld" } }],
  citation_items: [{ n: 1, title: "Reuters", url: "https://reuters.com/a" }, { n: 2, title: "Bad", url: "javascript:alert(1)" }] };

(async () => {
  console.log("\n== VerifAI extension popup ==");
  await test("reads the selected text from the active tab and verifies a short claim as a question", async () => {
    const { d, calls } = await load({ selection: "Coal kills more people than nuclear", routes: { "/research": () => json({ session_id: "s1" }) } });
    assert.strictEqual(d.getElementById("text").value, "Coal kills more people than nuclear");
    d.getElementById("verify").click(); await tick();
    assert.deepStrictEqual(calls[0].body, { query: "Coal kills more people than nuclear", mode: "quick" });
    const ws = MockWS.last; assert.ok(ws.url === "ws://localhost:8000/api/v1/ws/research/s1", ws.url);
    ws.emit({ type: "agent_update", agent: "research", status: "running", message: "…" }); assert.ok(d.getElementById("st-research").classList.contains("running"));
    ws.emit({ type: "agent_update", agent: "factcheck", status: "done", message: "2 claims" });
    ws.emit({ type: "final_report", payload: REPORT }); ws.emit({ type: "pipeline_complete", payload: {} });
    assert.ok(d.getElementById("st-factcheck").classList.contains("done") && ws.closed && !d.getElementById("verify").disabled);
    const t = d.getElementById("result").textContent;
    assert.ok(t.includes("80%") && t.includes("Nuclear causes fewer deaths") && t.includes("critic: upheld"));
    const links = [...d.querySelectorAll("#result a")].map((a) => a.href);
    assert.ok(links.includes("https://reuters.com/a") && links.includes("http://localhost:8000/ui/report.html?id=s1"));
    assert.ok(![...d.querySelectorAll("a")].some((a) => (a.getAttribute("href") || "").startsWith("javascript")), "unsafe link not clickable");
    assert.ok([...d.querySelectorAll("#result a")].every((a) => a.target === "_blank" && a.rel.includes("noopener")));
  });
  await test("long selections are sent as text; 'Verify this page' sends the tab URL", async () => {
    const long = "The city council announced that nuclear power is safer than coal. ".repeat(3);
    const { d, calls } = await load({ selection: long, routes: { "/research/text": () => json({ session_id: "t1" }), "/research/url": () => json({ session_id: "u1" }) } });
    d.getElementById("verify").click(); await tick();
    assert.strictEqual(calls[0].path, "/research/text"); assert.strictEqual(calls[0].body.text, long.trim());
    MockWS.last.emit({ type: "pipeline_complete", payload: {} });
    d.getElementById("page").click(); await tick();
    assert.deepStrictEqual(calls[1].body, { url: "https://news.example/story", mode: "quick" });
    assert.strictEqual(d.querySelector("#steps .step").textContent, "Input");
  });
  await test("opened from the right-click menu it starts automatically", async () => {
    const { calls } = await load({ search: "?text=" + encodeURIComponent("Vaccines cause autism") + "&auto=text&pageUrl=" + encodeURIComponent("https://x.example/"), routes: { "/research": () => json({ session_id: "a1" }) } });
    assert.strictEqual(calls.length, 1); assert.strictEqual(calls[0].body.query, "Vaccines cause autism");
    const p = await load({ search: "?auto=page&pageUrl=" + encodeURIComponent("https://x.example/news"), routes: { "/research/url": () => json({ session_id: "p1" }) } });
    assert.deepStrictEqual(p.calls[0].body, { url: "https://x.example/news", mode: "quick" });
  });
  await test("plagiarism button shows originality and clickable matching sources", async () => {
    const { d, calls } = await load({ selection: "word ".repeat(30), routes: { "/plagiarism": () => json({ session_id: "g1" }) } });
    d.getElementById("plag").click(); await tick();
    MockWS.last.emit({ type: "plagiarism_report", payload: { originality_percent: 55, risk: "Moderate", passages_checked: 4, passages_total: 5, sources: [{ n: 1, url: "https://copy.example/p", title: "Copy", domain: "copy.example", max_overlap: 0.9 }] } });
    MockWS.last.emit({ type: "pipeline_complete", payload: {} });
    const t = d.getElementById("result").textContent;
    assert.ok(t.includes("55% original") && t.includes("Moderate risk") && [...d.querySelectorAll("#result a")].some((a) => a.href === "https://copy.example/p"));
  });
  await test("friendly messages: server down, too little text, errors from agents", async () => {
    const down = await load({ selection: "A short claim to check", routes: { "/research": () => { throw new TypeError("Failed to fetch"); } } });
    down.d.getElementById("verify").click(); await tick();
    assert.ok(down.d.getElementById("msg").textContent.includes("Cannot reach the VerifAI server at http://localhost:8000"));
    assert.ok(!down.d.getElementById("verify").disabled);
    const empty = await load({ selection: "" }); empty.d.getElementById("verify").click(); await tick();
    assert.ok(empty.d.getElementById("msg").textContent.includes("Select some text") && empty.calls.length === 0);
    const err = await load({ selection: "Some claim to verify here", routes: { "/research": () => json({ session_id: "e1" }) } });
    err.d.getElementById("verify").click(); await tick();
    MockWS.last.emit({ type: "error", agent: "factcheck", message: "404 models/x not found" }); MockWS.last.emit({ type: "pipeline_complete", payload: {} });
    assert.ok(err.d.getElementById("st-factcheck").classList.contains("error") && err.d.getElementById("msg").textContent.includes("404 models/x"));
    const restricted = await load({ selection: "", tabUrl: "chrome://extensions" }); restricted.d.getElementById("page").click(); await tick();
    assert.ok(restricted.d.getElementById("msg").textContent.includes("cannot be checked"));
  });
  await test("server setting: saved, localhost needs no permission, other servers ask Chrome for it", async () => {
    const { d, saved } = await load({ store: { server: "http://127.0.0.1:8000/" } });
    assert.strictEqual(d.getElementById("server").value, "http://127.0.0.1:8000");
    d.getElementById("server").value = "http://localhost:9000"; d.getElementById("save").click(); await tick();
    assert.strictEqual(saved.server, "http://localhost:9000");
    const r = await load({ permission: true }); r.d.getElementById("server").value = "https://verifai.example.com/"; r.d.getElementById("save").click(); await tick();
    assert.strictEqual(JSON.stringify(r.w.__perm), '{"origins":["https://verifai.example.com/*"]}'); assert.strictEqual(r.saved.server, "https://verifai.example.com");
    const denied = await load({ permission: false }); denied.d.getElementById("server").value = "https://other.example.com"; denied.d.getElementById("save").click(); await tick();
    assert.ok(denied.d.getElementById("settingsmsg").textContent.includes("not granted") && !denied.saved.server);
  });
  await test("manifest is valid MV3 and every referenced file exists", async () => {
    const m = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"));
    assert.strictEqual(m.manifest_version, 3);
    [m.background.service_worker, m.action.default_popup, ...Object.values(m.icons)].forEach((f) => assert.ok(fs.existsSync(path.join(ROOT, f)), f + " missing"));
    ["contextMenus", "storage", "activeTab", "scripting"].forEach((p) => assert.ok(m.permissions.includes(p), p));
    const html = fs.readFileSync(path.join(ROOT, "popup.html"), "utf8");
    assert.ok(!/<script>[\s\S]*?\S[\s\S]*?<\/script>/.test(html), "no inline script (blocked by MV3 CSP)");
    const bg = fs.readFileSync(path.join(ROOT, "background.js"), "utf8");
    assert.ok(bg.includes("contextMenus.create") && bg.includes("windows.create"));
  });
  console.log("\n" + passed + " passed, " + failed + " failed"); process.exit(failed ? 1 : 0);
})();
