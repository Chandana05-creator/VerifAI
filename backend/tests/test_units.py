"""Unit tests: JSON parsing, plagiarism checker, safe URL fetching, exports, metrics, rate limit, DB upgrade."""
import asyncio
import os
import sqlite3
import tempfile

import pytest

from services.json_utils import llm_text, parse_json


# ── json helpers ──
def test_parse_json_handles_fences_prose_and_garbage():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json("Sure! Here: [1, 2, 3] hope that helps") == [1, 2, 3]
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_llm_text_accepts_list_content():
    class R: content = [{"type": "text", "text": "hi"}, "!"]
    assert llm_text(R()) == "hi!"


# ── plagiarism checker ──
SENTENCES = ("The northern harbour was rebuilt after the great storm of nineteen ninety using stone from the old quarry. "
             "Fishing families moved back slowly while the council funded new boats and a modern market hall. "
             "Visitors today walk along the restored sea wall and admire the lighthouse that survived the flood. "
             "Local historians say the project became a model for coastal recovery across the whole region.")


def test_plagiarism_detects_copied_text_and_clears_original_text(monkeypatch):
    import agents.plagiarism as pg

    async def copied_page(query):
        return [{"url": "https://copy.example/page", "title": "Harbour history", "raw_content": SENTENCES, "content": SENTENCES}]

    monkeypatch.setattr(pg, "_search", copied_page)
    res = asyncio.run(pg.check_text(SENTENCES))
    assert res["similarity_percent"] >= 60 and res["risk"].lower() in ("high", "medium")
    assert res["sources"] and res["sources"][0]["url"] == "https://copy.example/page"
    assert any(s["status"] == "verbatim" for s in res["segments"])

    async def unrelated(query):
        return [{"url": "https://other.example", "title": "Cooking", "raw_content": "Boil the pasta for ten minutes then add salt and olive oil to taste." * 5}]

    monkeypatch.setattr(pg, "_search", unrelated)
    res = asyncio.run(pg.check_text(SENTENCES))
    assert res["similarity_percent"] < 15 and res["originality_percent"] > 85 and not res["sources"]


# ── safe URL fetching ──
@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://localhost:8000/", "http://192.168.1.5/", "http://10.0.0.1/",
                                 "http://169.254.169.254/latest/meta-data", "ftp://example.com/file", "file:///etc/passwd"])
def test_private_and_non_http_urls_are_blocked(url):
    from services.web_fetch import validate_public_url
    with pytest.raises(ValueError):
        asyncio.run(validate_public_url(url))


def test_public_ip_is_allowed():
    from services.web_fetch import validate_public_url
    asyncio.run(validate_public_url("http://93.184.216.34/"))


def test_extract_article_keeps_the_story_and_drops_menus_and_scripts():
    from services.web_fetch import extract_article
    html = """<html><head><title>Fallback</title><meta property="og:title" content="Harbour rebuilt"></head><body>
      <nav><a>Home</a><a>Sports</a></nav><script>var secret = 1;</script>
      <article><p>The harbour was rebuilt after the storm using stone from the old quarry nearby.</p>
      <p>Fishing families moved back slowly while the council funded new boats and a market.</p></article>
      <footer>Copyright notice that should vanish from the output text</footer></body></html>"""
    art = extract_article(html)
    assert art["title"] == "Harbour rebuilt"
    assert "rebuilt after the storm" in art["text"] and "Fishing families" in art["text"]
    assert "secret" not in art["text"] and "Sports" not in art["text"] and "Copyright" not in art["text"]


# ── exports ──
REPORT = {"executive_summary": "Nuclear power has a very low death rate — see the sources.",
          "reliability": {"score": 0.82, "label": "High reliability"},
          "summary_originality": {"verdict": "Original wording", "max_overlap_pct": 4.0},
          "key_findings": [{"finding": "Nuclear is safe ≥ coal", "confidence": 0.9}],
          "all_claims": [{"idx": 0, "text": "Nuclear causes fewer deaths than coal.", "verdict": "VERIFIED", "confidence": 0.9,
                          "critic": {"outcome": "upheld", "confidence_before": 0.9, "confidence_after": 0.95},
                          "evidence_refs": [{"n": 1, "url": "https://reuters.com/a", "verdict": "SUPPORTS", "quote": "q"}]}],
          "source_scores": [{"domain": "reuters.com", "credibility": 96, "political_lean": 0, "lean_label": "Centre"}],
          "citation_items": [{"n": 1, "title": "Reuters — energy", "domain": "reuters.com", "url": "https://reuters.com/a",
                              "apa": "reuters.com. (2026). Reuters. Retrieved from https://reuters.com/a"},
                             {"n": 2, "title": "Long", "domain": "x.example", "url": "https://x.example/" + "very-long-path-segment-" * 8, "apa": "x"}]}
