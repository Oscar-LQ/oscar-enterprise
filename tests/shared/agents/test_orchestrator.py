"""Unit tests for Oscar — the M3 LangChain orchestrator.

Uses a tiny ``_FakeChatModel`` that pops canned ``AIMessage`` instances
from a queue and treats ``bind_tools`` as a no-op (the canned messages
already encode any tool_calls). Plus a fake ``redline_nda`` tool that
records calls. No real LLM, no real pipeline. The real pipeline is
exercised end-to-end in the live integration test (Phase 3).
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from shared.agents.orchestrator import build_orchestrator


class _FakeChatModel(BaseChatModel):
    """Pops canned AIMessages from a queue. ``bind_tools`` is a no-op."""

    responses: list[AIMessage] = Field(default_factory=list)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        msg = self.responses.pop(0)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "_fake_for_tests"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        # The canned AIMessages already encode any tool_calls; no real
        # binding required for these tests.
        return self


class _FakeRedlineToolInput(BaseModel):
    brief: str


def _fake_redline_tool(call_log: list[str]) -> BaseTool:
    """Build a fake `redline_nda` tool that records `brief` per call."""

    async def _redline_nda(brief: str) -> dict:
        call_log.append(brief)
        return {
            "output_path": "/tmp/fake.docx",
            "elapsed_seconds": 1.0,
            "decisions_total": 3,
            "decisions_accepted": 2,
            "decisions_countered": 1,
            "decisions_commented": 2,
            "summary": "Reviewed 3 changes (2 accepted, 1 counter-proposed, 2 commented). Output at /tmp/fake.docx.",
        }

    return StructuredTool.from_function(
        coroutine=_redline_nda,
        name="redline_nda",
        description="Fake redline tool for orchestrator tests.",
        args_schema=_FakeRedlineToolInput,
    )


@pytest.mark.asyncio
async def test_orchestrator_passes_through_simple_question() -> None:
    """When no tool call is needed, the orchestrator returns the model's reply.

    Off-scope requests should produce the canned "not yet wired" message
    per Oscar's system prompt; the orchestrator must surface that as the
    final AIMessage so the dispatcher posts it to Slack.
    """
    canned = (
        "this work needs a partner-level review and I haven't been wired "
        "into the heads of practice yet — flagging for the human partner"
    )
    model = _FakeChatModel(responses=[AIMessage(content=canned)])
    tool = _fake_redline_tool(call_log=[])

    graph = build_orchestrator(redline_tool=tool, model=model)
    result = await graph.ainvoke(
        {"messages": [HumanMessage("Can you draft a share purchase agreement?")]},
        config={"configurable": {"thread_id": "T1"}},
    )

    msgs = result["messages"]
    final_ai = next(
        m for m in reversed(msgs) if isinstance(m, AIMessage) and m.content
    )
    assert "partner-level review" in final_ai.content


@pytest.mark.asyncio
async def test_orchestrator_calls_redline_tool_on_nda_brief() -> None:
    """Model emits a tool call → orchestrator runs the tool → model replies.

    Turn 1: model returns an AIMessage with `tool_calls=[redline_nda]`.
    Turn 2: model returns a plain AIMessage paraphrasing the result.
    The orchestrator must invoke the tool with the planner's `args` and
    surface the second-turn AIMessage to the dispatcher.
    """
    call_log: list[str] = []
    tool = _fake_redline_tool(call_log)

    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "redline_nda",
                "args": {"brief": "review this NDA, our usual position"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    final_msg = AIMessage(
        content="Done — reviewed 3 changes; output written to /tmp/fake.docx."
    )
    model = _FakeChatModel(responses=[tool_call_msg, final_msg])

    graph = build_orchestrator(redline_tool=tool, model=model)
    result = await graph.ainvoke(
        {"messages": [HumanMessage("review this NDA, our usual position")]},
        config={"configurable": {"thread_id": "T2"}},
    )

    assert call_log == ["review this NDA, our usual position"]

    msgs = result["messages"]
    final_ai = next(
        m for m in reversed(msgs) if isinstance(m, AIMessage) and m.content
    )
    assert "Done" in final_ai.content


@pytest.mark.asyncio
async def test_orchestrator_routes_through_supplied_tool() -> None:
    """The injected tool — not a built-in — is what the agent calls.

    Pins the dispatcher contract: the runtime constructs a fresh
    redline tool per invocation (with a Slack-thread-scoped progress
    callback bound in closure) and passes it to ``build_orchestrator``.
    If the orchestrator ignored the supplied tool, progress narration
    would silently break.
    """
    call_log_a: list[str] = []
    call_log_b: list[str] = []
    tool_a = _fake_redline_tool(call_log_a)
    tool_b = _fake_redline_tool(call_log_b)

    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "redline_nda",
                "args": {"brief": "test"},
                "id": "c1",
                "type": "tool_call",
            }
        ],
    )
    final_msg = AIMessage(content="done")

    model_a = _FakeChatModel(responses=[tool_call_msg, final_msg])
    graph_a = build_orchestrator(redline_tool=tool_a, model=model_a)
    await graph_a.ainvoke(
        {"messages": [HumanMessage("review this NDA")]},
        config={"configurable": {"thread_id": "TA"}},
    )

    assert call_log_a == ["test"]
    assert call_log_b == []  # the unused tool stays unused


@pytest.mark.asyncio
async def test_orchestrator_preserves_thread_id_across_turns() -> None:
    """Same `thread_id` retains conversation state via MemorySaver.

    M3 keeps M2's per-conversation memory contract — the dispatcher
    passes one MemorySaver instance to ``build_orchestrator`` and re-uses
    it across per-invocation rebuilds (ADR 028). Two ``ainvoke`` calls on
    the same thread_id should see both inbound messages on the second
    turn.
    """
    checkpointer = MemorySaver()
    model = _FakeChatModel(
        responses=[
            AIMessage(content="first reply"),
            AIMessage(content="second reply"),
        ]
    )
    tool = _fake_redline_tool(call_log=[])
    graph = build_orchestrator(
        redline_tool=tool, model=model, checkpointer=checkpointer
    )

    config = {"configurable": {"thread_id": "T_persist"}}
    await graph.ainvoke({"messages": [HumanMessage("turn 1")]}, config=config)
    result2 = await graph.ainvoke(
        {"messages": [HumanMessage("turn 2")]}, config=config
    )

    msgs2 = result2["messages"]
    human_contents = [m.content for m in msgs2 if isinstance(m, HumanMessage)]
    assert "turn 1" in human_contents
    assert "turn 2" in human_contents
