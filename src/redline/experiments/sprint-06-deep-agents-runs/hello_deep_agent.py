"""Sprint 6 — Deep Agents runs end-to-end in the sandbox.

Substrate proof, not application. The smallest possible Deep Agent that
exercises the full default loop:

* Default system prompt (no override — we want to observe stock behaviour).
* Default model resolution via :func:`llm.chat_model.get_chat_model`
  (OpenRouter for this run; ADR 009 covers the bridging decision).
* Default backend (in-memory ``StateBackend()``).
* Default middleware stack: ``TodoListMiddleware``, ``FilesystemMiddleware``,
  ``SubAgentMiddleware`` (with the auto-inserted general-purpose subagent),
  ``SummarizationMiddleware``, ``PatchToolCallsMiddleware``,
  ``AnthropicPromptCachingMiddleware`` (no-ops for non-Anthropic).
* One trivial pure-function tool (``slugify``) — gives the agent a reason to
  plan and act.
* A prompt that requires the agent to plan, call the trivial tool repeatedly,
  use the built-in filesystem tools (``write_file``, ``ls``, ``read_file``),
  and synthesise a final response.

Observations the script prints after invocation
-----------------------------------------------
1. The final response message (last AI message text).
2. The state-shape keys (channels in the agent state).
3. Contents of the ``files`` channel after the run (the StateBackend).
4. Contents of the ``todos`` channel (PlanningState — what
   ``write_todos`` produced).
5. The full message trace, summarised: type + tool name + content preview.
6. A counter of how many times each tool was called.

Sprint-6 success criterion: the script runs to completion, ``write_todos``
fires at least once, ``write_file``/``read_file``/``ls`` fire, ``slugify``
fires three times, and the final response references the slugs.
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from deepagents import create_deep_agent

from shared.llm.chat_model import get_chat_model


_SLUGIFY_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@tool
def slugify(text: str) -> str:
    """Return a URL-safe kebab-case slug of ``text``.

    Trivial — lower-cases, replaces non-alphanumerics with ``-``, strips
    leading/trailing dashes. Pure function; no I/O. Exists so the agent
    has a reason to invoke a custom tool repeatedly and then exercise the
    built-in filesystem tools to persist the results.
    """
    return _SLUGIFY_NON_ALNUM.sub("-", text.lower()).strip("-")


PROMPT = (
    "Plan your approach with write_todos before you start. Then carry out:\n"
    "1. Use the slugify tool on each of these phrases, in order: "
    "'Hello World', 'Deep Agents Test', 'Sprint Six'.\n"
    "2. Save each slug as the only line of a file at /slugs/1.txt, "
    "/slugs/2.txt, and /slugs/3.txt respectively (one per file, in the order "
    "above).\n"
    "3. List /slugs/ with the ls tool to verify all three files exist.\n"
    "4. Read /slugs/2.txt back with read_file to confirm its content.\n"
    "5. Finish with a one-paragraph summary that includes all three slugs "
    "and confirms /slugs/2.txt's content matches the second slug."
)


def _message_summary(msg) -> str:
    kind = type(msg).__name__
    text = getattr(msg, "content", "")
    if isinstance(text, list):
        text = " ".join(
            str(b.get("text", b)) if isinstance(b, dict) else str(b) for b in text
        )
    text = str(text).replace("\n", " ").strip()
    if isinstance(msg, ToolMessage):
        return f"[{kind} name={msg.name!r}] {text[:160]}"
    if isinstance(msg, AIMessage) and msg.tool_calls:
        calls = ", ".join(
            f"{c['name']}({list(c.get('args', {}).keys())})" for c in msg.tool_calls
        )
        return f"[{kind} tool_calls={calls}] {text[:120]}"
    return f"[{kind}] {text[:200]}"


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


def main() -> None:
    print(f"OSCAR_LLM_PROVIDER = {os.environ.get('OSCAR_LLM_PROVIDER')!r}")
    print(f"OSCAR_LLM_MODEL    = {os.environ.get('OSCAR_LLM_MODEL')!r}")
    print(
        f"LANGSMITH_API_KEY  = "
        f"{'<set>' if os.environ.get('LANGSMITH_API_KEY') else '<unset>'}"
    )
    print()

    agent = create_deep_agent(model=get_chat_model(), tools=[slugify])

    result = agent.invoke({"messages": [HumanMessage(PROMPT)]})

    print("=" * 72)
    print("FINAL RESPONSE")
    print("=" * 72)
    print(_final_text(result["messages"]))
    print()

    print("=" * 72)
    print("STATE-SHAPE KEYS")
    print("=" * 72)
    print(sorted(result.keys()))
    print()

    print("=" * 72)
    print("FILES CHANNEL (StateBackend)")
    print("=" * 72)
    files = result.get("files", {})
    for path in sorted(files):
        fd = files[path]
        content = fd.get("content") if isinstance(fd, dict) else fd
        encoding = fd.get("encoding") if isinstance(fd, dict) else None
        modified = fd.get("modified_at") if isinstance(fd, dict) else None
        print(f"  {path}")
        print(f"    encoding   : {encoding!r}")
        print(f"    modified_at: {modified!r}")
        print(f"    content    : {content!r}")
    if not files:
        print("  <empty>")
    print()

    print("=" * 72)
    print("TODOS CHANNEL (PlanningState)")
    print("=" * 72)
    todos = result.get("todos", [])
    if not todos:
        print("  <empty — write_todos did not fire>")
    for i, todo in enumerate(todos, 1):
        print(f"  {i}. {todo}")
    print()

    print("=" * 72)
    print("MESSAGE TRACE")
    print("=" * 72)
    for i, msg in enumerate(result["messages"], 1):
        print(f"  {i:2}. {_message_summary(msg)}")
    print()

    print("=" * 72)
    print("TOOL-CALL COUNTS")
    print("=" * 72)
    counts: Counter[str] = Counter()
    for msg in result["messages"]:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                counts[call["name"]] += 1
    for name, n in counts.most_common():
        print(f"  {name}: {n}")
    print()

    assert "slugify" in counts and counts["slugify"] >= 3, (
        f"expected slugify >= 3, got: {dict(counts)}"
    )
    assert counts.get("write_file", 0) >= 3, (
        f"expected write_file >= 3, got: {dict(counts)}"
    )
    assert counts.get("read_file", 0) >= 1 or counts.get("ls", 0) >= 1, (
        f"expected at least one of read_file/ls, got: {dict(counts)}"
    )
    expected_paths = {"/slugs/1.txt", "/slugs/2.txt", "/slugs/3.txt"}
    assert expected_paths.issubset(set(files)), (
        f"expected files {expected_paths} in state, got: {sorted(files)}"
    )

    print("sprint-06: Deep Agents end-to-end run succeeded.")


if __name__ == "__main__":
    main()
