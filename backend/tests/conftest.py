"""Shared test setup. Nothing here calls Gemini, Tavily or downloads models:
the language model, web search and vector store are replaced by small fakes."""
import json
import os
import re
import sys
import tempfile
import types
from pathlib import Path

BACKEND = str(Path(__file__).resolve().parents[1])
_DB = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update(GEMINI_API_KEY="test-key", TAVILY_API_KEY="test-key", DATABASE_URL=f"sqlite+aiosqlite:///{_DB}",
                  RUNS_PER_MINUTE="1000", JWT_SECRET="test-secret")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# vector store stub (the real one needs ~250 MB of model downloads)
_vs = types.ModuleType("services.vector_store")


async def _init(): pass
async def _retrieve(q, top_k=6, candidate_k=20): return []
async def _ingest(r): return {}
_vs.init_chroma, _vs.retrieve, _vs.ingest_tavily_results = _init, _retrieve, _ingest
sys.modules["services.vector_store"] = _vs

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


class Kit:
    """Controls what the fake model and fake search return."""
    def __init__(self):
        self.verdict = "support"       # support | refute | mixed | cross  (evidence for the claims)
        self.critic = "support"        # support | refute               (counter-evidence found by the Critic)
        self.calls = {"expand": 0, "extract": 0, "verify": 0, "challenge": 0, "bias": 0, "summ": 0, "image": 0}
        self.searches = []


class FakeTavily:
    def __init__(self, kit): self.kit = kit
    async def ainvoke(self, q):
        self.kit.searches.append(q)
        if q.startswith("fact check:") or "devil" not in q and "counter" not in q:
            return [{"url": "https://reuters.com/a", "title": "Reuters", "content": "c1 " * 30},
                    {"url": "https://www.nature.com/b", "title": "Nature", "content": "c2 " * 30},
                    {"url": "https://someblog.example/c", "title": "Blog", "content": "c3 " * 30}]
        return [{"url": "https://counter.example/x", "title": "Counter A", "content": "k1 " * 30},
                {"url": "https://counter2.example/y", "title": "Counter B", "content": "k2 " * 30}]


def _fake_llm(kit):
    def fake(pv):
        if isinstance(pv, list):                       # image transcription call
            kit.calls["image"] += 1
            return AIMessage(content="Breaking: the moon is made of cheese, say officials in a viral post today.")
        text = pv.to_string()
        if "search query optimizer" in text:
            kit.calls["expand"] += 1
            return AIMessage(content='```json\n["nuclear safety statistics", "deaths per TWh", "coal vs nuclear risk"]\n```')
        if "Extract the individual" in text:
            kit.calls["extract"] += 1
            return AIMessage(content=[{"type": "text", "text": 'Sure:\n[{"idx":0,"text":"Nuclear causes fewer deaths per TWh than coal.","source_passage":"p"},{"idx":1,"text":"Coal emits more CO2 per kWh.","source_passage":"p"}]'}])
        if "devil's advocate" in text:
            kit.calls["challenge"] += 1
            return AIMessage(content='{"query": "counter evidence devil check"}')
        if "natural language inference" in text:
            kit.calls["verify"] += 1
            urls = re.findall(r"URL: (\S+)", text)
            claim = re.search(r"CLAIM: (.*)", text).group(1)
            cls = []
            for i, u in enumerate(urls):
                if "counter" in u:
                    v = "REFUTES" if kit.critic == "refute" else "SUPPORTS"
                elif kit.verdict == "cross":
                    v = "SUPPORTS" if "Nuclear" in claim else "REFUTES"
                elif kit.verdict == "support":
                    v = "SUPPORTS"
                elif kit.verdict == "refute":
                    v = "REFUTES"
                else:
                    v = "SUPPORTS" if i == 0 else "REFUTES" if i == 1 else "INSUFFICIENT"
                cls.append({"source_url": u, "verdict": v, "key_quote": "quote"})
            return AIMessage(content="```json\n" + json.dumps({"reasoning": "r", "classifications": cls}) + "\n```")
        if "media credibility analyst" in text:
            kit.calls["bias"] += 1
            return AIMessage(content='{"credibility": 41, "political_lean": 55, "reasoning": "blog", "signals_detected": []}')
        if "senior research analyst" in text:
            kit.calls["summ"] += 1
            return AIMessage(content='```json\n{"executive_summary": "Nuclear power has a very low death rate per unit of energy.", "key_findings": [{"finding": "f", "confidence": 0.9, "supported_by": [], "caveat": null}], "areas_of_uncertainty": [], "contradiction_explanations": []}\n```')
        raise AssertionError("unexpected prompt: " + text[:100])
    return RunnableLambda(fake)


@pytest.fixture()
def kit(monkeypatch):
    """Fake model + fake search wired into every agent."""
    k = Kit()
    from agents import research, factcheck, critic, bias_detector, summarizer, ingest
    llm = _fake_llm(k)
    for mod in (research, factcheck, critic, bias_detector, summarizer):
        monkeypatch.setattr(mod, "_llm", llm)
    monkeypatch.setattr(ingest, "get_llm", lambda *_a, **_k: llm)
    tav = FakeTavily(k)
    monkeypatch.setattr(research, "tavily_deep", tav)
    monkeypatch.setattr(factcheck, "_tavily", tav)
    monkeypatch.setattr(critic, "_tavily", tav)
    return k


@pytest.fixture(scope="session")
def client():
    from starlette.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def no_ws_wait(monkeypatch):
    """TestClient finishes background tasks before returning, so do not wait for a WebSocket."""
    from services.ws_manager import manager

    async def instant(*_a, **_k): return True
    monkeypatch.setattr(manager, "wait_for_connection", instant)
