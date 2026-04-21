"""Sprint 9 — General Counsel + Head of Commercial + accept/reject specialist.

Three-level delegation on the Deep Agents substrate:
General Counsel (orchestrator, GPT-5.4 via OpenRouter)
  → Head of Commercial (department head, MiniMax-M2.7)
    → accept-reject-reasoner (functional specialist, MiniMax-M2.7)

The accept-reject-reasoner is the first *functional* (operational) agent:
given a single proposed contract markup plus a playbook rule, it decides
``accept | reject | counter`` and returns a structured :class:`Decision`
via ``SubAgent.response_format``. Rule GL-001 (Governing Law) is
hardcoded in the specialist's system prompt for this sprint; persistent
playbook storage is deferred (ADR 015).

The specialist uses ``response_format=<pydantic BaseModel>`` on its
SubAgent spec. LangChain's ``AutoStrategy`` auto-selects ``ToolStrategy``
for MiniMax (not in the provider-strategy allow list), binding the
schema as a tool with ``tool_choice="any"`` — the proven path for
MiniMax structured output (ADR 013). ``ToolStrategy.handle_errors=True``
gives graceful retry on malformed tool calls.

Three-level delegation works by wrapping Head of Commercial as its own
``create_deep_agent`` graph (with its own ``subagents=[specialist]``)
and plugging that compiled runnable into the General Counsel as a
``CompiledSubAgent`` (ADR 014). ``SubAgent`` has no ``subagents`` field;
``CompiledSubAgent`` is the documented escape hatch.

Three test invocations exercise the three decision paths:

1. Counterparty accepted E&W unchanged → expected ``accept``.
2. Counterparty wants Delaware → expected ``reject``.
3. Counterparty wants Scotland → expected ``counter`` (with
   counter_language populated).

Each invocation goes through all three levels. ``main()`` asserts that
each test produced the expected decision and that the specialist's
structured output parses cleanly.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from deepagents import create_deep_agent

from shared.llm.chat_model import get_chat_model


# ---------------------------------------------------------------------------
# Decision schema — parent agents parse this from the specialist's JSON
# ---------------------------------------------------------------------------


class AcceptRejectDecision(BaseModel):
    """Decision on a single proposed contract markup.

    Serialised to the parent's `ToolMessage.content` via
    `BaseModel.model_dump_json()` by Deep Agents' `task` tool when the
    specialist's `response_format` is set.
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
# System prompts — Rule GL-001 lives inline in the specialist's prompt
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
# Agent construction — three levels, per-role model via env-prefix DI
# ---------------------------------------------------------------------------


def _build_accept_reject_spec() -> dict:
    """SubAgent spec for the accept/reject specialist (under Head of Commercial)."""
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
        "model": get_chat_model(
            env_prefix="OSCAR_LLM_ACCEPT_REJECT_REASONER"
        ),
        "response_format": AcceptRejectDecision,
    }


def _build_head_of_commercial() -> dict:
    """Build the Head of Commercial as its own compiled Deep Agent.

    Returns a CompiledSubAgent dict so the General Counsel can plug this
    graph in via its `subagents=[...]` list (ADR 014 — SubAgent has no
    `subagents` field; CompiledSubAgent is the documented path for
    nesting).
    """
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


def build_agents() -> tuple:
    """Build GC (with nested HOC + specialist) and return a handle to HOC too.

    Returning the compiled HOC graph alongside GC lets us re-invoke just
    HOC to surface the specialist's `AcceptRejectDecision` JSON directly
    — the outer GC trace only shows HOC's prose wrap around it. Each
    call uses its own freshly-built HOC graph; state does not leak
    between GC and the probe.
    """
    gc_model = get_chat_model(env_prefix="OSCAR_LLM_GENERAL_COUNSEL")
    hoc_under_gc = _build_head_of_commercial()
    gc_agent = create_deep_agent(
        model=gc_model,
        tools=[],
        system_prompt=GC_SYSTEM_PROMPT,
        subagents=[hoc_under_gc],
    )
    # Separate HOC instance for direct probing (avoids sharing state).
    hoc_probe_graph = create_deep_agent(
        model=get_chat_model(env_prefix="OSCAR_LLM_HEAD_OF_COMMERCIAL"),
        tools=[],
        system_prompt=HEAD_OF_COMMERCIAL_SYSTEM_PROMPT,
        subagents=[_build_accept_reject_spec()],
    )
    return gc_agent, hoc_probe_graph


# ---------------------------------------------------------------------------
# Test invocations
# ---------------------------------------------------------------------------

