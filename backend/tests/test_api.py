"""HTTP API tests (the pipeline runs for real, with fake models and fake search)."""
import itertools

import pytest

_n = itertools.count(1)
LONG = ("The northern harbour was rebuilt after the great storm using stone from the old quarry, and the council "
        "funded new boats and a modern market hall so that fishing families could return to the town.")


def login(client, name="User"):
    email = f"user{next(_n)}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "secret123", "name": name})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def run_question(client, headers=None, query="Is nuclear energy safer than coal?"):
    r = client.post("/api/v1/research", json={"query": query, "mode": "quick"}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_run_is_saved_with_report_citations_and_metrics(client, kit, no_ws_wait):
    sid = run_question(client)
    body = client.get(f"/api/v1/reports/{sid}").json()
    rep = body["report"]
    assert body["kind"] == "question" and body["is_owner"] and rep["claim_count"] == 2
    assert rep["citation_items"] and all(i["url"].startswith("http") for i in rep["citation_items"])
    m = body["metrics"]
    assert m["total_seconds"] >= 0 and {"research", "factcheck", "bias_detector", "summarizer"} <= set(m["agent_seconds"])
    assert m["searches"] > 0 and m["models"]["strong"]


def test_logged_in_runs_are_private_to_their_owner_and_listed_in_history(client, kit, no_ws_wait):
    alice, bob = login(client, "Alice"), login(client, "Bob")
    sid = run_question(client, alice)
    assert client.get(f"/api/v1/reports/{sid}", headers=alice).status_code == 200
    assert client.get(f"/api/v1/reports/{sid}", headers=bob).status_code == 404
    assert client.get(f"/api/v1/reports/{sid}").status_code == 404
    hist = client.get("/api/v1/history", headers=alice).json()["sessions"]
    assert [h["id"] for h in hist] == [sid] and hist[0]["kind"] == "question" and hist[0]["has_report"]
    assert client.get("/api/v1/history", headers=bob).json()["sessions"] == []
    assert client.delete(f"/api/v1/history/{sid}", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/history/{sid}", headers=alice).json()["deleted"]
    assert client.get(f"/api/v1/reports/{sid}", headers=alice).status_code == 404


def test_export_markdown_and_pdf(client, kit, no_ws_wait):
    sid = run_question(client)
    md = client.get(f"/api/v1/reports/{sid}/export?format=md")
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    assert "# VerifAI report" in md.text and "](https://reuters.com/a)" in md.text
    pdf = client.get(f"/api/v1/reports/{sid}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"/api/v1/reports/{sid}/export?format=docx").status_code == 422


def test_share_link_lifecycle(client, kit, no_ws_wait):
    owner, other = login(client), login(client)
    sid = run_question(client, owner)
    assert client.post(f"/api/v1/reports/{sid}/share", headers=other).status_code == 404
    token = client.post(f"/api/v1/reports/{sid}/share", headers=owner).json()["token"]
    pub = client.get(f"/api/v1/share/{token}")                         # no login needed
    assert pub.status_code == 200 and pub.json()["is_owner"] is False and pub.json()["metrics"] is None
    assert pub.json()["report"]["claim_count"] == 2
    assert client.get(f"/api/v1/reports/{sid}", headers=owner).json()["share_token"] == token
    assert client.delete(f"/api/v1/reports/{sid}/share", headers=owner).json()["revoked"]
    assert client.get(f"/api/v1/share/{token}").status_code == 404


def test_feedback_is_validated_and_stored(client, kit, no_ws_wait):
    sid = run_question(client)
    assert client.post("/api/v1/feedback", json={"session_id": sid, "rating": 1}).json()["saved"]
    assert client.post("/api/v1/feedback", json={"session_id": sid, "rating": -1, "claim_idx": 0, "comment": "wrong source"}).status_code == 200
    assert client.post("/api/v1/feedback", json={"session_id": sid, "rating": 5}).status_code == 422
    assert client.post("/api/v1/feedback", json={"session_id": "nope", "rating": 1}).status_code == 404


def test_analytics_needs_login_and_summarises_runs_and_feedback(client, kit, no_ws_wait):
    kit.critic = "refute"
    sid = run_question(client)
    client.post("/api/v1/feedback", json={"session_id": sid, "rating": 1, "comment": "useful"})
    assert client.get("/api/v1/analytics/summary").status_code == 401
    a = client.get("/api/v1/analytics/summary", headers=login(client)).json()
    assert a["totals"]["fact_checks"] >= 1 and a["totals"]["by_input"]["question"] >= 1
    assert a["speed"]["avg_seconds"] >= 0 and "factcheck" in a["speed"]["agent_avg_seconds"]
    assert a["quality"]["verdicts"].get("VERIFIED", 0) + a["quality"]["verdicts"].get("DISPUTED", 0) >= 2
    assert a["feedback"]["up"] >= 1 and a["feedback"]["helpful_percent"] is not None
    assert any(c["comment"] == "useful" for c in a["feedback"]["recent_comments"])
    assert len(a["runs_per_day"]) == 14 and a["models"]["strong"]


def test_input_validation(client, monkeypatch):
    assert client.post("/api/v1/research", json={"query": "x"}).status_code == 422
    assert client.post("/api/v1/research/url", json={"url": "ftp://example.com/a"}).status_code == 422
    assert client.post("/api/v1/research/text", json={"text": "too short"}).status_code == 422
    assert client.post("/api/v1/plagiarism", json={"text": "only a few words"}).status_code == 422
    bad = client.post("/api/v1/research/image", files={"file": ("a.txt", b"hello", "text/plain")})
    assert bad.status_code == 415
    assert client.post("/api/v1/research/image", files={"file": ("a.png", b"", "image/png")}).status_code == 422
    monkeypatch.setattr("routers.research.settings.max_upload_mb", 0)
    assert client.post("/api/v1/research/image", files={"file": ("a.png", b"x", "image/png")}).status_code == 413


def test_image_link_and_text_runs(client, kit, no_ws_wait, monkeypatch):
    async def fake_fetch(url):
        return {"title": "Council news", "text": LONG * 2, "url": "https://news.example/story"}
    monkeypatch.setattr("agents.ingest.fetch_article", fake_fetch)

    r = client.post("/api/v1/research/image", files={"file": ("viral.png", b"\x89PNG....", "image/png")}, data={"mode": "quick"})
    assert r.status_code == 200
    rep = client.get(f"/api/v1/reports/{r.json()['session_id']}").json()
    assert rep["kind"] == "image" and rep["report"]["input_kind"] == "image" and rep["report"]["claim_count"] == 2

    r = client.post("/api/v1/research/url", json={"url": "https://news.example/story", "mode": "quick"})
    rep = client.get(f"/api/v1/reports/{r.json()['session_id']}").json()
    assert rep["kind"] == "url" and "https://news.example/story" in [i["url"] for i in rep["report"]["citation_items"]]

    r = client.post("/api/v1/research/text", json={"text": LONG, "mode": "quick"})
    rep = client.get(f"/api/v1/reports/{r.json()['session_id']}").json()
    assert rep["kind"] == "text" and rep["report"]["claim_count"] == 2


def test_plagiarism_check_endpoint_and_export(client, no_ws_wait, monkeypatch):
    import agents.plagiarism as pg

    async def copied(query):
        return [{"url": "https://copy.example/page", "title": "Copy", "raw_content": LONG, "content": LONG}]
    monkeypatch.setattr(pg, "_search", copied)
    r = client.post("/api/v1/plagiarism", json={"text": LONG})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    body = client.get(f"/api/v1/reports/{sid}").json()
    assert body["kind"] == "plagiarism" and body["report"]["similarity_percent"] >= 60
    assert body["report"]["sources"][0]["url"] == "https://copy.example/page"
    assert "plagiarism check" in client.get(f"/api/v1/reports/{sid}/export?format=md").text.lower()
    assert client.get(f"/api/v1/reports/{sid}/export?format=pdf").content.startswith(b"%PDF")


def test_runs_are_rate_limited(client, kit, no_ws_wait, monkeypatch):
    from services import rate_limit as rl
    monkeypatch.setattr(rl.settings, "runs_per_minute", 2)
    rl._hits.clear()
    codes = [client.post("/api/v1/research", json={"query": "Is the sky blue?", "mode": "quick"}).status_code for _ in range(3)]
    rl._hits.clear()
    assert codes == [200, 200, 429]


def test_all_web_pages_and_assets_are_served(client):
    for page in ("index.html", "login.html", "history.html", "report.html", "analytics.html", "common.js", "app.css"):
        r = client.get(f"/ui/{page}")
        assert r.status_code == 200 and len(r.text) > 200, page
    assert "/api/v1/ws/research/" in client.get("/ui/common.js").text
    assert client.get("/", follow_redirects=True).status_code == 200
