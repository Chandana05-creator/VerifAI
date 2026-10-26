"""VerifAI — backend/agents/pipeline.py — LangGraph orchestration

  question:  research -> factcheck -> (low confidence? back to research, max 2x) -> critic -> bias -> summarizer
  link / text / image:  ingest -> factcheck -> critic -> bias -> summarizer     (no web re-search loop)

The Critic runs in "deep" mode only. The Summarizer needs the Bias Detector's scores, so those run in sequence.
"""
import functools
import time

from langgraph.graph import StateGraph, START, END

from agents.state import AgentState, make_initial_state
from agents.ingest import run_ingest
from agents.research import run_research
from agents.factcheck import run_factcheck
from agents.critic import run_critic
from agents.bias_detector import run_bias_detector
from agents.summarizer import run_summarizer
from services import metrics
from services.ws_manager import manager
from config import settings

CONFIDENCE_THRESHOLD = settings.confidence_threshold
MAX_LOOPS = settings.max_research_loops


def _unique_sources(sources: list[dict]) -> list[dict]:
    """`sources` accumulates across re-search loops, so drop repeated URLs."""
    seen, unique = set(), []
    for s in sources:
        url = s.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append(s)
    return unique


async def _running(state: AgentState, agent: str, message: str) -> None:
    await manager.broadcast(state["session_id"], {"type": "agent_update", "agent": agent,
                                                  "status": "running", "message": message, "payload": None})


def _error(agent: str, e: Exception) -> dict:
    print(f"[pipeline] {agent} error: {e}")
    metrics.add_error(agent, str(e))
    return {"type": "error", "agent": agent, "status": "error", "message": str(e)[:300], "payload": None}


def _done(agent: str, message: str) -> dict:
    return {"type": "agent_update", "agent": agent, "status": "done", "message": message, "payload": None}


