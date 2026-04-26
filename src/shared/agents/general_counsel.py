"""General Counsel — production-located three-level Deep Agent.

Copy-not-import of the Sprint 9 pattern (M2 pre-flight decision § 6.1). The
Sprint 9 experiment file at
``src/redline/experiments/sprint-09-accept-reject-specialist/gc_commercial_acceptreject.py``
stays untouched; this module is the production-located equivalent the M2
dispatcher invokes.

Difference from Sprint 9: the GC graph is built with a ``checkpointer``
(default ``MemorySaver`` from ``langgraph.checkpoint.memory``) so the
dispatcher can pass a per-conversation ``thread_id`` via
``config={"configurable": {"thread_id": ...}}`` and multi-turn memory
persists per channel conversation (M2 pre-flight decision § 6.2).
"""
from __future__ import annotations

from typing import Literal

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from shared.llm.chat_model import get_chat_model


# ---------------------------------------------------------------------------
# Specialist structured output (verbatim from Sprint 9)
# ---------------------------------------------------------------------------


class AcceptRejectDecision(BaseModel):
    """Decision on a single proposed contract markup.

    Serialised to the parent's ``ToolMessage.content`` via
    ``BaseModel.model_dump_json()`` by Deep Agents' ``task`` tool when the
    specialist's ``response_format`` is set.
    """

    decision: Literal["accept", "reject", "counter"] = Field(
        description="One of accept, reject, counter."
    )
    reason: str = Field(description="One sentence explaining the decision.")
    counter_language: str = Field(
        default="",
        description=(
            "Proposed alternative wording. REQUIRED (non-empty) when "
            "decision == 'counter'. Empty string otherwise."
        ),
    )


# ---------------------------------------------------------------------------
# System prompts (verbatim from Sprint 9)
# ---------------------------------------------------------------------------


ACCEPT_REJECT_SYSTEM_PROMPT = """You are an accept/reject reasoner. Given a single proposed contract markup and the playbook rule that governs it, decide one of three outcomes: accept, reject, or counter.

Output discipline — READ THIS FIRST.
Your ONLY output channel is a single tool call to the `AcceptRejectDecision` tool with the structured arguments shown below. Do not write prose. Do not write a chat reply. Do not wrap the JSON in markdown code fences (```). Do not explain your reasoning outside the `reason` field of the tool call. Emit exactly one tool call and nothing else.

Rule GL-001 (Governing Law). The client's position is that governing law must be England and Wales. Apply this in exact order to every inbound markup:
  1. If the counterparty has accepted England and Wales, or left it unchanged, decide: accept.
  2. If the counterparty proposes Scotland, Northern Ireland, or Ireland as the governing law, decide: counter. The client still wants England and Wales. When deciding counter, you MUST populate `counter_language` with a complete, self-contained English sentence that restates England and Wales as the governing law, with a brief justification drafted for this markup.
  3. If the counterparty proposes any other jurisdiction (for example Delaware, New York, Singapore, Germany), decide: reject.

Rules for the Decision tool call:
- `decision` is exactly one of accept, reject, counter.
- `reason` is one sentence.
- `counter_language`: on counter decisions MUST be a non-empty English sentence the client would send back to the counterparty, drafted specifically for this markup (do not copy boilerplate). On accept and reject decisions, leave it as an empty string.

No hedging. No requests for more information. No other rules apply in this sprint."""


HEAD_OF_COMMERCIAL_SYSTEM_PROMPT = """You are the Head of Commercial in an in-house legal function. You are responsible for commercial contract work — NDAs, MSAs, SaaS agreements, procurement contracts, amendments, and similar.

Staffed specialists under you (subagent names to use with the `task` tool):
  - accept-reject-reasoner: decides accept / reject / counter on a single proposed contract markup against a playbook rule. Returns a structured JSON decision. Use this whenever an inbound task describes any counterparty position on a contract clause (including "accepted unchanged", "proposed change to X", or "struck through") and a playbook rule applies.

Routing rules (follow strictly):
  1. If the inbound task contains BOTH (a) a description of the counterparty's position on a single contract clause — whether that position is a proposed change, an acceptance, or a rejection — AND (b) a playbook rule that governs that clause type, you MUST delegate to `accept-reject-reasoner` via the `task` tool. Pass the markup description and the rule to the specialist verbatim; do not paraphrase either. Do not try to decide yourself. "Accepted unchanged" and "no change" still count as a counterparty position — delegate anyway.
  2. Only if there is no markup description at all, or no rule to apply, respond plainly (one or two sentences) describing what you would do. Do not attempt to perform the work yourself. No other specialists are staffed this sprint.

When `accept-reject-reasoner` returns a structured decision (JSON with `decision`, `reason`, and `counter_language`), relay it back to the General Counsel in plain English. State the decision, include the reason, and include the `counter_language` verbatim when the decision is "counter". Do not invent extra context; the specialist's decision is the answer."""