TEST_INVOCATIONS = [
    {
        "label": "accept-ew-unchanged",
        "prompt": (
            "Please review this contract markup against our playbook. Rule "
            "GL-001 (Governing Law): the client's position is that governing "
            "law must be England and Wales. Any counterparty proposal to "
            "change governing law should be rejected unless the "
            "counter-proposal is to Scotland, Northern Ireland, or Ireland "
            "(in which case counter-propose England and Wales with a brief "
            "justification). Markup: the counterparty has accepted our "
            "proposed governing law of England and Wales without change."
        ),
        "expected_decision": "accept",
    },
    {
        "label": "reject-delaware",
        "prompt": (
            "Please review this contract markup against our playbook. Rule "
            "GL-001 (Governing Law): the client's position is that governing "
            "law must be England and Wales. Any counterparty proposal to "
            "change governing law should be rejected unless the "
            "counter-proposal is to Scotland, Northern Ireland, or Ireland "
            "(in which case counter-propose England and Wales with a brief "
            "justification). Markup: the counterparty wants to change "
            "governing law from England and Wales to Delaware."
        ),
        "expected_decision": "reject",
    },
    {
        "label": "counter-scotland",
        "prompt": (
            "Please review this contract markup against our playbook. Rule "
            "GL-001 (Governing Law): the client's position is that governing "
            "law must be England and Wales. Any counterparty proposal to "
            "change governing law should be rejected unless the "
            "counter-proposal is to Scotland, Northern Ireland, or Ireland "
            "(in which case counter-propose England and Wales with a brief "
            "justification). Markup: the counterparty wants to change "
            "governing law from England and Wales to Scotland."
        ),
        "expected_decision": "counter",
    },
]


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------


def _text_of(msg) -> str:
    text = getattr(msg, "content", "")
    if isinstance(text, list):
        parts: list[str] = []
        for block in text:
            if isinstance(block, dict):
                parts.append(str(block.get("text", block)))
            else:
                parts.append(str(block))
        text = " ".join(parts)
    return str(text)


def _final_text(messages) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            return _text_of(msg)
    return "<no final AI message found>"


def _summary(msg) -> str:
    kind = type(msg).__name__
    text = _text_of(msg).replace("\n", " ").strip()
    if isinstance(msg, ToolMessage):
        return f"[{kind} name={msg.name!r}] {text[:260]}"
    if isinstance(msg, AIMessage) and msg.tool_calls:
        calls = ", ".join(
            f"{c['name']}({list(c.get('args', {}).keys())})"
            for c in msg.tool_calls
        )
        return f"[{kind} tool_calls={calls}] {text[:220]}"
    return f"[{kind}] {text[:300]}"


def _gc_task_subagent_names(messages) -> list[str]:
    """Return the `subagent_type` values GC passed to each `task` tool call."""
    names: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                if call["name"] == "task":
                    names.append(call.get("args", {}).get("subagent_type", ""))
    return names


def _extract_specialist_json_from_messages(messages) -> dict | None:
    """Find the specialist's `AcceptRejectDecision` JSON in a message list.

    Two channels are possible and both are tolerated:

    * **Structured-response channel** — HOC's `task` tool serialised the
      specialist's `structured_response` via `BaseModel.model_dump_json()`,
      so the `ToolMessage(name='task')` content is raw JSON.
    * **Fallback prose channel** — if the specialist emitted prose (a
      MiniMax tool-call-discipline lapse we observed intermittently), the
      task tool falls back to `result["messages"][-1].text.rstrip()`,
      which for our specialist tends to be a JSON object wrapped in
      markdown code fences (``` / ```json / ```).

    We try raw JSON first, then strip code-fence wrappers and retry. Both
    reach the same `AcceptRejectDecision` shape.
    """
    for msg in messages:
        if not isinstance(msg, ToolMessage) or msg.name != "task":
            continue
        body = _text_of(msg).strip()
        parsed = _try_parse_json_with_fences(body)
        if isinstance(parsed, dict) and "decision" in parsed:
            return parsed
    return None


def _try_parse_json_with_fences(body: str) -> object:
    """Parse `body` as JSON, tolerating ``` / ```json markdown fences."""
    try:
        return json.loads(body)
    except Exception:
        pass
    # Strip matched fenced-code wrappers: ```json\n...\n``` or ```\n...\n```
    stripped = body.strip()
    for fence in ("```json", "```JSON", "```"):
        if stripped.startswith(fence):
            stripped = stripped[len(fence):]
            break
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    try:
        return json.loads(stripped.strip())
    except Exception:
        return None


