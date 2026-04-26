# Sprint 10O — model routing verification

Per Arturs's post-Phase-3 verification request. Five checks against the
existing 10O artefacts on feature branch `sprint-10O-planner-executor`,
no new run.

## Summary

**Overall outcome: (a) — both calls served by the intended models** by
indirect evidence (transcript + provider routing + output character +
structure match), with a methodological gap on outcome (c) — the
canonical OpenRouter API envelope `model` field is not captured in the
artefacts. Routing is high-confidence-correct; the gap is in our
ability to *prove* it from artefacts alone going forward.

| Check | Outcome | Evidence |
|---|---|---|
| 1. Transcript env values at run time | ✅ confirmed | `transcript.txt` line 1 |
| 2. OpenRouter API envelope `model` field | ❌ not captured | `llm-output-*.txt` only contains `.content`, not the API envelope |
| 3. Cross-check by output character | ✅ consistent | Planner = analytical lawyer reasoning; executors = compact MiniMax JSON |
| 4. API key routing (planner vs executor) | ✅ confirmed | Different `_PROVIDER` values force different chat-model factories and different keys by construction |
| 5. Planner output structure vs prompt | ✅ matches | Planner emitted `plan` array + `cross_clause_notes` per the planner_prompt.txt schema; not a flat edit list |

## Check 1 — Transcript env values

`src/redline/experiments/sprint-10O/transcript.txt` line 1 (verbatim):

```
=== Sprint 10O Phase 3 | planner=openrouter/openai/gpt-5.5 |
    executor=minimax/MiniMax-M2.7 | started 2026-04-26T07:41:19.151641+00:00 ===
```

Captured by `run.py`'s startup print (lines 215-217), which reads
`os.environ.get("OSCAR_LLM_REDLINE_PLANNER_{PROVIDER,MODEL}")` and
`OSCAR_LLM_REDLINE_EXECUTOR_{PROVIDER,MODEL}` after `load_dotenv()`
fires (line 65).

Cross-checked against `.env` on main:
- `OSCAR_LLM_REDLINE_PLANNER_PROVIDER=openrouter` ✅
- `OSCAR_LLM_REDLINE_PLANNER_MODEL=openai/gpt-5.5` ✅
- `OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER=minimax` ✅
- `OSCAR_LLM_REDLINE_EXECUTOR_MODEL=MiniMax-M2.7` ✅

Transcript env values match `.env`; both are what was intended in the
plan (planner = openai/gpt-5.5 non-Pro per Arturs's deliberate
choice; executor = MiniMax-M2.7 unchanged from 10N).

## Check 2 — OpenRouter API envelope `model` field — NOT IN ARTEFACTS

The captured `llm-output-planner.txt` and `llm-output-executor-NN-pX.txt`
files contain only the LangChain `AIMessage.content` value — the message
body the LLM returned. They do NOT contain the OpenRouter / MiniMax HTTP
response envelope, which would include the canonical `model` field that
names which model actually served the request.

`run.py:278` (planner):
```python
p_raw = p_reply.content if hasattr(p_reply, "content") else str(p_reply)
```

`run.py:344` (executor):
```python
e_raw = e_reply.content if hasattr(e_reply, "content") else str(e_reply)
```

Both extract `.content` only. The full LangChain reply object also carries
`response_metadata` and `additional_kwargs` which (depending on the
provider integration) typically hold the upstream envelope fields — but
we do not capture those.

**This is outcome (c) for the API-envelope dimension: cannot directly
verify from artefacts.** Provenance is established by other means (see
checks 3, 4, 5 below) but the canonical ground-truth field is not in
the captured data.

**Going-forward fix (proposal for future sprints, not 10O):** add a
diagnostic capture in `run.py` that writes `response_metadata` and
`additional_kwargs` alongside `content`:

```python
diag = {
    "content_len": len(p_raw),
    "response_metadata": getattr(p_reply, "response_metadata", None),
    "additional_kwargs": getattr(p_reply, "additional_kwargs", None),
}
(HERE / "llm-meta-planner.json").write_text(
    json.dumps(diag, default=str, indent=2), encoding="utf-8"
)
```

For OpenRouter calls this typically surfaces `response_metadata.model`
naming the actual upstream model (which can differ from the request
slug if OpenRouter route-renamed or version-pinned). For direct
MiniMax calls the metadata shape is provider-specific. This change is
a one-off in `run.py` and should land in 10P.

## Check 3 — Cross-check by output character

**Planner output (`llm-output-planner.txt`, 5,416 chars).** Reads as
analytical lawyer reasoning emitted by a frontier model. Characteristic
markers:

