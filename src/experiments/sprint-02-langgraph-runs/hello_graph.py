"""Sprint 2 — minimal LangGraph that exercises state, nodes, edges, compile, invoke.

Proves langgraph 1.1.8 runs end-to-end in this sandbox, not just imports.
No LLM, no checkpointer, no tools — just state threading through two nodes.

Design
------
State carries two fields: ``message`` (str) and ``counter`` (int).
Two nodes with deliberately-distinct modifications so behaviour is diagnosable:

    append_hello: message += " hello",  counter += 1
    append_world: message += " world",  counter += 10

Edges: ``START -> append_hello -> append_world -> END`` (linear).

Input:    ``{"message": "greetings:", "counter": 0}``
Expected: ``{"message": "greetings: hello world", "counter": 11}``

The counter arithmetic (0 -> 1 -> 11) and the ordered string concatenation
together prove both nodes ran and ran in order. Diagnosable failure modes:

    counter == 1     only append_hello ran
    counter == 10    only append_world ran
    counter == 0     neither ran (state untouched)
    message ends "world hello"  nodes ran in reverse order
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph


class State(TypedDict):
    message: str
    counter: int


def append_hello(state: State) -> dict:
    return {
        "message": state["message"] + " hello",
        "counter": state["counter"] + 1,
    }


def append_world(state: State) -> dict:
    return {
        "message": state["message"] + " world",
        "counter": state["counter"] + 10,
    }


def build() -> CompiledStateGraph:
    graph: StateGraph = StateGraph(State)
    graph.add_node("append_hello", append_hello)
    graph.add_node("append_world", append_world)
    graph.add_edge(START, "append_hello")
    graph.add_edge("append_hello", "append_world")
    graph.add_edge("append_world", END)
    return graph.compile()


def main() -> None:
    compiled = build()
    initial: State = {"message": "greetings:", "counter": 0}
    result = compiled.invoke(initial)
    print(result)

    expected: State = {"message": "greetings: hello world", "counter": 11}
    assert result == expected, f"mismatch: expected {expected}, got {result}"


if __name__ == "__main__":
    main()
