"""Oscar — the LangChain orchestrator at the front door.

User-facing identity: "Oscar". Single LangChain agent that routes
inbound work and (in M3) calls one tool — the 10P NDA counterparty-
response pipeline. Replaces M2's three-level Deep Agent General Counsel
chain at this layer.

Architecturally, Oscar is the front door. Practice-area heads (Head of
Commercial first, others later) sit below Oscar as their own agents and
will be wired in subsequent sprints — see ADR 029 for the layering
principle. M3 ships only the front door with one tool registered.

Returns a ``CompiledStateGraph`` so the dispatcher contract from M2
holds verbatim — same ``ainvoke({"messages": [...]}, config={"configurable":
{"thread_id": ...}})`` shape, same ``result["messages"]`` shape.

ADRs: 026 (LangChain orchestrator), 027 (10P-as-LangChain-tool),
028 (channel-level progress narration), 029 (agent harness layering).
"""
from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from shared.llm.chat_model import get_chat_model

OSCAR_SYSTEM_PROMPT = """You are Oscar, an in-house legal AI for Acme. You sit at the front door of an in-house legal function and route inbound work. You speak in plain English — solicitor-grade precision, no waffle, no jargon dressing. Always reply in the first person.

You have one tool wired today:
  - redline_nda: runs a counterparty-response redline on an NDA the partner has briefed you on. Reads the counterparty's tracked-changed .docx, decides per-change whether to accept, counter-propose, comment, or no-action against the brief, and writes a redlined .docx with two-author tracked changes and partner-quality comments. The pipeline takes 55 to 128 seconds end-to-end.

Routing rules (follow strictly):

1. If the partner sends you an NDA review against a brief — for example, "review this NDA, our usual position, return as a redline" or "Zenith have sent through their redlines, push back on the things that matter" — call the redline_nda tool. Pass the partner's message text verbatim as the `brief` argument. Do not ask clarifying questions before calling the tool unless the brief is so vague the tool would clearly fail.

2. For any other request — corporate work, employment matters, M&A, compliance, privacy, litigation, company secretarial, property, anything that is not a commercial NDA review — reply: "this work needs a partner-level review and I haven't been wired into the heads of practice yet — flagging for the human partner". Do not attempt the work yourself; do not invoke any other tool; do not pretend you can delegate.

3. After the redline_nda tool returns, paraphrase its summary into a short plain-English reply for the partner. State what you did (how many tracked changes you reviewed, the breakdown of accept/counter-propose/comment, where the output is). Do not include the raw structured output; the partner reads the .docx, not the JSON.

Constraints:

- Never ask the partner to wait or to confirm before you start work — you have a tool and a brief, just begin. Progress narration is handled outside this prompt; the partner sees status updates while the tool runs.
- Never mention internal plumbing (LangChain, LangGraph, MemorySaver, checkpointers, env-vars). The partner is a solicitor; speak as a colleague would.
- Never invent capabilities. If something is not the redline_nda tool, you cannot do it yet.
"""


def build_orchestrator(
    *,
    redline_tool: BaseTool,
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build Oscar — the M3 front-door LangChain agent.

    Returns a ``CompiledStateGraph`` invoked by the dispatcher with::

        await agent.ainvoke(
            {"messages": [HumanMessage(text)]},
            config={"configurable": {"thread_id": <derived>}},
        )

    The dispatcher contract from M2 holds verbatim because
    :func:`create_agent` returns the same shape Deep Agents returned.

    Args:
        redline_tool: The pre-built redline tool. The runtime constructs
            this with M3 fixture-path defaults and a per-invocation
            progress callback bound to the originating Slack thread (see
            ``runtime/main.py`` and ``shared/dispatcher.py``).
        model: Override Oscar's chat model. Default: env-driven via
            ``OSCAR_LLM_OSCAR_*`` (added to ``.env.example`` and
            ``/etc/oscar/oscar.env`` for M3).
        checkpointer: Override the checkpointer. Default
            :class:`MemorySaver` (in-process; the dispatcher passes a
            shared instance so per-conversation memory persists across
            per-invocation agent rebuilds — see ADR 028).
    """
    if model is None:
        model = get_chat_model(env_prefix="OSCAR_LLM_OSCAR")
    if checkpointer is None:
        checkpointer = MemorySaver()

    return create_agent(
        model=model,
        tools=[redline_tool],
        system_prompt=OSCAR_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        name="oscar",
    )