def _run_one(
    gc_agent,
    hoc_graph,
    label: str,
    prompt: str,
    expected_decision: str,
) -> dict:
    """Run one test end-to-end (GC → HOC → specialist), then repeat the
    HOC slice directly to surface the specialist's structured JSON.

    The direct-HOC repeat is the only way to get the specialist's
    verbatim `AcceptRejectDecision` JSON out — in the GC-level trace
    HOC's `task` ToolMessage is already HOC's prose wrap, not the
    specialist's JSON.
    """
    print("=" * 72)
    print(f"INVOCATION: {label}")
    print(f"EXPECTED decision: {expected_decision}")
    print(f"PROMPT:\n{prompt}")
    print("=" * 72)

    # -- Full three-level chain via GC --
    result = gc_agent.invoke({"messages": [HumanMessage(prompt)]})

    counts: Counter[str] = Counter()
    for msg in result["messages"]:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                counts[call["name"]] += 1

    print("\n--- GC MESSAGE TRACE (three-level chain) ---")
    for i, msg in enumerate(result["messages"], 1):
        print(f"  {i:2}. {_summary(msg)}")

    print("\n--- GC task() subagent_types ---")
    for name in _gc_task_subagent_names(result["messages"]):
        print(f"  {name}")

    final = _final_text(result["messages"])
    print("\n--- FINAL RESPONSE (GC → user) ---")
    print(final)

    # -- Repeat just the HOC slice to surface the specialist's JSON --
    hoc_probe = hoc_graph.invoke({"messages": [HumanMessage(prompt)]})

    print("\n--- HOC INTERNAL MESSAGE TRACE (direct invoke, for specialist JSON) ---")
    for i, msg in enumerate(hoc_probe["messages"], 1):
        print(f"  {i:2}. {_summary(msg)}")

    specialist_json = _extract_specialist_json_from_messages(hoc_probe["messages"])
    print("\n--- SPECIALIST STRUCTURED OUTPUT (verbatim) ---")
    print(json.dumps(specialist_json, indent=2) if specialist_json else "<none found>")

    return {
        "label": label,
        "prompt": prompt,
        "expected_decision": expected_decision,
        "final": final,
        "counts": dict(counts),
        "gc_task_subagents": _gc_task_subagent_names(result["messages"]),
        "specialist_json": specialist_json,
        "messages": result["messages"],
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _echo_env() -> None:
    for name in [
        "OSCAR_LLM_GENERAL_COUNSEL_PROVIDER",
        "OSCAR_LLM_GENERAL_COUNSEL_MODEL",
        "OSCAR_LLM_HEAD_OF_COMMERCIAL_PROVIDER",
        "OSCAR_LLM_HEAD_OF_COMMERCIAL_MODEL",
        "OSCAR_LLM_ACCEPT_REJECT_REASONER_PROVIDER",
        "OSCAR_LLM_ACCEPT_REJECT_REASONER_MODEL",
    ]:
        print(f"{name:45s} = {os.environ.get(name)!r}")


def main() -> None:
    _echo_env()
    print()

    gc_agent, hoc_probe_graph = build_agents()
    runs = [_run_one(gc_agent, hoc_probe_graph, **inv) for inv in TEST_INVOCATIONS]

    print("\n" + "=" * 72)
    print("SPRINT 9 VERDICT")
    print("=" * 72)

    all_pass = True
    for run in runs:
        label = run["label"]
        expected = run["expected_decision"]
        sj = run["specialist_json"] or {}
        decided = sj.get("decision")

        # (a) GC routed to head-of-commercial at least once
        routed_through_hoc = "head-of-commercial" in run["gc_task_subagents"]

        # (b) Specialist produced a structured decision that parsed
        structured_ok = isinstance(sj.get("decision"), str) and isinstance(
            sj.get("reason"), str
        )

        # (c) The decision field matches the expected path
        decision_matches = decided == expected

        # (d) For counter, counter_language must be non-empty
        counter_language_ok = True
        if expected == "counter":
            counter_language_ok = bool((sj.get("counter_language") or "").strip())

        ok = (
            routed_through_hoc
            and structured_ok
            and decision_matches
            and counter_language_ok
        )
        all_pass = all_pass and ok
        print(
            f"  {label:22s} routed={routed_through_hoc} "
            f"structured={structured_ok} "
            f"decision={decided!r} (expected {expected!r}) "
            f"counter_language_ok={counter_language_ok} "
            f"OK={ok}"
        )

    print()
    if not all_pass:
        raise AssertionError(
            "One or more Sprint 9 invocations did not meet the success "
            "criterion (see per-run lines above)."
        )
    print("sprint-09: accept/reject specialist end-to-end run succeeded.")


if __name__ == "__main__":
    main()