PLAG = {"originality_percent": 62.0, "similarity_percent": 38.0, "risk": "medium", "passages_checked": 5, "passages_total": 6,
        "coverage_percent": 80, "word_count": 150,
        "segments": [{"text": "Copied passage text here.", "status": "verbatim", "score": 0.9, "source_n": 1}],
        "sources": [{"n": 1, "url": "https://copy.example/p", "title": "Copy", "domain": "copy.example", "passages": 2, "max_overlap": 0.9}],
        "disclaimer": "A clean result is not proof of originality."}


def test_markdown_export_contains_clickable_links():
    from services.export_service import to_markdown
    md = to_markdown("question", "Is nuclear safe?", "now", REPORT, {"total_seconds": 12, "llm_calls": 5, "tokens_in": 100, "tokens_out": 50, "searches": 4})
    assert "[Reuters — energy](https://reuters.com/a)" in md and "Critic challenge: **upheld**" in md
    assert "[1](https://reuters.com/a) (supports)" in md and "150 tokens" in md
    assert "plagiarism" in to_markdown("plagiarism", "text", "now", PLAG).lower()


def test_pdf_export_is_valid_even_with_unicode_and_very_long_urls():
    from services.export_service import to_pdf
    for kind, rep in (("question", REPORT), ("plagiarism", PLAG)):
        data = to_pdf(kind, "Is nuclear — safer ≥ coal?", "now", rep, {"total_seconds": 1})
        assert data.startswith(b"%PDF") and len(data) > 1500


# ── usage metrics ──
def test_metrics_track_a_run_and_the_langchain_callback():
    from langchain_core.outputs import ChatGeneration, LLMResult
    from langchain_core.messages import AIMessage
    from services import metrics
    metrics.start("m1")
    metrics.add_search(3)
    metrics.add_agent_time("factcheck", 1.5); metrics.add_agent_time("factcheck", 0.5)
    metrics.add_error("critic", "boom")
    msg = AIMessage(content="x", usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14})
    asyncio.run(metrics.UsageCallback().on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]])))
    m = metrics.finish("m1")
    assert m["searches"] == 3 and m["agent_seconds"]["factcheck"] == 2.0 and m["errors"][0]["agent"] == "critic"
    assert m["llm_calls"] == 1 and m["tokens_in"] == 10 and m["tokens_out"] == 4 and m["total_seconds"] >= 0


# ── rate limit ──
def test_rate_limit_blocks_the_third_request(monkeypatch):
    from fastapi import HTTPException
    from services import rate_limit as rl
    monkeypatch.setattr(rl.settings, "runs_per_minute", 2)
    rl._hits.clear()

    class Req:
        class client: host = "1.2.3.4"
    rl.rate_limit(Req()); rl.rate_limit(Req())
    with pytest.raises(HTTPException) as e:
        rl.rate_limit(Req())
    assert e.value.status_code == 429
    rl._hits.clear()


# ── database upgrade from the previous version ──
def test_old_database_is_upgraded_without_losing_data():
    from sqlalchemy.ext.asyncio import create_async_engine
    from models.db_models import Base
    from services.session_store import _upgrade_schema
    path = os.path.join(tempfile.mkdtemp(), "old.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE research_sessions (id VARCHAR PRIMARY KEY, user_id VARCHAR, query VARCHAR, mode VARCHAR, "
                "final_report JSON, claim_count INTEGER, avg_confidence FLOAT, created_at DATETIME)")
    con.execute("INSERT INTO research_sessions (id, query, mode, claim_count) VALUES ('old1', 'old question', 'deep', 3)")
    con.commit(); con.close()

    async def upgrade():
        eng = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_upgrade_schema)
        await eng.dispose()
    asyncio.run(upgrade())
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(research_sessions)")}
    assert {"input_kind", "metrics", "share_token"} <= cols
    assert con.execute("SELECT query, claim_count FROM research_sessions WHERE id='old1'").fetchone() == ("old question", 3)
    assert con.execute("SELECT name FROM sqlite_master WHERE name='feedback'").fetchone()
    con.close()