- Tight structured JSON with no markdown fence (GPT-5.5 sometimes wraps,
  sometimes doesn't; this run did not)
- `cross_clause_notes` contains lawyer prose with characteristic
  qualifications: *"I have not proposed cosmetic mutuality edits where
  the operative effect is already reciprocal"*; *"absent a broader
  commercial instruction"*; *"I have limited the mark-up to the partner's
  substantive asks and have not added speculative provisions such as
  injunctive relief, assignment restrictions, or notices machinery"*
- The mutuality judgement (cross_clause_notes[0]) reads as a
  considered position, not a checklist tick
- Preserve lists are properly populated with verbatim quotes (4-5
  preserve items per instruction); no instruction has empty preserve
  where preservation was substantively needed

This pattern matches the GPT-5 family's lawyer-mode output character
(considered prose, structured fields properly populated, qualifying
language) and does NOT match MiniMax's typical compact emission
character.

**Executor outputs (4 files, 785-1,537 chars).** Read as MiniMax-style
emissions:

- Executor 1 (p1, 1,537 chars): bare one-line JSON, no markdown fence
- Executor 2 (p2, 785 chars): wrapped in ```json``` markdown fence
- Executor 3 (p3, 1,073 chars): pretty-printed JSON multi-line
- Executor 4 (p4, 969 chars): bare one-line JSON, no markdown fence

The MIX of formats (bare vs fenced vs pretty-printed) within the same
prompt is characteristic of MiniMax's known output-format inconsistency
(documented in the 10N B1 vs B2 comparison — MiniMax B2 wrapped in
```json``` while MiniMax B1 emitted bare JSON for the same prompt
type). GPT-5 family is more consistent.

Each executor's `comment` field begins with `"Per planner instruction
pN — ..."` per the executor prompt's directive — both planner-side
(planner emitted IDs `p1`-`p4`) and executor-side (executor cited those
IDs back) confirms the planner-executor handoff worked correctly.

**Output character is consistent with intended routing.** No flag.

## Check 4 — API key routing

The chat_model factory routes by provider name to different concrete
factories:

`src/shared/llm/chat_model.py:55-71`:
```python
def _openrouter_factory(*, model: str, api_key: str) -> BaseChatModel:
    return init_chat_model(f"openrouter:{model}", api_key=api_key)

def _minimax_factory(*, model: str, api_key: str) -> BaseChatModel:
    return init_chat_model(
        f"openai:{model}",
        base_url=_MINIMAX_BASE_URL,  # https://api.minimax.io/v1
        api_key=api_key,
        extra_body={"reasoning_split": True},
    )

_FACTORIES: dict[str, _ChatModelFactory] = {
    "openrouter": _openrouter_factory,
    "minimax": _minimax_factory,
}
```

10O's planner triple has `_PROVIDER=openrouter` → routes to
`_openrouter_factory` → uses the OpenRouter key from
`OSCAR_LLM_REDLINE_PLANNER_API_KEY`, hits OpenRouter's API.

10O's executor triple has `_PROVIDER=minimax` → routes to
`_minimax_factory` → uses the MiniMax key from
`OSCAR_LLM_REDLINE_EXECUTOR_API_KEY`, hits `https://api.minimax.io/v1`
directly. This is NOT OpenRouter — it bypasses any OpenRouter routing
entirely.

**The two calls cannot share a key (different providers, different
endpoints).** The planner cannot accidentally be served by MiniMax and
vice versa, because the HTTP calls go to different hosts via different
factories that do not share configuration.

This is structurally tight. Even without the API envelope check, the
provider-routing layer makes mis-routing between OpenRouter and direct
MiniMax effectively impossible without code changes.

The remaining residual risk is on the OpenRouter side: OpenRouter could
internally route `openai/gpt-5.5` to a different upstream model
(version-pinned variant, fallback model under load, etc.). This is
where the API-envelope `model` field would be the ground truth — and
that's the gap from check 2.

## Check 5 — Planner output structure vs prompt

`planner_prompt.txt` specifies the schema:

```
{
  "plan": [{"id": "...", "clause": "...", "position": "...",
            "instruction": "...", "preserve": [...],
            "comment_for_partner": "...", "depends_on": [...]}],
  "cross_clause_notes": [...]
}
```

`parsed-plan.json` (parsed from `llm-output-planner.txt`):

```
4 instructions:
  p1 | clause='3' | preserve=4 item(s)
  p2 | clause='4' | preserve=5 item(s)
  p3 | clause='7' | preserve=4 item(s)
  p4 | clause='9' | preserve=1 item(s)

4 cross_clause_notes (lawyer-prose qualifications, not edit-list-shaped)
```

**Planner output structure matches the prompt schema exactly.** Each
instruction has `id`, `clause`, `position`, `instruction`, `preserve`
(populated), `comment_for_partner` (empty in this run), `depends_on`
(empty in this run, all instructions standalone). `cross_clause_notes`
contains 4 lawyer-prose entries documenting the planner's reasoning
about cross-document patterns.

**This is NOT a flat edit list (10N's MiniMax shape).** A
mis-routed-to-MiniMax planner would have produced
`{"changes": [...]}` per the data contract from 10N's user_prompt
that 10O does not include — but 10O's planner_prompt.txt asks for
the `plan`/`cross_clause_notes` schema, and that's what was returned.
The structural shape match confirms the planner read 10O's prompt
(not some cached 10N prompt) and produced output to its schema.

## Conclusion

**Outcome (a) by indirect evidence: both calls served by the intended
models.**

- Planner served by `openai/gpt-5.5` via OpenRouter (transcript env,
  output character, schema match, provider-routing tightness)
- Executor served by `MiniMax-M2.7` direct via api.minimax.io
  (transcript env, output character, provider-routing tightness)

**Outcome (c) on the API-envelope dimension only:** the canonical
OpenRouter `model` field is not captured in the artefacts, so we
cannot prove routing from the LangChain reply alone. This is a
methodological gap not specific to 10O — every prior sprint has the
same gap. Routing was confirmed by other means; the gap should be
closed in 10P by adding `response_metadata` capture in `run.py`.

**10O's substantive verdict is NOT provisional.** Routing is
sufficiently established by checks 1+3+4+5 — adding the API envelope
capture in 10P would tighten provenance for future sprints but does
not change the 10O finding.

## Action item for 10P

Add diagnostic capture for `response_metadata` and `additional_kwargs`
alongside `.content` in any new `run.py` (one-off ~5 LoC change).
Output `llm-meta-{planner,executor-N}.json` files alongside the
existing `llm-output-*.txt` files. This makes future routing
verification a one-step grep against the captured `response_metadata`
rather than a five-step indirect inference.