GC_SYSTEM_PROMPT = """You are the General Counsel of an in-house legal function. Your job is to classify inbound work and delegate to the right department head via the `task` tool.

Currently staffed department heads (subagent names you can call via `task`):
  - head-of-commercial: commercial contract work — NDAs, MSAs, SaaS agreements, procurement contracts, amendments, and any accept/reject/counter decisions on specific contract markups.

Other departments (company secretarial, data protection, employment, property, litigation, and anything else) are NOT yet staffed. For those requests, respond exactly: "this department is not yet staffed". Do not delegate when no department head is staffed for the request.

When delegating to a staffed head, synthesise their response into a final reply to the user. When not delegating, reply directly."""


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _build_accept_reject_spec() -> dict:
    """SubAgent spec for the accept/reject specialist (under HOC)."""
    return {
        "name": "accept-reject-reasoner",
        "description": (
            "Decides accept / reject / counter on a single proposed contract "
            "markup against a playbook rule. Call this when you have one "
            "markup and the governing rule and need a decision. Returns a "
            "structured AcceptRejectDecision JSON."
        ),
        "system_prompt": ACCEPT_REJECT_SYSTEM_PROMPT,
        "tools": [],
        "model": get_chat_model(env_prefix="OSCAR_LLM_ACCEPT_REJECT_REASONER"),
        "response_format": AcceptRejectDecision,
    }


def _build_head_of_commercial() -> dict:
    """Build HOC as its own compiled Deep Agent and wrap as CompiledSubAgent
    so the GC can plug it in via ``subagents=[...]`` (ADR 014 — SubAgent
    has no ``subagents`` field; CompiledSubAgent is the documented path
    for nesting)."""
    hoc_graph = create_deep_agent(
        model=get_chat_model(env_prefix="OSCAR_LLM_HEAD_OF_COMMERCIAL"),
        tools=[],
        system_prompt=HEAD_OF_COMMERCIAL_SYSTEM_PROMPT,
        subagents=[_build_accept_reject_spec()],
    )
    return {
        "name": "head-of-commercial",
        "description": (
            "Head of Commercial. Delegate commercial contract work — NDAs, "
            "MSAs, SaaS agreements, procurement contracts, amendments, and "
            "any accept/reject/counter decisions on specific contract markups."
        ),
        "runnable": hoc_graph,
    }


def build_general_counsel(
    *,
    gc_model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build the GC graph with a checkpointer wired at construction time.

    The returned graph is invoked by the dispatcher with::

        await gc.ainvoke(
            {"messages": [HumanMessage(text)]},
            config={"configurable": {"thread_id": <derived>}},
        )

    so multi-turn memory persists per conversation.

    Args:
        gc_model: Override the GC's chat model. Default: env-driven via
            ``OSCAR_LLM_GENERAL_COUNSEL_*``.
        checkpointer: Override the checkpointer. Default:
            ``MemorySaver()`` (in-process; carry-forward to a durable
            store flagged in ADR 023).
    """
    if gc_model is None:
        gc_model = get_chat_model(env_prefix="OSCAR_LLM_GENERAL_COUNSEL")
    if checkpointer is None:
        checkpointer = MemorySaver()

    return create_deep_agent(
        model=gc_model,
        tools=[],
        system_prompt=GC_SYSTEM_PROMPT,
        subagents=[_build_head_of_commercial()],
        checkpointer=checkpointer,
    )
