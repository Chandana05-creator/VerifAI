"""Pipeline behaviour: question / link / text / image inputs, the Critic, loops, citations."""
import asyncio

import pytest

from agents import pipeline as pl
from agents.state import make_initial_state
from services import inputs


def run(query="Is nuclear safer than coal?", mode="deep", kind="question", value="", sid="t-sid"):
    state = make_initial_state(query, mode, sid, input_kind=kind, input_value=value)
    return asyncio.run(pl.pipeline.ainvoke(state, config={"recursion_limit": 50}))


def agents_with_events(out, etype="agent_update"):
    return [(e["agent"], e["status"]) for e in out["events"] if e["type"] == etype]


LONG_TEXT = ("The city council announced on Monday that nuclear power causes fewer deaths per unit of energy "
             "than coal, and that coal emits more carbon dioxide per kilowatt hour than any other source.")


def test_question_flow_with_critic_and_clickable_citations(kit):
    out = run()
    assert len(out["claims"]) == 2
    assert all(c["verdict"] == "VERIFIED" and c["confidence"] == 1.0 for c in out["claims"])
    assert kit.calls["expand"] == 1 and out["loop_count"] == 0           # no re-search when confidence is high
    assert kit.calls["challenge"] == 2                                   # the Critic challenged both claims
    assert [c["critic"]["outcome"] for c in out["claims"]] == ["upheld", "upheld"]
    rep = out["final_report"]
    items = rep["citation_items"]
    assert items and all(i["url"].startswith("http") and i["n"] and i["title"] for i in items)
    assert {i["url"] for i in items} >= {"https://reuters.com/a", "https://counter.example/x"}   # evidence + critic pages
    refs = rep["all_claims"][0]["evidence_refs"]
    assert refs and all({"n", "url", "verdict", "quote"} <= set(r) for r in refs)
    assert len({i["n"] for i in items}) == len(items)                    # numbering is unique
    assert rep["reliability"]["score"] > 0 and rep["summary_originality"]["verdict"] == "Original wording"
    ags = agents_with_events(out)
    assert ags.count(("critic", "done")) == 1 and ags.index(("critic", "done")) < ags.index(("bias_detector", "done"))


def test_critic_downgrades_a_claim_when_counter_evidence_is_found(kit):
    kit.critic = "refute"
    out = run()
    c = out["claims"][0]
    assert c["critic"]["outcome"] == "downgraded"
    assert c["critic"]["verdict_before"] == "VERIFIED" and c["verdict"] == "DISPUTED"
    assert c["confidence"] < c["critic"]["confidence_before"]
    assert c["contradiction"] is not None                                 # both supporting and refuting evidence now
    assert out["avg_confidence"] < 1.0


def test_quick_mode_skips_the_critic(kit):
    out = run(mode="quick")
    assert kit.calls["challenge"] == 0
    assert all(c["critic"] is None for c in out["claims"])
    assert any(e["agent"] == "critic" and "Skipped" in e["message"] for e in out["events"])


def test_re_search_loop_runs_twice_for_questions_with_low_confidence(kit):
    kit.verdict = "refute"
    out = run(mode="quick")
    assert kit.calls["expand"] == 3 and out["loop_count"] == 3
    assert out["final_report"] is not None
    assert len({c["url"] for c in out["final_report"]["citation_items"]}) == len(out["final_report"]["citation_items"])


def test_text_input_is_fact_checked_without_a_web_search_loop(kit):
    kit.verdict = "refute"                                # low confidence would loop for a question, not for text
    out = run(query=LONG_TEXT[:80], kind="text", value=LONG_TEXT, mode="quick")
    assert kit.calls["expand"] == 0 and out["loop_count"] == 1            # research never ran, no re-search
    assert out["claims"] and out["final_report"]["input_kind"] == "text"
    assert any(e["agent"] == "ingest" and e["status"] == "done" for e in out["events"])
    assert out["source_scores"] == []                                     # no URL, nothing to rate


def test_link_input_reads_the_page_and_rates_its_publisher(kit, monkeypatch):
    async def fake_fetch(url):
        return {"title": "Council news", "text": LONG_TEXT * 2, "url": "https://news.example/story"}
    monkeypatch.setattr("agents.ingest.fetch_article", fake_fetch)
    out = run(query="https://news.example/story", kind="url", value="https://news.example/story", mode="quick")
    assert out["sources"][0]["url"] == "https://news.example/story"
    domains = [s["domain"] for s in out["source_scores"] if "__fleet__" not in s]
    assert "news.example" in domains
    assert "https://news.example/story" in [i["url"] for i in out["final_report"]["citation_items"]]


def test_image_input_is_transcribed_then_checked(kit):
    inputs.put("img-sid", {"data": b"\x89PNG fake", "mime": "image/png", "filename": "post.png"})
    out = run(query="Image: post.png", kind="image", sid="img-sid", mode="quick")
    assert kit.calls["image"] == 1 and out["claims"]
    assert any(e["agent"] == "ingest" and e["status"] == "done" for e in out["events"])


def test_ingest_failure_is_reported_and_a_fallback_report_is_produced(kit, monkeypatch):
    async def bad_fetch(url):
        raise ValueError("The website answered with an error (404).")
    monkeypatch.setattr("agents.ingest.fetch_article", bad_fetch)
    out = run(query="https://x.example/404", kind="url", value="https://x.example/404", mode="quick")
    assert any(e["type"] == "error" and e["agent"] == "ingest" and "404" in e["message"] for e in out["events"])
    assert "could not verify" in out["final_report"]["executive_summary"]
    assert kit.calls["extract"] == 0


def test_missing_image_is_reported(kit):
    out = run(query="Image: gone.png", kind="image", sid="nothing-stored", mode="quick")
    assert any(e["type"] == "error" and e["agent"] == "ingest" for e in out["events"])


def test_summary_that_copies_a_source_is_flagged():
    from agents.summarizer import _summary_originality
    src = "The reactor was shut down on Tuesday after engineers detected a small leak in the cooling system."
    copied = _summary_originality("The reactor was shut down on Tuesday after engineers detected a small leak in the cooling system.", src)
    fresh = _summary_originality("Operators paused the plant because a coolant fault had been spotted by the staff.", src)
    assert copied["verdict"] == "Contains copied sentences" and copied["copied_sentences"] == 1
    assert fresh["verdict"] == "Original wording"
