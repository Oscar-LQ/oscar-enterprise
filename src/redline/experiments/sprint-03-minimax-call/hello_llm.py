"""Sprint 3 — LangGraph node round-trips a prompt through the LLM DI seam.

Proves that a LangGraph node in this sandbox can call a runtime-injected
LLM (MiniMax for this sprint) and capture its response into state.

Scope: one graph, two nodes, in-memory state only. No Deep Agents, no
channels, no checkpointer, no streaming, no tools.

Design
------
State: ``prompt`` (input, str) and ``response`` (output, str).

    call_llm:  state["response"] = llm(state["prompt"])
    present:   prints the prompt/response pair

Edges: ``START -> call_llm -> present -> END``.

The LLM client is injected at graph-build time via ``build(llm)``: this
keeps the node agnostic to provider and lets tests pass a fake without
touching env vars. In main() the client comes from ``get_llm_client()``,
which reads OSCAR_LLM_PROVIDER / OSCAR_LLM_MODEL / OSCAR_LLM_API_KEY.

Success criterion
-----------------
With a live MiniMax API key and the sandbox network policy widened for
api.minimax.io:443, a non-empty response containing "ok" is returned for
the prompt "Reply with exactly: ok". Exact equality is too strict —
models sometimes paraphrase or add punctuation — so we assert
containment only. The point is integration, not output quality.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from llm import LLMClient, get_llm_client


class State(TypedDict):
    prompt: str
    response: str


def build(llm: LLMClient) -> CompiledStateGraph:
    def call_llm(state: State) -> dict:
        return {"response": llm(state["prompt"])}

    def present(state: State) -> dict:
        print(f"prompt:   {state['prompt']}")
        print(f"response: {state['response']}")
        return {}

    graph: StateGraph = StateGraph(State)
    graph.add_node("call_llm", call_llm)
    graph.add_node("present", present)
    graph.add_edge(START, "call_llm")
    graph.add_edge("call_llm", "present")
    graph.add_edge("present", END)
    return graph.compile()


def main() -> None:
    compiled = build(get_llm_client())
    initial: State = {
        "prompt": "Reply with exactly: ok",
        "response": "",
    }
    result = compiled.invoke(initial)

    assert result["response"], "LLM returned an empty response"
    assert "ok" in result["response"].lower(), (
        f"expected 'ok' in response, got: {result['response']!r}"
    )
    print("\nsprint-03: MiniMax round-trip succeeded.")


if __name__ == "__main__":
    main()
