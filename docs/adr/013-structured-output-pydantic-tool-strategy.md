# ADR 013 — Structured Output from Specialist Sub-agents via Pydantic + ToolStrategy

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** How functional specialist sub-agents return machine-consumable decisions to their parent agent through Deep Agents' `task` tool
- **Supersedes:** none
- **Related:** ADR 010 (per-agent allocation), ADR 011 (MiniMax via OpenAI-compat), ADR 012 (`reasoning_split`), Sprint 9 brief

## Context

Sprint 9 introduces the first functional specialist (`accept-reject-reasoner`)
that must return a *structured* decision rather than prose. Parent agents
need to parse the decision (`accept | reject | counter`), not just quote
it. Three mechanisms for structured output were on the table:

1. JSON-in-prompt convention — describe the JSON in the system prompt and
   parse after the fact, with a retry-on-malformed wrapper.
2. `ChatOpenAI.with_structured_output(..., method="json_schema")` —
   OpenAI's native `response_format={type: "json_schema"}` mode.
3. `SubAgent.response_format = <Pydantic class>` — LangChain's
   `create_agent` auto-selects a strategy; Deep Agents' `task` tool
   serialises the structured response to the parent's `ToolMessage`.

Empirical check with MiniMax-M2.7 through the OpenAI-compat endpoint:

- **(2) json_schema mode fails.** MiniMax returns freeform markdown even
  when the request carries `response_format={type: "json_schema", ...}`;
  `pydantic_core.ValidationError: Invalid JSON` at parse time.
- **(2') function_calling / tool mode succeeds.** Binding the schema as a
  tool and forcing tool_choice produces clean, validated Pydantic
  instances across all three Rule GL-001 test cases.
- `langchain.agents.factory._supports_provider_strategy` (`factory.py:499-539`)
  returns `False` for MiniMax-M2.7 (no `profile.structured_output`, not
  in `FALLBACK_MODELS_WITH_STRUCTURED_OUTPUT`). So `AutoStrategy`
  auto-selects `ToolStrategy` (`factory.py:1199-1209`), i.e. the
  function-calling path we just verified.

## Decision

**Specialist sub-agents declare `response_format=<Pydantic class>` on
their `SubAgent` spec.** `create_agent` sees a Pydantic class, wraps it
in `AutoStrategy`, and for MiniMax (no provider-strategy support)
auto-picks `ToolStrategy`. The structured output tool is bound with
`tool_choice="any"` so the model is forced to call it.
`ToolStrategy.handle_errors=True` (default) catches schema-validation
errors and retries with a templated correction message.

Deep Agents' `task` tool (`deepagents/middleware/subagents.py:386-393`)
detects `structured_response` on the sub-agent's return state and
serialises via `BaseModel.model_dump_json()` — the parent's
`ToolMessage.content` is a clean JSON string, not the last
`AIMessage.text`.

Schema shape for `accept-reject-reasoner` (Sprint 9):

```python
class AcceptRejectDecision(BaseModel):
    decision: Literal["accept", "reject", "counter"]
    reason: str
    counter_language: str = Field(default="")  # non-empty iff decision == "counter"
```

`counter_language` is a required string (empty when not counter) rather
than `Optional[str]`. Optional fields are not in the JSON schema's
`required` list and MiniMax routinely omits them even when the prompt
asks for them; a required-with-empty-default field is present in every
tool call and the specialist's prompt enforces the counter-case value.

Rejected:
- **JSON-in-prompt + manual retry.** Works, but reimplements what
  `ToolStrategy.handle_errors` already does. Pointless when the
  framework's auto-path works with MiniMax today.
- **`with_structured_output(..., method="json_schema")` directly.**
  Empirically fails against MiniMax (markdown, not JSON) — the OpenAI-
  compat shim does not enforce the native `response_format` contract.
- **Provider strategy via AutoStrategy.** Same failure path as above;
  only forestalled by MiniMax not being in the provider-strategy allow
  lists.
- **Optional/nullable `counter_language`.** MiniMax often omits it even
  when the prompt requires it, because it is not `required` in the
  JSON schema derived from the Pydantic class.

## Consequences

- **Pro:** no new dependencies, no new middleware, no custom parsers.
  The specialist spec carries the schema; the framework does the rest.
- **Pro:** `ToolMessage.content` from the parent's perspective is a
  well-formed JSON string the parent can parse (or hand to a downstream
  consumer) without string-munging.
- **Pro:** `ToolStrategy.handle_errors=True` gives built-in graceful
  degradation on malformed tool calls — the retry hook exists without
  any code we wrote.
- **Con:** the forced tool-call rules out the specialist returning a
  plain-prose "I don't know" — the model must emit a Decision or the
  schema validator rejects the call. For a narrow three-path rule
  (accept, reject, counter) this is the right discipline; a richer
  future rule set may want a fourth `needs_more_information` decision
  added to the `Literal`.
- **Con:** if MiniMax starts honouring OpenAI-compat `response_format`,
  AutoStrategy would still pick ToolStrategy (MiniMax remains absent
  from the allow lists). To switch, the factory or this ADR gets
  revisited. Not a live concern.
- **Carry-forward:** other specialists (comment-responder, defined-terms
  auditor, fresh-language drafter) should follow the same pattern —
  one Pydantic schema per specialist, declared on the `SubAgent` spec,
  surfaced to the parent via `task`'s automatic JSON serialisation.
