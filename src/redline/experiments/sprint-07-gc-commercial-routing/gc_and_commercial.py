"""Sprint 7 — General Counsel orchestrator + Head of Commercial subagent.

Scaffolding for Oscar's in-house legal org chart on top of the Deep Agents
substrate proven in Sprint 6. One top-level agent (General Counsel), one
staffed department head (Head of Commercial), one yes/no routing decision.
Not a capability — the point is the routing pattern, not the answer quality.

Structure
---------

* **General Counsel** — ``create_deep_agent`` top-level. Model: frontier
  reasoning model via ``OSCAR_LLM_GENERAL_COUNSEL_*`` (this sprint: GPT-5.4
  through OpenRouter). System prompt classifies inbound work and delegates
  to a department head via the ``task`` tool. Only ``head-of-commercial`` is
  staffed; everything else → "this department is not yet staffed".
* **Head of Commercial** — ``SubAgent`` spec passed via ``subagents=[...]``.
  Model: capable-but-cheaper specialist via
  ``OSCAR_LLM_HEAD_OF_COMMERCIAL_*`` (this sprint: MiniMax-M2.7 direct).
  No extra tools, no further subagents. Returns a short description of
  what it would do rather than doing the work.

Two test prompts exercise the routing decision:

1. *"Please review this NDA against our standard position"* — expected
   route: commercial → delegates to Head of Commercial via ``task``.
2. *"Please file our annual return at Companies House"* — expected route:
   company-secretarial → responds "this department is not yet staffed",
   no delegation.

Model allocation (per ADR 010): GC = frontier, specialist = cheaper. Per-agent
model choice via per-agent env-var triple, injected at build time. Agents do
not pick their own models; the DI seam does.

The two test invocations' verbatim outputs, tool-call counts, and routing
verdict are captured by ``main()`` and echoed to PROJECT.md at sprint end.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deepagents import create_deep_agent

from shared.llm.chat_model import get_chat_model


GC_SYSTEM_PROMPT = (
    "You are the General Counsel of an in-house legal function. Your job is "
    "to classify inbound work and delegate to the right department head via "
    "the `task` tool.\n"
    "\n"
    "Currently staffed department heads (subagent names you can call via "
    "`task`):\n"
    "  - head-of-commercial: commercial contract work — NDAs, MSAs, SaaS "
    "agreements, procurement contracts, amendments.\n"
    "\n"
    "Other departments (company secretarial, data protection, employment, "
    "property, litigation, and anything else) are NOT yet staffed. For those "
    'requests, respond exactly: "this department is not yet staffed". '
    "Do not delegate when no department head is staffed for the request.\n"
    "\n"
    "When delegating to a staffed head, synthesise their response into a "
    "final reply to the user. When not delegating, reply directly."
)

HEAD_OF_COMMERCIAL_SYSTEM_PROMPT = (
    "You are the Head of Commercial in an in-house legal function. You are "
    "responsible for commercial contract work — NDAs, MSAs, SaaS agreements, "
    "procurement contracts, amendments, and similar.\n"
    "\n"
    "You have no tools and no sub-agents. When delegated a task, respond "
    "with a short string (one or two sentences) describing what you would "
    "do with the task. Do not attempt to perform the work itself."
)


def _build_head_of_commercial() -> dict:
    """Build the Head of Commercial subagent spec.

    Model is built fresh on each call so tests can swap env at runtime.
    """
    return {
        "name": "head-of-commercial",
        "description": (
            "Head of Commercial. Delegate commercial contract work — "
            "NDAs, MSAs, SaaS agreements, procurement contracts, amendments."
        ),
        "system_prompt": HEAD_OF_COMMERCIAL_SYSTEM_PROMPT,
        "tools": [],
        "model": get_chat_model(env_prefix="OSCAR_LLM_HEAD_OF_COMMERCIAL"),
    }


def build_agent():
    """Build the General Counsel agent with a Head of Commercial subagent."""
    gc_model = get_chat_model(env_prefix="OSCAR_LLM_GENERAL_COUNSEL")
    return create_deep_agent(
        model=gc_model,
        tools=[],
        system_prompt=GC_SYSTEM_PROMPT,
        subagents=[_build_head_of_commercial()],
    )


TEST_INVOCATIONS = [
    {
        "label": "nda-review",
        "prompt": "Please review this NDA against our standard position",
        "expected": "delegate to head-of-commercial",
    },
    {
        "label": "companies-house-filing",
        "prompt": "Please file our annual return at Companies House",
        "expected": "this department is not yet staffed (no delegation)",
    },
]


def _final_text(messages) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            text = msg.content
            if isinstance(text, list):
                text = " ".join(
                    str(b.get("text", b)) if isinstance(b, dict) else str(b)
                    for b in text
                )
            return str(text)
    return "<no final AI message found>"


def _message_summary(msg) -> str:
    kind = type(msg).__name__
    text = getattr(msg, "content", "")
    if isinstance(text, list):
        text = " ".join(
            str(b.get("text", b)) if isinstance(b, dict) else str(b) for b in text
        )
    text = str(text).replace("\n", " ").strip()
    if isinstance(msg, ToolMessage):
        return f"[{kind} name={msg.name!r}] {text[:220]}"
    if isinstance(msg, AIMessage) and msg.tool_calls:
        calls = ", ".join(
            f"{c['name']}({list(c.get('args', {}).keys())})" for c in msg.tool_calls
        )
        return f"[{kind} tool_calls={calls}] {text[:180]}"
    return f"[{kind}] {text[:260]}"


def _run_one(agent, label: str, prompt: str, expected: str) -> dict:
    print("=" * 72)
    print(f"INVOCATION: {label}")
    print(f"PROMPT:     {prompt}")
    print(f"EXPECTED:   {expected}")
    print("=" * 72)
    result = agent.invoke({"messages": [HumanMessage(prompt)]})

    counts: Counter[str] = Counter()
    for msg in result["messages"]:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                counts[call["name"]] += 1

    print("\n--- FINAL RESPONSE ---")
    print(_final_text(result["messages"]))
    print("\n--- TOOL-CALL COUNTS ---")
    for name, n in counts.most_common():
        print(f"  {name}: {n}")
    if not counts:
        print("  <no tool calls>")
    print("\n--- MESSAGE TRACE ---")
    for i, msg in enumerate(result["messages"], 1):
        print(f"  {i:2}. {_message_summary(msg)}")
    print()

    return {
        "label": label,
        "prompt": prompt,
        "expected": expected,
        "final": _final_text(result["messages"]),
        "counts": dict(counts),
        "messages": result["messages"],
    }


def main() -> None:
    print(
        f"OSCAR_LLM_GENERAL_COUNSEL_PROVIDER     = "
        f"{os.environ.get('OSCAR_LLM_GENERAL_COUNSEL_PROVIDER')!r}"
    )
    print(
        f"OSCAR_LLM_GENERAL_COUNSEL_MODEL        = "
        f"{os.environ.get('OSCAR_LLM_GENERAL_COUNSEL_MODEL')!r}"
    )
    print(
        f"OSCAR_LLM_HEAD_OF_COMMERCIAL_PROVIDER  = "
        f"{os.environ.get('OSCAR_LLM_HEAD_OF_COMMERCIAL_PROVIDER')!r}"
    )
    print(
        f"OSCAR_LLM_HEAD_OF_COMMERCIAL_MODEL     = "
        f"{os.environ.get('OSCAR_LLM_HEAD_OF_COMMERCIAL_MODEL')!r}"
    )
    print()

    agent = build_agent()
    runs = [_run_one(agent, **inv) for inv in TEST_INVOCATIONS]

    print("=" * 72)
    print("SPRINT 7 VERDICT")
    print("=" * 72)
    # Invocation 1 should fire `task` exactly once.
    nda = runs[0]
    ch = runs[1]
    nda_task = nda["counts"].get("task", 0)
    ch_task = ch["counts"].get("task", 0)
    print(f"  NDA invocation: task calls = {nda_task} (expected 1)")
    print(f"  Companies House invocation: task calls = {ch_task} (expected 0)")
    assert nda_task == 1, f"expected task=1 for NDA, got {nda_task}"
    assert ch_task == 0, f"expected task=0 for Companies House, got {ch_task}"
    assert "not yet staffed" in ch["final"].lower(), (
        f"expected 'not yet staffed' in Companies House final, "
        f"got: {ch['final']!r}"
    )

    print("\nsprint-07: routing scaffolding end-to-end run succeeded.")


if __name__ == "__main__":
    main()
