"""VerifAI — backend/agents/state.py — the shared state every agent reads and writes."""
from __future__ import annotations
from typing import Annotated, Optional
from operator import add
from typing_extensions import TypedDict


class AgentState(TypedDict):
    query: str
    mode: str                          # "deep" (with Critic) or "quick"
    session_id: str
    input_kind: str                    # question | url | text | image
    input_value: str                   # the link or the pasted text (images are held in services.inputs)
    input_title: str

    sources: Annotated[list, add]      # accumulates across re-search loops
    context: str

    claims: list
    avg_confidence: float
    contradictions: list

    source_scores: list

    final_report: Optional[dict]
    citations: list

    loop_count: int
    events: Annotated[list, add]       # accumulates; streamed to the browser


def make_initial_state(query: str, mode: str, session_id: str,
                       input_kind: str = "question", input_value: str = "") -> AgentState:
    return AgentState(
        query=query, mode=mode, session_id=session_id,
        input_kind=input_kind, input_value=input_value, input_title="",
        sources=[], context="",
        claims=[], avg_confidence=0.0, contradictions=[],
        source_scores=[],
        final_report=None, citations=[],
        loop_count=0, events=[],
    )