def timed(agent: str):
    """Record how long each agent takes (summed over re-search loops) for the analytics page."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(state):
            t0 = time.perf_counter()
            try:
                return await fn(state)
            finally:
                metrics.add_agent_time(agent, time.perf_counter() - t0)
        return wrapper
    return deco


# ── nodes ───────────────────────────────────────────────────────

@timed("ingest")
async def ingest_node(state: AgentState) -> dict:
    await _running(state, "ingest", "Reading the input…")
    try:
        res = await run_ingest(state["input_kind"], state["input_value"], state["session_id"])
        text = res["text"]
        if len(text.strip()) < 40:
            raise ValueError("Not enough readable text was found in the input.")
        sources = ([{"url": res["url"], "title": res["title"] or res["url"], "content": text[:800], "source": "input"}]
                   if res.get("url") else [])
        context = f"Text under review ({res.get('title') or state['input_kind']}):\n\n{text}"
        return {"context": context, "sources": sources, "input_title": res.get("title", ""),
                "events": [_done("ingest", f"Read {len(text.split())} words")]}
    except Exception as e:
        return {"context": "", "sources": [], "events": [_error("ingest", e)]}


@timed("research")
async def research_node(state: AgentState) -> dict:
    await _running(state, "research", "Searching the web and indexed documents…")
    try:
        result = await run_research(query=state["query"], existing_claims=state.get("claims", []),
                                    loop=state.get("loop_count", 0))
        n = len(result["sources"])
        ev = (_done("research", f"{n} sources retrieved") if n else
              {"type": "error", "agent": "research", "status": "error", "payload": None,
               "message": "No sources retrieved — check your Tavily key and internet connection"})
        return {"sources": result["sources"], "context": result["context"], "events": [ev]}
    except Exception as e:
        return {"sources": [], "context": state.get("context", ""), "events": [_error("research", e)]}


@timed("factcheck")
async def factcheck_node(state: AgentState) -> dict:
    await _running(state, "factcheck", "Extracting and verifying claims…")
    try:
        result = await run_factcheck(context=state["context"], sources=state["sources"],
                                     require_sources=state["input_kind"] == "question")
        avg = result["avg_confidence"]
        low = bool(result["claims"]) and avg < CONFIDENCE_THRESHOLD
        return {"claims": result["claims"], "avg_confidence": avg, "contradictions": result["contradictions"],
                "loop_count": state.get("loop_count", 0) + (1 if low else 0),
                "events": [_done("factcheck", f"{len(result['claims'])} claims verified, average confidence {avg:.2f}")]}
    except Exception as e:
        return {"claims": [], "avg_confidence": 0.0, "contradictions": [], "events": [_error("factcheck", e)]}


@timed("critic")
async def critic_node(state: AgentState) -> dict:
    if state["mode"] == "quick" or not settings.enable_critic or not state["claims"]:
        why = "Skipped (quick mode)" if state["mode"] == "quick" else "Skipped (nothing to challenge)"
        return {"events": [_done("critic", why)]}
    await _running(state, "critic", "Searching for evidence against the strongest claims…")
    try:
        r = await run_critic(state["claims"])
        o = r["outcomes"]
        msg = (f"Challenged {r['challenged']} claims: {o['upheld']} upheld, {o['weakened']} weakened, "
               f"{o['downgraded']} downgraded")
        return {"claims": r["claims"], "avg_confidence": r["avg_confidence"], "contradictions": r["contradictions"],
                "events": [_done("critic", msg)]}
    except Exception as e:    # the Critic is an extra check: if it fails, keep the Fact-Check results
        return {"events": [_error("critic", e)]}


@timed("bias_detector")
async def bias_detector_node(state: AgentState) -> dict:
    await _running(state, "bias_detector", "Scoring source credibility and political lean…")
    try:
        sources = [s for s in _unique_sources(state["sources"]) if s.get("url")]
        scores = await run_bias_detector(sources=sources)
        n = len([s for s in scores if "__fleet__" not in s])
        return {"source_scores": scores, "events": [_done("bias_detector", f"{n} sources scored")]}
    except Exception as e:
        return {"source_scores": [], "events": [_error("bias_detector", e)]}


@timed("summarizer")
async def summarizer_node(state: AgentState) -> dict:
    await _running(state, "summarizer", "Writing the final report…")
    try:
        out = await run_summarizer(query=state["query"], claims=state["claims"],
                                   sources=[s for s in _unique_sources(state["sources"]) if s.get("url")],
                                   source_scores=state["source_scores"], contradictions=state["contradictions"],
                                   context=state["context"])
        report = {**out["report"], "input_kind": state["input_kind"], "mode": state["mode"]}
        return {"final_report": report, "citations": out["citations"],
                "events": [{"type": "final_report", "agent": "summarizer", "status": "done",
                            "message": "Report generated", "payload": report}]}
    except Exception as e:
        return {"final_report": None, "citations": [], "events": [_error("summarizer", e)]}


# ── routing ─────────────────────────────────────────────────────

def route_start(state: AgentState) -> str:
    return "research" if state["input_kind"] == "question" else "ingest"


def route_after_factcheck(state: AgentState) -> str:
    """Re-search only for questions, when there ARE claims, confidence is low and loops remain.
    (With no claims, e.g. after an API error, re-searching cannot help.)"""
    low = bool(state.get("claims")) and state.get("avg_confidence", 0.0) < CONFIDENCE_THRESHOLD
    again = low and state["input_kind"] == "question" and state.get("loop_count", 0) <= MAX_LOOPS
    return "re_research" if again else "continue"


def build_pipeline():
    g = StateGraph(AgentState)
    for name, fn in (("ingest_node", ingest_node), ("research_node", research_node), ("factcheck_node", factcheck_node),
                     ("critic_node", critic_node), ("bias_detector_node", bias_detector_node),
                     ("summarizer_node", summarizer_node)):
        g.add_node(name, fn)
    g.add_conditional_edges(START, route_start, {"research": "research_node", "ingest": "ingest_node"})
    g.add_edge("ingest_node", "factcheck_node")
    g.add_edge("research_node", "factcheck_node")
    g.add_conditional_edges("factcheck_node", route_after_factcheck,
                            {"re_research": "research_node", "continue": "critic_node"})
    g.add_edge("critic_node", "bias_detector_node")
    g.add_edge("bias_detector_node", "summarizer_node")
    g.add_edge("summarizer_node", END)
    return g.compile()


pipeline = build_pipeline()


async def run_pipeline_streaming(session_id: str, query: str, mode: str, ws_manager,
                                 input_kind: str = "question", input_value: str = "") -> dict:
    """Run the pipeline and stream each agent's events to the browser."""
    from services import session_store

    # the browser opens its WebSocket right after the POST returns; wait so no event is lost
    await ws_manager.wait_for_connection(session_id)
    metrics.start(session_id)

    state = make_initial_state(query=query, mode=mode, session_id=session_id,
                               input_kind=input_kind, input_value=input_value)
    final_state, sent = None, 0
    try:
        async for snapshot in pipeline.astream(state, stream_mode="values", config={"recursion_limit": 50}):
            final_state = snapshot
            events = snapshot.get("events", [])
            for ev in events[sent:]:          # `events` accumulates, so only send the new ones
                await ws_manager.broadcast(session_id, ev)
            sent = len(events)
    except Exception as e:
        print(f"[pipeline] pipeline aborted: {e}")
        metrics.add_error("system", str(e))
        await ws_manager.broadcast(session_id, {"type": "error", "agent": "system", "status": "error",
                                                "message": f"Pipeline failed: {e}"[:300], "payload": None})

    run_metrics = metrics.finish(session_id)
    run_metrics["models"] = {"strong": settings.gemini_model_strong, "fast": settings.gemini_model_fast}
    fs = final_state or {}
    try:
        await session_store.update_session(
            session_id=session_id, final_report=fs.get("final_report"),
            claim_count=len(fs.get("claims", [])), avg_confidence=fs.get("avg_confidence", 0.0),
            metrics=run_metrics)
    except Exception as e:
        print(f"[pipeline] could not save session {session_id}: {e}")

    await ws_manager.broadcast(session_id, {"type": "pipeline_complete", "agent": "system", "status": "done",
                                            "message": "Pipeline finished", "payload": run_metrics})
    return fs
