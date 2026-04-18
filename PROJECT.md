# PROJECT.md — Oscar Enterprise

> This file describes WHAT Oscar is. See CLAUDE.md for HOW to write the code.
> Read both files before writing any code.
>
> This is a goal document. It describes the destination, not the path.
> Build decisions emerge stage by stage and are captured in ADRs as they are made.

## What Oscar Is

Oscar is an AI agent that automates large parts of in-house legal work — commercial transactions, company secretarial, privacy compliance, and more. Oscar is delivered as a service by law firms to their clients, with a dedicated VPS per client, fully isolated, governed by NVIDIA OpenShell. Each client's Oscar learns the client's preferences and house positions over time and becomes increasingly tailored to how that client wants legal work done.

Oscar is multi-capability. Capabilities are added in stages. They share a common foundation: the same agent harness, the same governance discipline, the same memory and audit principles. New capabilities slot in alongside existing ones rather than as separate products.

Oscar's first capability is **contract redlining**. Oscar reads contracts the way a commercial lawyer would — clause by clause, against the client's playbook, with an eye to commercial substance — and returns marked-up versions with native track changes. Subsequent capabilities are added as the work matures.

---

## One VPS, One Client, No Multi-Tenancy

Each client gets their own VPS. There is no multi-tenant architecture. No row-level security. No tenant_id columns. One database, one Oscar instance, one client.

This means:

- No tenant isolation logic in the application code
- No tenant context middleware
- No RLS policies
- Simple, direct database queries
- Complete isolation by infrastructure, not by code

Client-specific configuration lives in `oscar_config.yaml`, not in a tenants table.

---

## What Oscar Does

Oscar is a working legal team in software. It does the kinds of things a junior to mid-level in-house lawyer would do — read documents, propose changes, ask questions, generate outputs, learn what the client wants — across a growing range of capability areas.

Oscar communicates in plain English. No legalese unless the output is itself a legal document. Oscar leads with materiality (what matters, why), gives opinions where asked, and flags uncertainty rather than papering over it.

### Human Authority

Humans are always the final authority on Oscar's output. Oscar proposes, humans confirm. Oscar's confidence in its own outputs is always provisional until a human signs off.

### Audit

Every action Oscar takes is recorded — what changed, from what source, when, by whom. Append-only. Oscar's behaviour is inspectable end to end.

### Learning

Oscar learns from its clients over time. Preferences, house positions, drafting styles, walk-away thresholds — these accumulate through the natural course of work. Oscar does not autonomously rewrite its own knowledge; updates flow through human approval. The learning loop is the substantive differentiation: each client's Oscar becomes that client's Oscar.

---

## What Oscar Does NOT Do

- Provide legal advice on its own authority — Oscar is a tool used by solicitors
- Delete data (soft delete only)
- Modify its own code, prompts, or knowledge autonomously
- Send communications outside configured channels
- Make external API calls to anything not declared in its sandbox network policy

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.13 |
| Sandbox | NVIDIA OpenShell |
| Agent harness | Deep Agents on LangGraph |
| Database | PostgreSQL |
| LLM (runtime) | Model-agnostic via dependency injection |
| LLM (build) | Claude Code |
| Observability | LangSmith + OpenTelemetry |

Specific libraries within these layers (memory tools, channel adapters, document processing engines, etc.) are chosen per capability stage and captured in ADRs.

### LLM Policy

Oscar's runtime LLM is model-agnostic by design. Model choice is a dependency injection at startup, not hardcoded in agent code. Clients with sovereignty concerns can configure their own provider.

The build-time agents (Claude Code) are exempt from this policy — they are tools for humans, not part of Oscar's runtime.

### Model Allocation

Model choice is dependency injection, not hardcoded. The architectural principle:

- The orchestrator (General Counsel) uses the strongest available frontier reasoning model. Today that might be GPT-5.4 or Opus 4.7; tomorrow it will be whatever has superseded them. Orchestration is reasoning-heavy and relatively low-volume — spend the tokens here.
- Specialist agents that do the substantive work run on capable-but-cheaper models. In DEV that is MiniMax. In PROD it might be Sonnet or similar. The right choice per specialist depends on per-agent evaluation — some will need more capable models, others won't.
- No agent hardcodes its own model. Allocation lives in configuration and is injected at startup.

---

## Sandbox

Oscar's runtime runs inside an OpenShell sandbox. This is foundational, not optional. Network policy is default-deny. Every external endpoint Oscar talks to is explicitly allowed in policy YAML, with method-level enforcement where it matters. Policy YAML is version-controlled in the repo.

---

## Capability Stages

**Phase 1 (current): Contract redlining.** Oscar reads commercial contracts and returns redlined versions reflecting the client's playbook. Edits are returned as native Word track changes. The playbook learns from client conversations.

**Future phases** will be specified in this file as they are approached. Likely areas:

- Company secretarial
- Privacy compliance
- Transactional support (M&A, due diligence)
- Further areas as the in-house legal capability surface expands

The order in which future phases are tackled depends on what we learn from earlier ones, on commercial priorities, and on what client demand looks like as Oscar reaches market.

---

## Files in Project Root

| File | Purpose |
|------|---------|
| README.md | Brief project description |
| PROJECT.md | This file — what Oscar is; includes the Sprint Log |
| CLAUDE.md | Coding standards — governs how Oscar's code is written |
| oscar_config.yaml | Runtime configuration |
| .env.example | Template for required environment variables |
| policies/ | OpenShell policy YAMLs |
| docs/adr/ | Architecture Decision Records |
| src/ | Application source |
| tests/ | Test source |

Deployment-time exclusion of non-runtime files (PROJECT.md, CLAUDE.md, docs/adr/) is a build/package-time concern — handled via a deployignore or equivalent when SIT is stood up — not a reason to keep files outside git. Git is the durability mechanism; what ships to SIT is a later, separate concern.

---

## Sprint Log

> Append-only record of what has been built. Each sprint is a short, concrete piece of work with a single goal and a binary success criterion. Newest entries at the bottom. Read the most recent entry to know where the previous sprint left off.

### Sprint 0 — 2026-04-18 — Establish workflow

**Goal:** Establish the sprint discipline. Get sandbox-Claude-Code able to work with the repo (SSH access, git identity, clone). Initialise the sprint log.

**Done:** Sprint log created in PROJECT.md. Subsequent sprints appended below.

**Next sprint picks up from:** Sandbox is ready for sandbox-Claude-Code to clone the repo and start working.

### Sprint 1 — 2026-04-18 — Install LangGraph core

**Goal:** Create a Python 3.13 venv at `/sandbox/.venv` and install LangGraph core (`pip install langgraph`) with no extras, no companions, no pinning. Verify with an import + version print. Capture friction honestly.

**Done:** `langgraph 1.1.8` installed and importable inside the venv. Transitive companions that `langgraph` declares as hard deps came along (see versions below). Pip resolved cleanly — no policy denies. Functional check: `from langgraph.graph import StateGraph` imports; version `1.1.8` confirmed via `langgraph.version.__version__` and `importlib.metadata.version("langgraph")`.

**Installed (for reference, not pinned):**
- `langgraph 1.1.8`
- Companions pulled as hard deps of `langgraph`: `langchain-core 1.3.0`, `langgraph-checkpoint 4.0.2` (in-memory only — NOT the `-postgres` variant), `langgraph-prebuilt 1.0.10`, `langgraph-sdk 0.3.13`, `langsmith 0.7.32`
- Usual pydantic/httpx/anyio/tenacity/requests stack underneath

**Surprises, flagged honestly:**

1. **Sandbox state drift at sprint start.** `/sandbox/.venv` already existed with ~25 packages matching langgraph's dep tree (pydantic, httpx, orjson, cloudpickle, etc.) plus empty `langgraph/{cache,checkpoint,store}/` namespace dirs — but no `langgraph` dist-info. Fingerprint of a prior partial install that had been partially rolled back, leaving orphan namespace dirs. Wiped with `rm -rf /sandbox/.venv` and recreated with `uv venv --seed --python 3.13 /sandbox/.venv` so the install could be verified from a known-clean base.
2. **OpenShell does NOT ship LangGraph** (investigated because of #1). `/sandbox/reference/nvidia-openshell/pyproject.toml` declares only `cloudpickle`, `grpcio`, `protobuf` as Python deps. No langgraph/langchain/deepagents references anywhere in the OpenShell repo. The pre-seed was therefore not an OpenShell artefact.
3. **PyPI egress was already allowed.** The brief predicted `pip install` would hit a policy deny and need a mid-sprint host-Claude-Code intermission to widen policy. It didn't. `policies/oscar-dev.yaml` has a `pypi` network_policy block (lines ~186–209) allowing `pypi.org`, `files.pythonhosted.org`, `github.com`, `downloads.python.org` for `/sandbox/.venv/bin/pip|python` and `/usr/local/bin/uv` — present since the initial policy commit `4967830`. No host intermission was needed.
4. **The brief's verify one-liner is wrong for langgraph 1.1.8.** `python -c "import langgraph; print(langgraph.__version__)"` raises `AttributeError: module 'langgraph' has no attribute '__version__'` — not `ImportError`. Reason: langgraph 1.1.8 is a PEP 420 namespace package (`langgraph.__file__ is None`, top-level `dir(langgraph)` is empty). Version lives in `langgraph.version.__version__` — not re-exported at the top level. Future sprint briefs should use `python -c "from langgraph.version import __version__; print(__version__)"` or `importlib.metadata.version("langgraph")`. Functional intent of the criterion (langgraph is importable + version is known) passes.
5. **`pip install langgraph` is not as "core only" as the brief assumed.** The brief explicitly excluded `langgraph-checkpoint-postgres`, `langgraph-store-postgres`, `langchain-postgres`, LangMem, and Deep Agents — those weren't installed. But `langgraph-checkpoint` (base, in-memory), `langgraph-prebuilt`, `langgraph-sdk`, `langchain-core`, and `langsmith` ARE hard deps of `langgraph` itself (per `pip show langgraph: Requires: langchain-core, langgraph-checkpoint, langgraph-prebuilt, langgraph-sdk, pydantic, xxhash`) and came as part of the core install. Sprint 2+ can assume these are present; the Postgres variants, LangMem, and Deep Agents remain their own sprints.

**Next sprint picks up from:** Working `langgraph 1.1.8` install inside `/sandbox/.venv` (Python 3.13.12, uv 0.10.8). The venv is known-clean (recreated this sprint, not inherited). PyPI egress is confirmed working for future installs. No ADR was written this sprint — dependency installs within the already-declared framework stack (CLAUDE.md § Framework Stack) aren't architectural decisions. If a future sprint needs to deviate from that stack, that's when an ADR fires.

### Sprint 2 — 2026-04-18 — Minimal LangGraph runs

**Goal:** Prove langgraph 1.1.8 actually runs in the sandbox — not just imports. Build the smallest graph that exercises state, nodes, edges, compilation, and invocation. No LLM, no checkpointer, no tools, no Deep Agents, no Postgres.

**Done:** `src/experiments/sprint-02-langgraph-runs/hello_graph.py` runs and prints `{'message': 'greetings: hello world', 'counter': 11}` — matching the expected output documented in the file's docstring. An `assert result == expected` inside `main()` confirms exact equality. The graph is two nodes joined by linear edges (`START -> append_hello -> append_world -> END`) over a two-field TypedDict state; `append_hello` adds 1 to the counter and appends " hello", `append_world` adds 10 and appends " world", so the counter going 0 -> 11 and the message ordering are both independent witnesses that both nodes ran and ran in order.

**Surprises, flagged honestly:**

1. **`docs.langchain.com` is blocked by the sandbox network policy** — `WebFetch` on the LangGraph overview page returned HTTP 403. The `policies/oscar-dev.yaml` file has no block covering `docs.langchain.com`. Rather than widen policy mid-sprint for a sprint that explicitly doesn't need it, I worked from `/sandbox/.venv/lib/python3.13/site-packages/langgraph/` — which is the exact 1.1.8 source and therefore authoritative per CLAUDE.md's "Code outranks docs" rule. The brief said to read `docs.langchain.com` first; the spirit (version-matched reference) was honoured via the installed source. If a later sprint needs the hosted docs, a `langchain_docs` policy block (covering `docs.langchain.com`, `python.langchain.com`, and probably `api.python.langchain.com`) will need to be added.

2. **1.1.8's StateGraph signature has moved on.** Constructor is `StateGraph(state_schema, context_schema=None, *, input_schema=None, output_schema=None)`. The older `config_schema` kwarg is soft-deprecated (warns via `LangGraphDeprecatedSinceV10`, removed in v2.0.0) and superseded by `context_schema` for run-scoped context like `user_id`/`db_conn`. Older tutorials that pass `config_schema` still work but emit a deprecation warning. Not relevant for Sprint 2 (no context used), but worth knowing before Sprint 3 wires anything in.

3. **Node return semantics: overwrite, not merge.** A node returns `Partial<State>` — a dict of the keys it changed. Without a reducer, those keys **overwrite** the state; there is no automatic merge or accumulation. To accumulate (e.g. append to a list, sum across nodes) you annotate the state field with a reducer: `Annotated[list, reducer_fn]`. LangGraph ships `add_messages` as the canonical example for chat-message lists. This is documented in the `StateGraph` class docstring (source `graph/state.py` lines 115-184). Relevant when a future sprint has multiple nodes writing the same field.

**Source references relied on (since the hosted docs were unreachable):**

- `/sandbox/.venv/lib/python3.13/site-packages/langgraph/graph/__init__.py` — public API: `StateGraph`, `START`, `END`, `MessagesState`, `MessageGraph`, `add_messages`.
- `/sandbox/.venv/lib/python3.13/site-packages/langgraph/graph/state.py` — `StateGraph` class definition with canonical example in its docstring (lines 115-184); `add_node` (line 293), `add_edge` (line 788), `compile` (line 1038); `CompiledStateGraph` (line 1196).
- `/sandbox/.venv/lib/python3.13/site-packages/langgraph/constants.py` lines 28, 30 — `START = "__start__"`, `END = "__end__"` as interned strings.

**Next sprint picks up from:** Working minimal LangGraph in the repo at `src/experiments/sprint-02-langgraph-runs/hello_graph.py`. LangGraph 1.1.8 is confirmed functional end-to-end (import, compile, invoke, state threading, node ordering). `docs.langchain.com` remains policy-blocked; widen before any sprint whose brief depends on the hosted docs. No ADR written this sprint — nothing decided architecturally.

### Sprint 3 — 2026-04-18 — MiniMax LLM call from a LangGraph node

**Goal:** Prove an LLM call can round-trip from inside a LangGraph node in this sandbox. Build a minimal graph that takes a prompt, routes it through a node that calls MiniMax-M2.7, captures the response into state, returns. Wire the LLM call through a dependency-injection seam driven by `OSCAR_LLM_PROVIDER` / `OSCAR_LLM_MODEL` / `OSCAR_LLM_API_KEY` so future sprints can add providers by branch, not by rewriting the LLM-calling code.

**Done:** `src/experiments/sprint-03-minimax-call/hello_llm.py` runs end-to-end. The prompt `"Reply with exactly: ok"` round-trips through `MiniMax-M2.7` at `api.minimax.io/v1/chat/completions`; the returned content contains `ok`; the assertion passes; the script prints `sprint-03: MiniMax round-trip succeeded.` Two-node graph (`START -> call_llm -> present -> END`) over a two-field TypedDict state (`prompt`, `response`). The LLM is injected at build time — `build(llm: LLMClient)` — so the graph is agnostic to which provider is plugged in.

The DI seam landed at `src/llm/`:

- `src/llm/__init__.py` — `get_llm_client()` reads the three env vars and dispatches through a `_FACTORIES: dict[str, factory]`. Adding a provider is one dict entry plus one small factory function; callers untouched.
- `src/llm/minimax.py` — `MiniMaxClient` class with constructor-injected `model` and `api_key`; single public method `.complete(prompt) -> str` that POSTs to the OpenAI-compatible endpoint and unpacks `choices[0].message.content`. ~50 lines, raw `httpx`, no new dependency.
- `.env.example` at repo root documents the three required vars. `.gitignore` added covering `.env` + standard Python detritus. `.env` populated out-of-band; `git check-ignore` confirms it is not staged.
- ADR 008 records the library and endpoint choices (raw httpx vs langchain-community; OpenAI-compat vs native `/v1/text/chatcompletion_v2`).

**MiniMax endpoint used:** `POST https://api.minimax.io/v1/chat/completions` with `Authorization: Bearer <key>`, body `{"model": "MiniMax-M2.7", "messages": [{"role": "user", "content": "..."}]}`, response parsed at `data["choices"][0]["message"]["content"]`.

**Library chosen:** raw `httpx 0.28.1` (already installed as a langgraph transitive). Short-form rationale: the brief's preference ranking was `(1) maintained LangChain community integration, (2) official SDK, (3) raw httpx` — but `langchain-community.MiniMaxChat` fails the "and maintained" qualifier (stale `api.minimax.chat` host, stale `abab6.5-chat` default — issue [#29278](https://github.com/langchain-ai/langchain/issues/29278) closed as *not planned*). Raw httpx against the OpenAI-compat endpoint is the smallest thing that works and keeps the DI contract a plain `Callable[[str], str]`. Full rationale in ADR 008.

**Policy additions needed — and shipped:** a `minimax` block in `policies/oscar-dev.yaml` allowing `/sandbox/.venv/bin/python{,3}` (and `/app/.venv/...`, `/sandbox/.uv/python/**`, `/usr/bin/curl`) to reach `api.minimax.io:443`. Shipped by host-Claude-Code at commit `d931511` between the sandbox's first-attempt deny and the rerun. Live policy confirmed at v7.

**Actual prompt and response (verbatim):**

```
prompt:   Reply with exactly: ok
response: <think>
The user says: "Reply with exactly: ok". The user wants exactly "ok" as the reply. So we should output exactly "ok" (lowercase). There's no conflict with policy; it's a simple request. So we comply.
</think>

ok
```

**Surprises, flagged honestly:**

1. **MiniMax-M2.7 returns chain-of-thought inside `<think>...</think>` tags, inlined into `message.content`.** The OpenAI-compatible endpoint does not suppress it by default; the reasoning trace sits in the same string as the answer. Research noted `extra_body={"reasoning_split": True}` as the knob to split reasoning into a separate field — we did not use it this sprint because the integration test only asserted containment (`"ok" in response.lower()`) and adding knobs was out of scope. Any future sprint whose node consumes MiniMax output for structured purposes must either strip `<think>...</think>` or send `reasoning_split: True`, or the reasoning text will pollute downstream parsers.

2. **`langchain-community.MiniMaxChat` is not usable for M2 out of the box.** Issue [#29278](https://github.com/langchain-ai/langchain/issues/29278) reports stale defaults for `minimax_api_host` (still `api.minimax.chat` — wrong for M2) and `model` (`abab6.5-chat` — not M2); closed as *not planned*. Using it would have required overriding both plus installing `langchain-community`. Raw httpx was cheaper and better-aligned with the DI contract we wanted anyway.

3. **GroupId is required on the native endpoint, not on the OpenAI-compat endpoint.** MiniMax's native `/v1/text/chatcompletion_v2` needs `?GroupId=...`; `/v1/chat/completions` does not. This kept the DI contract model+api_key only — no `OSCAR_LLM_GROUP_ID`.

4. **The key prefix was `sk-cp-...`**, not MiniMax's own `sk-...` format (and characteristic of broker/proxy keys). It nonetheless authenticated against `api.minimax.io/v1/chat/completions`. Not investigated — worked, moved on. Flagging for future-us in case billing or rate-limit behaviour looks unusual and correlates with how the key was issued. (Subscription-capped at USD 20 per operator; Sprint 3's end-to-end exercised ~200 tokens total against that cap.)

5. **Sovereignty note now has a concrete anchor.** MiniMax is a Shanghai-operated provider; `api.minimax.io` is its global edge but the operating entity is PRC-domiciled. This is what the PROJECT.md § LLM Policy sovereignty clause was written for. The DI seam built this sprint means a client with PRC-exposure constraints changes three env vars — not code — once a second provider is wired.

6. **First-attempt policy deny was clean and diagnosable.** `httpx.ProxyError: 403 Forbidden` at the CONNECT stage, with the LangGraph wrapper correctly attributing it to `task with name 'call_llm'`. No bytes left the sandbox. Confirms the pattern from ADR 002/007 for future provider adds: try, capture the 403, write the policy block, rerun.

**Next sprint picks up from:** Working DI seam at `src/llm/` with one provider (MiniMax) wired end-to-end through a two-node LangGraph. The `_FACTORIES` dict in `src/llm/__init__.py` is the extension point; Sprint 4 is a natural fit for adding a second provider (OpenRouter or Anthropic-direct) to make the "adding a provider is just adding a branch" claim concrete under load, and for a test that swaps provider without changing graph code. Known follow-ups as they land: `<think>` / `reasoning_split` handling when a node consumes structured output (see surprise 1); provider-native tool-calling support when a sprint requires it (will likely need a richer per-provider client alongside the string-in/string-out seam, not a retrofit of it).

### Sprint 4 — 2026-04-18 — OpenRouter as a second provider

**Goal:** Make good on ADR 008's closing prediction that a second provider drops into the DI seam with "one dict entry plus one small factory function; callers unchanged." Add OpenRouter alongside MiniMax, widen the sandbox policy for `openrouter.ai:443`, and prove end-to-end by running Sprint 3's script verbatim with `OSCAR_LLM_PROVIDER=openrouter`.

**Done:** OpenRouter wired end-to-end through the same Sprint 3 two-node LangGraph with zero changes to the graph code. `OSCAR_LLM_PROVIDER=openrouter OSCAR_LLM_MODEL=openai/gpt-5.4 /sandbox/.venv/bin/python src/experiments/sprint-03-minimax-call/hello_llm.py` prints `response: ok` and the containment assertion passes. The `sprint-03: MiniMax round-trip succeeded.` tail is a string literal in the Sprint 3 script — left unchanged; Sprint 3's integration test is what ran, provider-swapped. The DI claim is now concrete: graph code is provider-agnostic, provider is a runtime choice, swapping it touches three env vars and nothing in `src/experiments/`.

Files changed:

- `src/llm/openrouter.py` — new. `OpenRouterClient(*, model, api_key)` with `.complete(prompt) -> str` mirroring `MiniMaxClient`: POSTs to `https://openrouter.ai/api/v1/chat/completions`, unpacks `choices[0].message.content`. Same raw-httpx pattern and same failure-mode RuntimeError as MiniMax.
- `src/llm/__init__.py` — one `_openrouter_factory` function, one entry in `_FACTORIES`. No other call sites touched.
- `.env.example` — `OSCAR_LLM_PROVIDER` supported list now `minimax, openrouter`; model-hint line documents OpenRouter's `<vendor>/<model>` identifier form (e.g. `openai/gpt-5.4`, `anthropic/claude-3.5-sonnet`).
- `policies/oscar-dev.yaml` — new `openrouter` block allowing the same binaries as the `minimax` block to reach `openrouter.ai:443`.

**Mid-sprint host-Claude-Code intermission (expected):** the live policy at `/etc/openshell/policy.yaml` is owned by root and not writable from the sandbox. Sandbox-Claude shipped the YAML; host-Claude-Code applied it live (commit `a7b1f51`, live policy v8, hash `5a6a9e687192…`). Same pattern as Sprint 3 (commit `d931511`, policy v7) and consistent with ADR 002 + ADR 007. Host-Claude-Code also confirmed on its side that the v7 MiniMax block was not rolled back, so both providers are reachable from v8 concurrently.

**Surprises, flagged honestly:**

1. **OpenAI-compat was a non-event, which is the point.** The ADR 008 claim was that OpenRouter "drops into the same shape — same wire, different host." It did. `openrouter.py` is a near-carbon-copy of `minimax.py` with the URL constants changed; no reshaping of payloads, no auth-scheme shift, no response-parsing fork. One sprint was enough to make the seam's second plug a structural validation, not a design exercise. ADR 008 did not need revisiting.

2. **`openai/gpt-5.4` returned clean text, no inline reasoning trace.** In contrast to MiniMax-M2.7 (Sprint 3 surprise 1), the OpenAI-compat response from `openai/gpt-5.4` was a bare `"ok"` — no `<think>...</think>` wrapper around reasoning. Good news for downstream parsing when a node consumes structured output: the MiniMax `<think>`-stripping problem is MiniMax-specific, not a general OpenAI-compat quirk. Do not assume every provider through the seam will need reasoning-trace handling; it is per-provider.

3. **Sovereignty profile is genuinely different, and the abstraction level shifts.** MiniMax surfaces a single upstream (MiniMax-M2.7 running on MiniMax-operated PRC infrastructure). OpenRouter is a US-operated broker that fronts many upstreams — the data-residency decision now lives at *model* selection time, not *provider* selection time (e.g. `openai/*` lands on OpenAI, `anthropic/*` lands on Anthropic, `mistralai/*` routes to upstreams in different jurisdictions). Clients with residency constraints can no longer satisfy them by picking a provider; they must constrain the model slug. This is worth remembering before Sprint N tries to offer clients a single `OSCAR_LLM_PROVIDER=openrouter` catch-all — openrouter-as-provider is not sovereignty-equivalent to the set of its upstreams. The `OpenRouterClient` docstring and `.env.example` hint carry the note for future-us; PROJECT.md § LLM Policy may want to acknowledge the broker-vs-direct distinction once a second client reaches production configuration.

4. **`openai/gpt-5.4` worked as a raw slug with no headers, no HTTP-Referer, no X-Title.** OpenRouter documents optional headers (`HTTP-Referer`, `X-Title`) for attribution and some soft rate-limit behaviour; Sprint 4 sent neither and the request served cleanly at ~18 tokens round-trip. Acceptable for integration testing. Production configuration should probably set at least `HTTP-Referer` once a client-facing deployment is stood up, so OpenRouter's usage dashboard attributes calls to this workload rather than as anonymous — but that is configuration, not code, and out of scope here.

5. **Sprint 3's assertion tail leaks provider name.** `hello_llm.py` prints `sprint-03: MiniMax round-trip succeeded.` regardless of which provider actually served the request. Cosmetic — the integration semantics are "LLM round-trip through the DI seam," and the script's docstring + the containment assertion are provider-agnostic. Not worth editing the Sprint 3 artefact to genericise; flagging so future-us does not read a successful Sprint 4 run and think Sprint 3's MiniMax block somehow served it.

**Next sprint picks up from:** DI seam now has two providers (MiniMax, OpenRouter), each reachable from the sandbox with policy blocks live at v8. Provider swap via env-var is demonstrated and one-line-diff. The predicted follow-ups from Sprint 3 remain open (reasoning-trace handling for MiniMax when structured output arrives, provider-native tool-calling when a sprint requires it). The "broker vs. direct" sovereignty distinction raised in surprise 3 is parked; PROJECT.md § LLM Policy can acknowledge it when a second concrete client configuration forces the decision.

### Sprint 6 — 2026-04-18 — Deep Agents runs end-to-end

**Goal:** Substrate proof for Deep Agents in the sandbox. Install `deepagents`, build the smallest possible meaningful agent (one model, one trivial filesystem-touching tool, default system prompt), invoke it on a prompt that requires planning + filesystem use + the trivial tool, and confirm everything works. Pin all transitive deps. No General Counsel, no department roles, no sub-agents, no Adeu — substrate, not application. Equivalent to Sprint 2 (LangGraph runs) and Sprint 3 (LLM call round-trips), one layer up.

**Done:** `src/experiments/sprint-06-deep-agents-runs/hello_deep_agent.py` runs end-to-end against `openai/gpt-5.4` via OpenRouter and prints `sprint-06: Deep Agents end-to-end run succeeded.` Tail of the trace: `slugify` (custom) fired 3×; built-in `write_file` fired 3×, `ls` 1×, `read_file` 1×; built-in `write_todos` (planning) fired 6× (one initial plan, five status updates as steps completed); the model returned a coherent paragraph confirming all three slugs and the read-back. The agent state at end has three channels — `messages`, `files`, `todos` — and the `files` channel holds the three slug files written during the run, each with `encoding='utf-8'` and an ISO-8601 `modified_at`. All `assert`s in the script pass, including content equality on the three files and the tool-call count thresholds. `requirements.txt` now pins all 54 packages in `/sandbox/.venv` (deepagents 0.5.3, langchain 1.2.15, langgraph 1.1.8, langchain-openrouter 0.2.1, openrouter 0.9.1, plus all the langgraph-from-Sprint-1 + httpx-from-Sprint-3/4 transitives in one pass).

**Trivial tool chosen:** one `@tool`-decorated pure function — `slugify(text: str) -> str` — that lower-cases input and replaces non-alphanumerics with `-`. No I/O of its own; the agent uses it as a content producer and then routes the outputs through the built-in `write_file` / `ls` / `read_file` tools. Picked over a tool that itself touches the filesystem (the brief's other suggestion) because the goal was to *observe* the built-in filesystem tools firing — having the trivial tool wrap `StateBackend` would have buried that signal. One tool also kept the experiment to the literal "smallest possible" the brief asked for.

**Model wiring (ADR 009):** Deep Agents requires a tool-calling `BaseChatModel`; ADR 008's `Callable[[str], str]` seam doesn't satisfy that. Three bridging options were considered — wrap our existing `LLMClient` as a `BaseChatModel` subclass (loses tool calling, since our raw httpx clients are single-message string-in/string-out), use `langchain-openai`'s `ChatOpenAI` with a `base_url` override pointed at OpenRouter or MiniMax (works against any OpenAI-compat host but bypasses Deep Agents' built-in OpenRouter profile), or use `init_chat_model("openrouter:…")` via `langchain-openrouter` (fully native — Deep Agents' OpenRouter profile auto-injects HTTP-Referer/X-Title attribution kwargs, and `langchain-openrouter` supports tool calling). Picked option 3. Added a parallel BaseChatModel-shaped seam at `src/llm/chat_model.py` (`get_chat_model() -> BaseChatModel`) with the same `_FACTORIES: dict[str, factory]` dispatch pattern as the string seam in `src/llm/__init__.py`. Same env vars (`OSCAR_LLM_PROVIDER`, `OSCAR_LLM_MODEL`, `OSCAR_LLM_API_KEY`) drive both seams. Sprint-6 only wires the `openrouter` factory in the chat seam — MiniMax via this seam needs another factory and probably `langchain-openai` with a `base_url` override (no native `langchain-minimax` package exists), and is deferred until a sprint requires MiniMax for tool-calling work. ADR 009 records the decision in full.

**Filesystem backend in use:** `deepagents.backends.StateBackend` — the default when `create_deep_agent(... backend=None)`. Files live in the LangGraph agent state as the `files` channel, with a `dict-merge` reducer (`deepagents/middleware/filesystem.py` `_file_data_reducer`) that carries unchanged keys forward and supports per-key deletion. Reads and writes are routed through Pregel internals (`CONFIG_KEY_READ` / `CONFIG_KEY_SEND`) so updates queue as proper channel writes — they apply at node boundaries, not within the same superstep. Each `FileData` value is a dict shaped `{content: str, encoding: str, created_at: str, modified_at: str}` (file format `v2`, the default); the legacy `v1` format is `list[str]` lines. Files are ephemeral to the conversation thread — they persist across superstep boundaries within one `invoke()` but not across separate invocations unless a `Checkpointer` is configured (none was, this sprint).

**Default middleware stack as instantiated for our agent** (from `deepagents/graph.py:551-598`): `TodoListMiddleware`, `FilesystemMiddleware`, `SubAgentMiddleware` (with the auto-inserted general-purpose subagent — see surprise 3), `SummarizationMiddleware` (created via `create_summarization_middleware(model, backend)`), `PatchToolCallsMiddleware`, `AnthropicPromptCachingMiddleware` (no-op for non-Anthropic models). Memory and permissions are skipped because we passed neither `memory=` nor `permissions=`. The `task` tool is present in the toolset but our prompt does not invoke it.

**Where files actually live:** in the `files` channel of the agent state, accessible after `invoke()` returns as `result["files"]` — verified by reading the live state at the end of the experiment. Pre-population works the documented way (`agent.invoke({"messages": […], "files": {…}})`). No disk writes, no LangGraph store, no external persistence. `StateBackend.write` raises a clear `RuntimeError` with remediation hints if called outside a graph context (we did not hit this in normal flow).

**Whether and how `write_todos` fired:** initially didn't — when the prompt was a numbered 4-step task with no explicit planning instruction, `gpt-5.4` skipped `write_todos` entirely (in line with the tool's own description: *"Only use this tool if you think it will be helpful in staying organized. If the user's request is trivial and takes less than 3 steps, it is better to NOT use this tool"*). Once the prompt added a leading sentence — *"Plan your approach with write_todos before you start."* — the tool fired six times: once to lay out the five-step plan with the first step `in_progress`, then five status-update calls advancing items to `completed` as work progressed. Each `write_todos` call surfaces in the message trace as an `AIMessage tool_calls=write_todos(['todos'])` followed by a `ToolMessage name='write_todos'` echoing the new list. Final `todos` channel state preserved in `result["todos"]`. **Discovery worth keeping:** the planning machinery is wired correctly but model-discretionary. Future agents whose work genuinely benefits from explicit plan tracking should signal that in their system prompt — the `BASE_AGENT_PROMPT` (lines 50-91 of `deepagents/graph.py`) does not by itself push the model toward planning. We did not override the base prompt this sprint.

**Final response (verbatim):**

```
Created the three slugs in order as `hello-world`, `deep-agents-test`, and
`sprint-six`, saved them to `/slugs/1.txt`, `/slugs/2.txt`, and `/slugs/3.txt`,
and verified with `ls` that all three files exist in `/slugs/`. I also read
`/slugs/2.txt` back and confirmed its content is `deep-agents-test`, which
matches the second slug exactly.
```

**Surprises, flagged honestly:**

1. **The `.env` LLM key was a MiniMax key when Sprint 6 started — not OpenRouter.** Sprint 4 demonstrably ran `OSCAR_LLM_PROVIDER=openrouter` end-to-end, so a working OpenRouter key existed at the time, but `.env` was reverted to the MiniMax key after the Sprint 4 commit (no provenance in git — `.env` is git-ignored). First Deep-Agents invocation against `openrouter.ai/api/v1/chat/completions` returned `401 Missing Authentication header`. Diagnosed by reproducing with raw `httpx` against both endpoints — same key authenticated cleanly against `api.minimax.io/v1/chat/completions`, confirming the key was MiniMax-only and not OpenRouter (different broker issuance). Surfaced to the operator, received a fresh OpenRouter key (`sk-or-v1-…`), updated `.env` accordingly. **Lesson for future sprints**: `.env` state is *not* tracked in git, so each sprint should sanity-check the live key against the provider it's targeting before assuming continuity from the prior sprint.

2. **`langchain-openai` was installed during diagnosis, then uninstalled before pinning.** When option 1 (the OpenRouter key was the issue) wasn't yet diagnosed, the working hypothesis was that we'd need to pivot to MiniMax via `ChatOpenAI(base_url='https://api.minimax.io/v1', …)` — that path was tested (tool calling against MiniMax-M2.7 via OpenAI-compat works, with `<think>…</think>` in `content` and `tool_calls` correctly extracted). Once the OpenRouter key arrived and the original plan resumed, `langchain-openai` (and its unique transitives `openai`, `tiktoken`, `regex`, `tqdm`) were uninstalled to keep `requirements.txt` honest about what Sprint 6 actually exercised. **Carry-forward**: when a sprint needs MiniMax with tool calling, `langchain-openai` is the proven path; the chat seam will need a `_minimax_factory` that builds `ChatOpenAI` with `base_url='https://api.minimax.io/v1'`.

3. **`SubAgentMiddleware` is unconditional even with `subagents=None`.** `deepagents/graph.py:546-548` auto-inserts a general-purpose synchronous subagent if no entry named `general-purpose` is supplied. The `task` tool is therefore present in *every* Deep Agent's toolset, and a default sub-agent is reachable via it — there is no `subagents=False` switch. Our prompt did not invoke `task`, so behaviour was as if no subagents existed, but the wiring is always there. The brief's "sub-agents are out of scope" is enforced by *prompt design*, not by middleware exclusion. Future sprints that genuinely want a single-agent posture have to either accept the latent default subagent or explicitly construct the middleware stack without `SubAgentMiddleware` (more involved than `create_deep_agent`).

4. **`AnthropicPromptCachingMiddleware` is appended unconditionally** with `unsupported_model_behavior="ignore"` — it silently no-ops for OpenRouter / OpenAI / Google models. Confirmed: no errors, no observable side-effects in our trace. Worth knowing because middleware-stack diffs across providers will look identical at the surface even though the caching middleware is doing real work for Anthropic-routed models and nothing for others.

5. **LangSmith tracing did not error despite `LANGSMITH_API_KEY` being unset.** No `langsmith.Client(...)` failures, no warnings. The `langsmith` package opts in only when an API key is present (or `LANGCHAIN_TRACING_V2=true` is set with a key); silent skip is the default. Recorded against the brief's open question. If we want traces, we'll need a LangSmith account and an env-var widening — a separate sprint.

6. **`write_todos` is exposed as a `langchain.agents.middleware.todo` import, not a `deepagents` import.** The Deep Agents stack composes middleware *from* `langchain.agents.middleware` — `TodoListMiddleware`, `HumanInTheLoopMiddleware`, `SummarizationMiddleware` all live in langchain-core/langchain.agents now. Deep Agents adds the filesystem, sub-agent, summarization-with-backend, and patch-tool-calls layers on top. The substrate hierarchy is therefore *langchain.agents → deepagents middleware → user middleware → tail*; future ADRs should reference middleware by their actual module path, not by lineage assumption.

7. **The `init_chat_model("openrouter:…")` path constructs `langchain_openrouter.ChatOpenRouter`, which builds a custom `httpx.Client` with attribution headers as defaults**, then relies on the underlying `openrouter` SDK to inject the `Authorization` header per-request. We feared the custom client would clobber the auth header (a subtle bug shape), but per-request injection works correctly — verified by request-level header logging. Filed as a "watch-this-if-tracing-network-issues-later" note.

8. **`write_file` returns `Updated file /slugs/1.txt` even on first creation.** Cosmetic — the StateBackend treats first-write and subsequent overwrites the same way at the message-text level (the underlying record-keeping does distinguish via `created_at` vs `modified_at`). Not a bug; just unintuitive wording for a creation event.

9. **Tool calls were parallelised** — `slugify` × 3 came back in one `AIMessage`, `write_file` × 3 likewise. `gpt-5.4` via OpenRouter natively emits multi-tool-call messages and Deep Agents executes them in one round-trip; this is good for throughput but means the message trace has *fewer* hops than a "one tool per turn" agent. State observations should not assume one tool per AIMessage.

**Policy widenings needed:** none. `openrouter.ai:443` was already allowed (Sprint 4 commit `a7b1f51`, live policy v8). PyPI egress was already allowed (Sprint 1). `pip install deepagents` and `pip install langchain-openrouter` both completed cleanly without surfacing a CONNECT deny.

**ADR written this sprint:** ADR 009 — *Bridging Oscar's LLM DI Seam to Deep Agents' BaseChatModel Requirement*. Captures the three-option model-bridging analysis and the decision to add a parallel BaseChatModel-shaped seam at `src/llm/chat_model.py` (rather than wrapping the existing string seam or reaching for a generic `ChatOpenAI` base-URL override).

**`requirements.txt` now pins 54 packages** to the exact versions that worked today, capturing in one pass everything pulled in by Sprint 1 (`langgraph` core), Sprint 3/4 (`httpx` already a transitive), and Sprint 6 (`deepagents`, `langchain` umbrella, `langchain-openrouter`, `langchain-anthropic`, `langchain-google-genai`, plus their transitives — `anthropic`, `google-genai`, `google-auth`, `cryptography`, `cffi`, `wcmatch`, `bracex`, etc.). This is the first time the repo has a pinned dep manifest. Previous sprints (1, 3, 4) did not pin; this sprint's freeze captures their installs retrospectively at exactly the versions still in `/sandbox/.venv`. Reproducing the working state in a fresh venv is now `uv venv --seed --python 3.13 /sandbox/.venv && /sandbox/.venv/bin/pip install -r requirements.txt`.

**Next sprint picks up from:** working Deep Agents end-to-end inside the sandbox at `src/experiments/sprint-06-deep-agents-runs/hello_deep_agent.py`. The chat-model DI seam at `src/llm/chat_model.py` is wired for OpenRouter only; MiniMax-via-`ChatOpenAI` (with `base_url`) is the documented next factory. The middleware stack, planning channel, and `StateBackend` filesystem are now characterised — Sprint 7 onward can begin populating Oscar's organisational structure (General Counsel orchestrator, department heads, specialist sub-agents, functional tools) on top of this foundation. Open follow-ups: (a) `BASE_AGENT_PROMPT` does not by itself induce planning — agents whose work benefits from explicit plan-tracking should say so in their system prompt; (b) LangSmith tracing is silently disabled until we add a key + policy block — defer until a sprint actually wants traces; (c) the `task` tool / general-purpose subagent are always present; future single-agent designs need to either tolerate this or build a stack without `SubAgentMiddleware`; (d) `.env` is git-ignored, so per-provider key state should be sanity-checked at every sprint start (Sprint 6 lost ~15 minutes to a stale-key-from-prior-sprint surprise).

### Sprint 7 — 2026-04-18 — General Counsel + Head of Commercial routing scaffolding

**Numbering note.** The brief was titled "Sprint 6" and referred to the previous log entry as "Sprint 5". In fact, the sprint log skipped the Sprint 5 slot — the previous entry ("Deep Agents runs end-to-end") is labelled Sprint 6. ADR 009, `src/experiments/sprint-06-deep-agents-runs/`, and the `requirements.txt` freeze all reference that Sprint 6 by number and path, so retroactively renaming it to Sprint 5 would cascade into the code and historical record. Instead, this entry is called Sprint 7 — keeping historical artefacts stable and the log append-only. Future sprints are invited to continue from Sprint 8.

**Goal:** Begin building Oscar's in-house legal org chart on top of the Deep Agents substrate proven last sprint. Scope deliberately narrow: one General Counsel (orchestrator), one department head (Head of Commercial), one yes/no routing decision. Two test invocations exercise the routing pattern. Not a capability — the point is the routing pattern, not the answer quality. Per the brief, the ancestry is Sprint 5/6 (this sprint's framing) proving Deep Agents runs, and Sprint 7 proving the org-chart scaffolding routes.

**Done:** `src/experiments/sprint-07-gc-commercial-routing/gc_and_commercial.py` runs end-to-end and both test invocations produce the expected routing behaviour:

* **Invocation 1 ("NDA review")** — GC classified as commercial and delegated to Head of Commercial via the `task` tool (fired exactly once, with `subagent_type='head-of-commercial'` confirmed by probing the tool-call args). Head of Commercial returned a MiniMax-M2.7 response; GC synthesised a final reply asking for the NDA text. Trace has 4 messages: HumanMessage → AIMessage(task call) → ToolMessage(subagent output) → AIMessage(final synthesis).
* **Invocation 2 ("Companies House filing")** — GC classified as company-secretarial and replied "this department is not yet staffed" verbatim, no delegation, zero tool calls. Trace has 2 messages: HumanMessage → AIMessage(final).

Binary success criterion met: `task` fired once in invocation 1 and zero times in invocation 2; invocation 1's final response is a synthesis over the subagent's output; invocation 2 acknowledges the department is not staffed.

**Chat-model seam extension for MiniMax (ADR 011).** `src/llm/chat_model.py` gained a `_minimax_factory` using `init_chat_model("openai:MiniMax-M2.7", base_url="https://api.minimax.io/v1", api_key=...)` — the carry-forward from Sprint 6's "MiniMax via this seam needs another factory and probably `langchain-openai` with a `base_url` override (no native `langchain-minimax` package exists)". The seam's `get_chat_model()` signature also grew an `env_prefix=` keyword (default `OSCAR_LLM` for backward compat with Sprint 6's experiment) and a new pure-DI `build_chat_model(*, provider, model, api_key)` entry point. Same `_FACTORIES` dispatch pattern as before; adding a provider remains one dict entry plus one small factory.

Trivial verification — `get_chat_model(env_prefix="OSCAR_LLM_HEAD_OF_COMMERCIAL")` on `"Reply with exactly: ok"` returned (verbatim, including the `<think>` block):

```
<think>
The user says: "Reply with exactly: ok". This seems like a request for the assistant to output exactly the string "ok". This is a short request. There's no policy violation; it's trivial. The user wants the assistant to output exactly "ok". There's no problem. There's no hidden content. So we comply.

We must produce exactly "ok". Nothing else. So output "ok".
</think>

ok
```

The `<think>` wrapper is MiniMax-M2.7's standard OpenAI-compat behaviour (Sprint 3 surprise 1). Tool calling still works around it.

**The two agent definitions (brief summary):**

* **General Counsel** — `create_deep_agent(model=<OpenRouter GPT-5.4>, tools=[], system_prompt=GC_SYSTEM_PROMPT, subagents=[head_of_commercial])`. System prompt says: you are the GC of an in-house legal function; your job is to classify inbound work and delegate to the right department head via `task`; only `head-of-commercial` is staffed; for anything else reply "this department is not yet staffed" without delegating.
* **Head of Commercial** — a `SubAgent` dict with `name='head-of-commercial'`, `tools=[]`, `model=<MiniMax-M2.7 via the chat-model seam>`, and a system prompt describing the role as responsible for commercial contract work (NDAs, MSAs, SaaS, amendments) with instructions to respond with a short string describing what it would do rather than performing the work.

Model allocation rationale is in ADR 010 (per the brief's mandate): GC = frontier reasoning model (orchestration is reasoning-heavy and low-volume — spend tokens here), specialist = capable-but-cheaper (higher-volume, narrower-scope; cheaper models hold up at per-role eval), no agent hardcodes its own model, per-role env-var triples carry the DI injection. Two concrete prefixes this sprint: `OSCAR_LLM_GENERAL_COUNSEL_*` and `OSCAR_LLM_HEAD_OF_COMMERCIAL_*`. Future roles extend the same pattern.

**The two test invocations — verbatim outputs (captured from a second run for clean message numbering; LLM wording varies between runs, routing does not).**

*Invocation 1 — "Please review this NDA against our standard position":*

```
msg#0 HumanMessage
  Please review this NDA against our standard position

msg#1 AIMessage
  tool_call name='task'
  args={'description': "Review the user's NDA against our standard
  position. Identify key deviations from a typical company-friendly
  standard NDA position, flag material legal/commercial risks, and
  provide a concise issues list with recommended fallback positions
  and negotiation points. If the actual NDA text is not available in
  the prompt, state exactly what is needed from the user to perform
  the review and keep it minimal.",
        'subagent_type': 'head-of-commercial'}
  content: ""

msg#2 ToolMessage name='task'
  <think>
  The user is asking me to review an NDA (Non-Disclosure Agreement)
  against their standard position. However, I don't see any NDA text
  provided in the prompt. I need to check if there's a file path
  provided or if I need to ask for the actual NDA text.

  Let me look at what information I have:
  - The user wants me to review "the user's NDA" against "our
    standard position"
  - They want me to identify deviations, flag risks, and provide
    negotiation points

  But there's no NDA text provided and no file path given. I should
  ask the user to provide the NDA text or file path, but keep the
  request minimal as instructed.
  </think>

  To perform this NDA review, I need the following:

  1. **The counterparty's NDA** — please provide the file path or
     paste the text directly.
  2. **Your company's standard NDA template** — file path or text
     for comparison.

  Once you share these, I'll analyze deviations from your standard
  position, flag material risks, and provide an issues list with
  fallback positions and negotiation points.

msg#3 AIMessage (final)
  Please send:
  1. the NDA to review, and
  2. your standard NDA/template or playbook position.

  If you only have one of those, send that and I'll review against
  a typical market-standard fallback.
```

*Invocation 2 — "Please file our annual return at Companies House":*

```
msg#0 HumanMessage
  Please file our annual return at Companies House

msg#1 AIMessage (final)
  this department is not yet staffed
```

Tool-call counts:
* NDA invocation: `task: 1` (routing to `head-of-commercial` — confirmed via probe).
* Companies House invocation: no tool calls.

Assertions in `main()` pass: `task == 1` and `task == 0` for the two invocations; `"not yet staffed"` is in the Companies House final response. `sprint-07: routing scaffolding end-to-end run succeeded.`

**Routing verdict:** working as expected in both cases. Classification is decided by GPT-5.4 in the GC node; for the NDA, it selected the staffed `head-of-commercial` subagent; for the filing, it declined to delegate and returned the exact canonical refusal. No crossover — the GC never routed the Companies House request to a wrong department, and never refused the NDA.

**Surprises, flagged honestly:**

1. **`tools=[]` on a SubAgent does NOT mean no tools — it means no *extra* tools.** Head of Commercial still received the default middleware stack (TodoListMiddleware, FilesystemMiddleware, SubAgentMiddleware, SummarizationMiddleware, etc.) per the `SubAgent` spec's documented inheritance, so it had `write_todos`, `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, and (transitively) `task` available. Our system prompt said "you have no tools and no sub-agents" and MiniMax complied by not calling any — but the tools were reachable. This is the SubAgent-level instance of Sprint 6 surprise 3 ("`SubAgentMiddleware` is unconditional"): the middleware stack is baked in by `create_deep_agent` and only overridable by constructing a custom stack without those middlewares. For routing tests this doesn't matter; for future agents expected to be genuinely toolless, the enforcement is prompt-level, not framework-level.

2. **The brief said "short string, one or two sentences" — Head of Commercial produced a markdown-formatted multi-section response.** The system prompt requested brevity; MiniMax-M2.7 gave it structure anyway. Routing still worked. Future sprints that need terse sub-agent output will likely need either a tighter prompt, a ResponseFormat constraint (the `SubAgent` spec supports `response_format` for structured output), or both. Not worth polishing this sprint per brief's "No polish on the system prompts — short and directional is fine".

3. **MiniMax `<think>...</think>` blocks surface inside the `ToolMessage` content returned to GC.** GC's synthesiser ignored the `<think>` text in its final reply — it summarised around it correctly. But any downstream consumer of sub-agent outputs (e.g. an audit log, an automated test that compares ToolMessage content) will see the chain-of-thought inline. The `reasoning_split: True` knob noted in Sprint 3 surprise 1 is still the documented mitigation, still deferred.

4. **LLM non-determinism is visible between runs.** Two full runs of the same script produced different final wordings — `"Please paste the NDA text or upload the NDA file. Without the document, I can't review it against the standard position."` on one run vs. `"Please send: 1. the NDA to review, and 2. your standard NDA/template or playbook position. If you only have one of those, send that and I'll review against a typical market-standard fallback."` on another. The routing decision (task fires in invocation 1, doesn't in invocation 2) and the refusal string (invocation 2's "this department is not yet staffed") were stable across runs. Worth remembering when a future sprint wants to assert on exact wording — prefer routing-shape assertions.

5. **`subagent_type` dispatch is the routing mechanism, not a `route` arg or similar.** The `task` tool's schema includes `description` (free-text brief for the sub-agent) and `subagent_type` (which named subagent to dispatch to). GC picked `'head-of-commercial'` for the NDA — exactly the name we gave the SubAgent spec. If GC had called `task` with `subagent_type='general-purpose'` (the latent default), routing would have silently succeeded into the wrong subagent, and the sprint-success check would have passed (task == 1). The guard is prompt-level: the system prompt names the only staffed subagent. Future sprints with multiple staffed heads will need either more explicit prompt guidance or programmatic routing outside the LLM.

6. **No policy widenings needed.** `api.minimax.io:443` was already allowed (Sprint 3 commit `d931511`, live policy v7), `openrouter.ai:443` was already allowed (Sprint 4 commit `a7b1f51`, live policy v8), PyPI egress was already allowed (Sprint 1). `pip install langchain-openai` and its transitives (`openai`, `tiktoken`, `regex`, `tqdm`) completed cleanly. No 403 at any stage.

**ADRs written this sprint:**

* **ADR 010 — Per-Agent Model Allocation.** Frontier-at-the-top, capable-but-cheaper-below principle (from PROJECT.md § Model Allocation) given its first concrete implementation: GC = `openai/gpt-5.4` via OpenRouter, Head of Commercial = `MiniMax-M2.7` direct. Per-role env-var triples as the DI mechanism. Rejects single-triple and single-YAML alternatives with explicit revisit triggers.
* **ADR 011 — MiniMax in the BaseChatModel Seam via OpenAI-Compat `base_url` Override.** Resolves the "deferred" con in ADR 009's consequences. Uses `init_chat_model("openai:...", base_url="https://api.minimax.io/v1", api_key=...)` to stay consistent with the OpenRouter factory's construction entry point. `langchain-openai` is now a permanent dependency.

**`docs/secrets.md` created and populated.** Seeded with every env var the project currently expects, grouped by required/declared-but-unused/non-env; columns for purpose, required-for, introduced-sprint, last-touched-sprint. Maintenance rule: every sprint that adds/removes/materially-changes an env var updates the table in the same commit. Direct response to Sprint 6 surprise 1's complaint about silent `.env` drift.

**`.env.example` updated** to document the three triples (default + per-role) with inline pointers to `docs/secrets.md` and ADR 010 / ADR 011.

**`requirements.txt` re-frozen.** `langchain-openai 1.1.14`, `openai 2.32.0`, `tiktoken 0.12.0`, `regex 2026.4.4`, `tqdm 4.67.3` added (Sprint 6 had transiently installed them for diagnosis and uninstalled). File grew from 54 to 59 pinned packages. Fresh-venv reproduction command unchanged: `uv venv --seed --python 3.13 /sandbox/.venv && /sandbox/.venv/bin/pip install -r requirements.txt`.

**Next sprint picks up from:** a two-role GC+Commercial routing scaffold at `src/experiments/sprint-07-gc-commercial-routing/gc_and_commercial.py`, with per-role DI slots in `.env` and an updated chat-model seam supporting both OpenRouter and MiniMax. Natural directions: (a) stand up a second department head (Company Secretariat, Data Protection, Employment, Property, or Litigation) to stress the routing pattern with more than one staffed option; (b) introduce the first functional agent within Commercial (a document-operation agent — comment-responder, accept/reject reasoner, defined-terms auditor) to prove the within-department toolkit shape; (c) attach a real document (NDA + playbook) and see whether the routing still lands on Commercial and whether Commercial can produce anything useful. Open follow-ups carried over: (i) `<think>` reasoning-trace stripping for structured consumers (Sprint 3 surprise 1, still deferred); (ii) LangSmith tracing needs a key + policy block; (iii) the latent `task` tool / general-purpose subagent in every agent — including subagents — continues to require prompt-level enforcement for single-agent postures; (iv) sub-agent response brevity is hard to get from a short prompt alone — a `response_format` or tighter prompt scaffolding likely needed before the substantive capability sprints.

### Sprint 8 — 2026-04-18 — Clean MiniMax `<think>` pollution at the chat-model seam

**Goal:** Stop MiniMax-M2.7's chain-of-thought wrapper (`<think>...</think>`) from landing inline in sub-agent `ToolMessage.content` in the orchestrator's message history (Sprint 3 surprise 1 → Sprint 7 surprise 3). Primary mechanism: MiniMax's native `reasoning_split=True` parameter. Fallback (only if primary fails): tag stripping. Targeted fix at the seam, not a restructuring.

**Done:** Primary fix applied and verified. `src/llm/chat_model.py::_minimax_factory` now passes `extra_body={"reasoning_split": True}` to `init_chat_model`; the kwarg flows through `ChatOpenAI.extra_body` → OpenAI SDK `extra_body` → MiniMax HTTP payload; MiniMax returns `message.content` clean and `message.reasoning_details` separate; LangChain drops `reasoning_details` during message conversion; `AIMessage.content` is clean; Deep Agents' `task` tool picks up `.text.rstrip()` and builds a clean `ToolMessage`. Sprint 7's NDA re-run confirms: `contains <think> or </think>: False` in the ToolMessage returned to the General Counsel. Sprint 7's Companies House test is unchanged (no sub-agent called, so no seam traffic to fix).

---

**Research findings (pre-code note).**

*A — MiniMax `reasoning_split`:* per MiniMax's own docs (`platform.minimax.io/docs/guides/text-m2-function-call`, reached via WebSearch — the page itself was policy-blocked), setting `reasoning_split=True` on the request causes the response to split: `response.choices[0].message.content` holds the clean answer; `response.choices[0].message.reasoning_details[0]['text']` holds the thinking. MiniMax's own guidance recommends preserving the `<think>reasoning_content</think>` wrapper across multi-turn conversations to keep Interleaved Thinking coherent. **We are not implementing that preservation this sprint** — see "non-decision" below and ADR 012.

*B — LangChain / LangGraph message handling:*
- `extra_body` is a documented kwarg on `BaseChatOpenAI` (`langchain_openai/chat_models/base.py:795`), passed through in `_default_params` at line 1128 to the OpenAI SDK. `reasoning_split=True` therefore reaches MiniMax as expected.
- `_convert_dict_to_message` at line 188 only extracts `content`, `function_call`, `tool_calls`, `audio`. `reasoning_content` / `reasoning_details` are silently dropped (class docstring at line 574-576 is explicit: "Non-standard response fields added by third-party providers … are not extracted"). Multiple open LangChain issues track this (#35059 vLLM/DeepSeek, #35901 preservation proposal, #34706 o1/grok, #31326 reasoning_content). The LangChain PR #35530 noted in the brief as bringing `langchain-perplexity`'s tag-stripper to core was not merged into any module we have installed.
- `langchain-perplexity` is **not installed** in our venv (confirmed via directory listing of `/sandbox/.venv/lib/python3.13/site-packages/`); its tag-stripping output parser is unavailable by that path.

*C — Deep Agents sub-agent return flow:* read from installed source at `/sandbox/.venv/lib/python3.13/site-packages/deepagents/middleware/subagents.py`. The `task` tool's success path (`_return_command_with_state_update`, lines 374-402) does exactly one thing with content: line 396, `content = result["messages"][-1].text.rstrip() if result["messages"][-1].text else ""`, then line 401, `ToolMessage(content, tool_call_id=tool_call_id)`. No extraction, no stripping, no structured-field handling — just the last message's `.text`. This means **the fix must land before the sub-agent's last `AIMessage` is built** (i.e. at the chat-model seam) or the content will arrive polluted into the parent's history. A post-hoc fix after the task tool would require wrapping the task tool itself (more invasive, more surface area). The chat-model seam is the correct layer.

---

**Fix strategy applied: primary.** `reasoning_split=True` was the primary mechanism in the brief and it worked end-to-end. No fallback needed. The one-line change is:

```python
# src/llm/chat_model.py::_minimax_factory
return init_chat_model(
    f"openai:{model}",
    base_url=_MINIMAX_BASE_URL,
    api_key=api_key,
    extra_body={"reasoning_split": True},  # ← new
)
```

---

**Empirical verification — direct chat-model probe (post-fix).**

```text
CHAT MODEL: ChatOpenAI
extra_body: {'reasoning_split': True}
type: AIMessage
content: 'ok'
additional_kwargs keys: ['refusal']
response_metadata keys: ['token_usage', 'model_provider', 'model_name',
                         'system_fingerprint', 'id', 'finish_reason', 'logprobs']
```

Compare Sprint 7 verbatim for the same prompt (MiniMax chat-model seam direct verification):

```text
<think>
The user says: "Reply with exactly: ok". This seems like a request for the
assistant to output exactly the string "ok". This is a short request.
There's no policy violation; it's trivial. [...]
</think>

ok
```

`AIMessage.content` is now `'ok'`. `reasoning_details` is not surfaced on `additional_kwargs` (dropped by `_convert_dict_to_message`), which is what we expect and accept this sprint.

---

**Verbatim ToolMessage content — Sprint 7 NDA re-run, post-fix.**

```
**Document Missing**

No NDA text or file has been provided for review. To proceed, please upload or paste the NDA you would like me to analyse against our standard position. Once received, I will:

- Identify key deviations from our standard in-house NDA terms
- Flag legal and commercial risks
- Provide a concise issue list with recommended fallback positions
```

Programmatic check: `contains <think> or </think>: False`. Compare Sprint 7's verbatim pre-fix ToolMessage (PROJECT.md lines 377-403), which opened with a multi-paragraph `<think>...</think>` block before the user-facing content.

Routing assertions still pass: `task == 1` for NDA invocation, `task == 0` for Companies House invocation, `"not yet staffed"` present in the Companies House final response. Sprint 7's binary routing check is unchanged; Sprint 8's binary check (`<think>`-free ToolMessage) now also passes.

---

**Where the code change landed.** `src/llm/chat_model.py::_minimax_factory`, one new kwarg (`extra_body={"reasoning_split": True}`) on the `init_chat_model` call. The module docstring and the fallback note now reference ADR 012. Nothing else in the repo changed: no new files, no middleware, no post-processing, no dependency changes, no routing changes, no system-prompt changes, no policy changes. Fix radius is one line of behavioural code plus the ADR.

**Response shape produced by `reasoning_split=True` through the LangChain path:** `AIMessage.content` = clean string (e.g. `'ok'`); `AIMessage.additional_kwargs` = `{'refusal': None}` (no reasoning fields); `AIMessage.response_metadata` carries usage/model/finish_reason as before. MiniMax's `reasoning_details` field is dropped by `_convert_dict_to_message` before the `AIMessage` is constructed. This matches the research prediction.

---

**ADR written this sprint:** ADR 012 — *MiniMax `reasoning_split=True` via `extra_body`*. Captures the decision to enable `reasoning_split` at the factory, and the explicit non-decision on multi-turn `reasoning_details` preservation (what `reasoning_details` contains when populated, why we are discarding it today, and the three concrete changes that would be needed if a future sprint introduces multi-turn specialist conversations). Partially amends ADR 011 (whose Con #2 claimed `reasoning_split` was not reachable through `ChatOpenAI` — empirically, it is; the non-reachable thing is non-standard *response* fields, which LangChain drops by design).

---

**Surprises, flagged honestly:**

1. **`reasoning_details` preservation would need three separate plumbing changes, not one.** Research made clear that even if we did want multi-turn preservation, it is not a single-point extension of today's fix. LangChain drops the field at message-conversion time, Deep Agents' `task` tool only forwards `.text.rstrip()`, and the outgoing payload would need the `<think>...</think>` wrapper reconstructed from the split form (MiniMax expects the wrapper form on inbound, not the split form). ADR 012 records the three steps explicitly so a future sprint that needs this does not re-derive the plan.

2. **ADR 011's "not reachable" claim was wrong.** ADR 011 Con #2 said "MiniMax-specific features only exposed on the native endpoint (`reasoning_split`, MiniMax-native tool-call shape) are not reachable through `ChatOpenAI`." The `reasoning_split` half is wrong: `extra_body` makes provider-specific *request* parameters reachable. The tool-call-shape half is likely still correct (not tested this sprint — not needed). ADR 012 records the amendment; ADR 011 itself is append-only and stays as-is.

3. **Sprint 7 surprise 3's deferred fix was a one-line change.** Surprise 3 in Sprint 7's log framed `<think>` stripping as a follow-up likely to require either a `reasoning_split` knob or a stripping utility. It turned out to require neither stripping utility nor any kind of middleware — just the knob, passed through the documented `extra_body` channel. When a deferred surprise turns out to be one line of code, that is worth logging: future-us should prefer trying the native knob before reaching for post-processing.

4. **Brief's mention of `langchain-perplexity.output_parsers` / LangChain PR #35530 turned out to be moot in our venv.** Neither is installed; the PR is not merged into any module we have. The fallback plan's "use LangChain's existing utility if installed" branch was unreachable from the start. Not a problem — the primary path worked. Recorded because the brief treated the existence of an installed utility as plausible, and it wasn't.

**No policy widenings needed.** `api.minimax.io:443` already allowed (Sprint 3 policy v7). `platform.minimax.io` is not in the allow list and returned 403 on WebFetch — worked around by using WebSearch to retrieve the relevant information from the MiniMax docs page and from surfaced GitHub issues / vLLM recipes. Same pattern as Sprint 2's `docs.langchain.com` block. Not proposing to widen policy for a doc lookup we only needed once.

**No new dependencies.** `requirements.txt` unchanged (still 59 packages).

**Next sprint picks up from:** Sub-agent responses flowing through the MiniMax chat-model seam now land clean (no `<think>` pollution) in orchestrator history. The Sprint 7 scaffold is the starting point as before — its follow-up directions (second department head, first functional agent within Commercial, real document attachment) are all still open. Carry-forwards from Sprint 7 remain: (i) `<think>` handling is **resolved** for MiniMax via this sprint's primary fix; for multi-turn specialist conversations, ADR 012's three plumbing steps will be needed (deferred until a sprint requires it); (ii) LangSmith tracing still needs a key + policy block; (iii) the latent `task` tool / general-purpose subagent continues to require prompt-level enforcement for single-agent postures; (iv) sub-agent response brevity still hard to get from a short prompt alone — unchanged.

### Sprint 9 — 2026-04-18 — Accept/reject reasoner (first functional specialist under Head of Commercial)

**Goal:** Populate the Head of Commercial from Sprint 7 with its first *functional* agent — a specialist that takes a single proposed contract markup plus a playbook rule and returns `accept | reject | counter`. End-to-end routing: General Counsel → Head of Commercial → accept-reject-reasoner. First sprint in which Oscar does any legal work, even trivially. Rule GL-001 (Governing Law: England and Wales) is hardcoded in the specialist's system prompt; persistent playbook storage deferred. Three synthetic test invocations exercise the three decision paths.

**Done:** `src/experiments/sprint-09-accept-reject-specialist/gc_commercial_acceptreject.py` runs end-to-end. All three test invocations route through `head-of-commercial` (observed in GC's `task()` tool-call args), HOC delegates to `accept-reject-reasoner`, specialist returns structured JSON that parses to the expected decision, and GC synthesises a coherent user-facing response.

```
SPRINT 9 VERDICT
  accept-ew-unchanged    routed=True structured=True decision='accept'  (expected 'accept')  counter_language_ok=True  OK=True
  reject-delaware        routed=True structured=True decision='reject'  (expected 'reject')  counter_language_ok=True  OK=True
  counter-scotland       routed=True structured=True decision='counter' (expected 'counter') counter_language_ok=True  OK=True
sprint-09: accept/reject specialist end-to-end run succeeded.
```

---

**Research findings (pre-code — became ADRs 013, 014, 016).**

*A — Structured output from MiniMax through LangChain.* Three options were on the table: JSON-in-prompt, `ChatOpenAI.with_structured_output(..., method="json_schema")`, and `SubAgent.response_format = <Pydantic class>`. Empirical probe:

- `with_structured_output(..., method="json_schema")` **fails** against MiniMax via OpenAI-compat — `pydantic_core.ValidationError: Invalid JSON`, MiniMax returned freeform markdown when OpenAI's native `response_format={type: "json_schema"}` was in the request. MiniMax's OpenAI-compat shim does not enforce the json_schema contract.
- `with_structured_output(..., method="function_calling")` **succeeds** — binding the Pydantic class as a tool with tool_choice produces validated instances across all three Rule GL-001 test cases.
- Reading `langchain/agents/factory.py:499-539, 1199-1209`: `_supports_provider_strategy(model, tools)` returns `False` for MiniMax-M2.7 (no `profile.structured_output`, not in `FALLBACK_MODELS_WITH_STRUCTURED_OUTPUT = ["grok","gpt-5","gpt-4.1","gpt-4o","gpt-oss","o3-pro","o3-mini"]`). `AutoStrategy` auto-picks `ToolStrategy` — which is the function-calling path that works. No prompt-side JSON convention or manual retry wrapper required; `ToolStrategy.handle_errors=True` gives graceful retry on malformed tool calls out of the box.
- Decision shape: Pydantic `AcceptRejectDecision(decision: Literal['accept','reject','counter'], reason: str, counter_language: str = "")`. `counter_language` is a required string (empty when not counter) rather than `Optional[str]` — optional fields are not in the JSON schema's `required` list and MiniMax routinely omits them even when the prompt asks for them.
- ADR 013 records the choice.

*B — Deep Agents three-level delegation.* Read from installed source at `/sandbox/.venv/lib/python3.13/site-packages/deepagents/middleware/subagents.py:25-127`. The `SubAgent` TypedDict supports only `name`, `description`, `system_prompt`, `tools`, `model`, `middleware`, `interrupt_on`, `skills`, `permissions`, `response_format` — **no `subagents` field**. Flat-parent-with-many-children is what `SubAgent` encodes. But (`subagents.py:130-159`) `CompiledSubAgent` takes an arbitrary `runnable`, and `create_deep_agent(...)` returns a compiled `CompiledStateGraph`. So the nested shape is: build Head of Commercial with its own `create_deep_agent(subagents=[specialist_spec])`, then wrap the compiled graph as `{"name": "head-of-commercial", "description": "...", "runnable": hoc_graph}` when plugging into GC. `SubAgentMiddleware._get_subagents()` (`subagents.py:538-542`) preserves the `runnable` as-is. Arbitrary depth works by induction. ADR 014 records the pattern.

*C — Head of Commercial's specialist-routing prompt.* `SubAgentMiddleware` auto-appends "Available subagent types" to the system prompt (`subagents.py:522-524`), and the `TASK_SYSTEM_PROMPT` covers generic when-to-use-task guidance. The custom HOC prompt therefore only needs (1) role line, (2) routing table from input shape to specialist name, (3) relay instructions for the specialist's JSON back to the orchestrator. Naming the specialist by its `name` field (not its description) because `task` dispatches on `subagent_type`. ADR 016 records the pattern.

---

**Specialist definition (`accept-reject-reasoner`, brief summary).**

- **Model:** MiniMax-M2.7 (specialist tier, ADR 010), via `OSCAR_LLM_ACCEPT_REJECT_REASONER_*`.
- **Tools:** none beyond the default Deep Agents middleware stack.
- **Response format:** `AcceptRejectDecision` Pydantic BaseModel bound via `SubAgent["response_format"]`. `AutoStrategy` → `ToolStrategy` auto-selected (ADR 013). `ToolStrategy.handle_errors=True` retries on malformed tool calls.
- **System prompt (verbatim):** opens with an *output-discipline* preamble forcing exactly one tool call to the `AcceptRejectDecision` tool (no prose, no markdown fences), then encodes Rule GL-001 as a three-step ordered procedure covering accept / counter / reject paths. Full text in `gc_commercial_acceptreject.py:ACCEPT_REJECT_SYSTEM_PROMPT`.
- **Contract to the parent:** Deep Agents' `task` tool (`deepagents/middleware/subagents.py:386-393`) detects `structured_response` in the specialist's result state and serialises via `BaseModel.model_dump_json()` into the parent's `ToolMessage.content` — HOC's trace sees a raw JSON string when discipline holds.

---

**Revised Head of Commercial system prompt (verbatim).**

```
You are the Head of Commercial in an in-house legal function. You are responsible for commercial contract work — NDAs, MSAs, SaaS agreements, procurement contracts, amendments, and similar.

Staffed specialists under you (subagent names to use with the `task` tool):
  - accept-reject-reasoner: decides accept / reject / counter on a single proposed contract markup against a playbook rule. Returns a structured JSON decision. Use this whenever an inbound task describes any counterparty position on a contract clause (including "accepted unchanged", "proposed change to X", or "struck through") and a playbook rule applies.

Routing rules (follow strictly):
  1. If the inbound task contains BOTH (a) a description of the counterparty's position on a single contract clause — whether that position is a proposed change, an acceptance, or a rejection — AND (b) a playbook rule that governs that clause type, you MUST delegate to `accept-reject-reasoner` via the `task` tool. Pass the markup description and the rule to the specialist verbatim; do not paraphrase either. Do not try to decide yourself. "Accepted unchanged" and "no change" still count as a counterparty position — delegate anyway.
  2. Only if there is no markup description at all, or no rule to apply, respond plainly (one or two sentences) describing what you would do. Do not attempt to perform the work yourself. No other specialists are staffed this sprint.

When `accept-reject-reasoner` returns a structured decision (JSON with `decision`, `reason`, and `counter_language`), relay it back to the General Counsel in plain English. State the decision, include the reason, and include the `counter_language` verbatim when the decision is "counter". Do not invent extra context; the specialist's decision is the answer.
```

Sprint 7's HOC prompt said "you have no tools and no sub-agents" — removed. The routing-rule item (1) had to be re-tightened once mid-sprint to force delegation on the "accepted unchanged" edge case (see Surprise 1 below) — hence the explicit *"accepted unchanged / no change still count as a counterparty position — delegate anyway"* clause.

---

**The three test invocations — verbatim outputs (full run captured from `/tmp/sprint-09-run-4.log`; LLM wording varies between runs, routing and decision fields are stable).**

*Invocation 1 — "accept-ew-unchanged" (edge case — counterparty confirming, not changing).*

Prompt (verbatim, one line): *Please review this contract markup against our playbook. Rule GL-001 (Governing Law): the client's position is that governing law must be England and Wales. Any counterparty proposal to change governing law should be rejected unless the counter-proposal is to Scotland, Northern Ireland, or Ireland (in which case counter-propose England and Wales with a brief justification). Markup: the counterparty has accepted our proposed governing law of England and Wales without change.*

GC three-level trace summary:
```
1. HumanMessage
2. AIMessage tool_calls=task(['description','subagent_type'='head-of-commercial'])
3. ToolMessage name='task' <HOC's prose wrap of the specialist's decision>
4. AIMessage (final synthesis to user)
```

Specialist structured output (verbatim, from HOC-direct probe):
```json
{"decision":"accept","reason":"The counterparty has accepted England and Wales as the governing law, which aligns with the client's position.","counter_language":""}
```

Final user-facing response (verbatim):
```
Accept. Counterparty accepted England and Wales unchanged, which is fully compliant with GL-001.

Suggested response language: No response needed — the clause stands as proposed.
```

*Invocation 2 — "reject-delaware" (main test of the reject path).*

Prompt: as above with markup replaced by *the counterparty wants to change governing law from England and Wales to Delaware.*

GC trace summary: identical shape — one `task` call to `head-of-commercial`, one prose ToolMessage back, one AIMessage final.

Specialist structured output (verbatim):
```json
{"decision":"reject","reason":"Delaware is not an acceptable jurisdiction under GL-001; the client requires governing law to be England and Wales.","counter_language":""}
```

Final user-facing response (verbatim):
```
Reject.

Rationale: under GL-001, governing law must remain England and Wales. A change to Delaware is outside the permitted exceptions, so it should be rejected rather than counter-proposed.

Suggested response to counterparty:
> Thank you for your proposal. Unfortunately, we are unable to accept Delaware as the governing law. Our position is that the agreement must remain governed by the laws of England and Wales. Please revert the clause accordingly.
```

*Invocation 3 — "counter-scotland" (tests the counter path + `counter_language` generation).*

Prompt: *…Markup: the counterparty wants to change governing law from England and Wales to Scotland.*

GC trace summary: identical shape.

Specialist structured output (verbatim):
```json
{"decision":"counter","reason":"The counterparty proposes Scotland, which is on the acceptable shortlist, so we counter-propose England and Wales as the governing law.","counter_language":"The governing law shall be England and Wales, as this jurisdiction provides certainty and familiarity for both parties and aligns with our standard contractual framework."}
```

Final user-facing response (verbatim):
```
Counter.

Rationale: under GL-001, Scotland falls within the exception set where we do not outright reject, but we still counter-propose England and Wales.

Suggested markup response:
"We maintain our position that governing law should be England and Wales, as this provides the certainty and legal framework our client requires."
```

All three decisions match expected outcomes and reasoning is coherent. The GC-level final response in each case names the right decision and surfaces a usable counterparty reply (empty for accept, fresh language for reject and counter). The specialist's JSON parses cleanly in all three cases and `counter_language` is non-empty only on the counter case.

---

**Iteration history — what took more than one pass.**

The sprint budgeted ≤2 iterations on prompts if the specialist was unreliable. Two iterations were spent:

* *Iteration 1 — initial HOC + specialist prompts.* First three-level run: routing, reject and counter ended correctly; the accept case didn't reach the specialist because HOC reinterpreted "counterparty accepted unchanged" as "no markup to decide on" and answered itself. (Strictly defensible — there is no markup in the narrow sense — but the brief explicitly names this as a test case and expects the specialist to return "accept".)
* *Iteration 2 — HOC routing rule tightened to "delegate whenever a counterparty position + applicable rule is present, including 'accepted unchanged'".* Accept case now delegates; specialist returns "accept". Plus a specialist-prompt preamble demanding exactly one `AcceptRejectDecision` tool call (no prose, no markdown fences) to tighten the structured-output discipline observed as intermittent in the first run — see Surprise 2 below.

Two consecutive green runs after iteration 2 (`/tmp/sprint-09-run-4.log`, `/tmp/sprint-09-run-5.log`). Iteration budget exhausted — any further prompt-side fragility is a finding, not a fix.

A third change landed mid-sprint but it is a *harness* fix, not a model-side iteration — so not counted against the budget: the JSON extractor was made tolerant of MiniMax's intermittent markdown-code-fence wrapping. More on that in Surprise 2.

---

**Surprises, flagged honestly.**

1. **HOC's first-pass routing was semantically conservative.** On the accept edge case, HOC initially decided that "counterparty accepted unchanged" was not a markup in the narrow sense and so answered itself without delegating to the specialist. The brief expected delegation plus a specialist "accept" decision. Iteration 2's prompt expansion — explicit list of counterparty-position shapes that *do* trigger delegation, including "accepted unchanged" — fixed it. Carry-forward: department-head prompts should spell out ambiguous input shapes rather than rely on the model's natural-language intuition; orchestration is a decision layer, not a judgment layer.

2. **MiniMax's tool-call discipline for forced-structured-output is ~67% on our first-iteration prompt, driven to 100% across two trials by an explicit output-discipline preamble.** `ToolStrategy` binds the schema tool with `tool_choice="any"` (`langchain/agents/factory.py:1251`), forcing a tool call. MiniMax's OpenAI-compat shim honours this unreliably: on one of three first-iteration runs (Delaware case, run-3 log), the specialist emitted `AIMessage` prose wrapping the decision in ` ```json … ``` ` markdown code fences instead of calling the structured-output tool — so the specialist's result state had no `structured_response`, and Deep Agents' `task` tool fell through to `result["messages"][-1].text.rstrip()` (`subagents.py:396`). The fenced prose was well-formed JSON but flowed through the "no structured output" channel. Iteration 2's preamble ("Your ONLY output channel is a single tool call to the `AcceptRejectDecision` tool. Do not write prose. Do not wrap the JSON in markdown code fences. Emit exactly one tool call and nothing else.") moved runs 4 and 5 to 3-of-3 clean structured-response channel. This is a MiniMax/OpenAI-compat idiosyncrasy — not inherent to the ToolStrategy path — and the JSON extractor in the test harness now accepts both channels belt-and-braces. Carry-forward: the minute specialists get more numerous or rules less step-by-step, this is a candidate for a defensive middleware that falls back to fence-stripped parsing automatically, or a hard switch to a more tool-calling-disciplined specialist model.

3. **`SubAgent` has no `subagents` field; `CompiledSubAgent` is the documented escape hatch for nesting.** From `deepagents/middleware/subagents.py:25-127` (source of truth, CLAUDE.md's "code outranks docs"): the `SubAgent` TypedDict lists nine fields; `subagents` is not one of them. Nesting is therefore "build each non-leaf agent as its own `create_deep_agent(...)` graph and plug the compiled runnable in as `CompiledSubAgent`" (ADR 014). The sprint reached this via reading the source before wiring. Future sprints wanting an org-chart branch deeper than three levels extend the same pattern by induction. Minor caveat (from `graph.py:388-392` docstring): `CompiledSubAgent` does not inherit the parent's `interrupt_on` — HITL has to be configured at every compile site. Not a Sprint 9 concern; flagged for when HITL lands.

4. **The `task` tool's structured-response path only fires for the specialist immediately above it — it does not propagate up the tree.** `SubAgentMiddleware._return_command_with_state_update` (`subagents.py:386-402`) detects `structured_response` and serialises to the parent's `ToolMessage.content`, but the `_EXCLUDED_STATE_KEYS = {"messages","todos","structured_response",...}` block strips `structured_response` from the parent's own state before it propagates further. So at GC level the specialist's JSON is not in `result["structured_response"]`; only HOC's prose wrap is in `ToolMessage.content`. To audit the specialist's JSON, you either (a) invoke HOC directly as a second pass (what the test harness does), (b) give HOC its own `response_format` to preserve the shape (noted in ADR 016 as rejected for this sprint — preserves the JSON contract across levels but forecloses HOC's future role of composing multi-specialist decisions in prose), or (c) write a custom middleware that tees the intermediate state. For Sprint 9's scope, (a) is the simplest diagnostic.

5. **Auto-inserted general-purpose subagents at every nesting level (Sprint 6 surprise 3, now multiplied by three).** GC, HOC, and the accept-reject-reasoner each have a latent `general-purpose` subagent in their tool surface because `create_deep_agent` auto-inserts it when no entry named `general-purpose` is present (`graph.py:546-548`). Three latent subagents across the tree. Enforcement is still prompt-level: each agent's system prompt names only the specialists it should call. No test invocation this sprint tripped on this, but the structural fact should be called out before someone builds a four-or-five-level tree and spends time chasing "why is a general-purpose subagent firing".

6. **LangSmith tracing remains silent — still no key, still no policy block.** Carry-forward from Sprint 6 unchanged. Three-level traces are more verbose than Sprint 7's two-level ones, but the local message-trace dump in the experiment script is enough for Sprint 9; the helper documented in the brief turned out not to be needed — pretty-printing a subset of message kinds covered it.

7. **No policy widenings.** `api.minimax.io:443` allowed since Sprint 3, `openrouter.ai:443` since Sprint 4, PyPI since Sprint 1. No new hosts touched this sprint. `requirements.txt` unchanged (still 59 packages).

---

**ADRs written this sprint (at the moment of decision).**

- **ADR 013 — Structured Output from Specialist Sub-agents via Pydantic + ToolStrategy.** Pydantic class on `SubAgent["response_format"]`; AutoStrategy auto-selects ToolStrategy because MiniMax is absent from LangChain's provider-strategy allow lists; `task` tool serialises via `model_dump_json()`. `counter_language` is required-string-with-empty-default to stay in the JSON schema's `required` list.
- **ADR 014 — Three-Level Delegation via `CompiledSubAgent`.** `SubAgent` lacks a `subagents` field; `CompiledSubAgent` is the documented mechanism for plugging an arbitrary compiled graph (including a nested Deep Agent) under the `task` tool.
- **ADR 015 — Playbook Rule Hardcoded in the Specialist's System Prompt (Sprint 9).** Rule GL-001 lives inline in the specialist's prompt. No registry, no YAML, no placeholder Postgres table. Forward trigger: first sprint that needs multi-rule reasoning or human-editable rules supersedes this ADR.
- **ADR 016 — Head of Commercial's Specialist-Routing Prompt Pattern.** Three-part pattern (role, routing table, relay instructions) layered on what `SubAgentMiddleware` already auto-injects. Explicit input-shape-to-specialist mapping rather than letting the LLM infer from descriptions.

---

**Secrets / env:** three new env vars this sprint (`OSCAR_LLM_ACCEPT_REJECT_REASONER_PROVIDER`, `_MODEL`, `_API_KEY`) added to `.env.example` and `docs/secrets.md`. Typically reuse the same MiniMax provider/key as Head of Commercial; kept separate so per-specialist reallocation stays a config-only change (ADR 010).

**No new dependencies.** `requirements.txt` unchanged. No policy widening.

---

**Next sprint picks up from:** a working three-level org chart (GC → HOC → accept-reject-reasoner) with one functional specialist exercising accept/reject/counter against one playbook rule. Natural directions:

(a) *Second functional specialist under HOC* — comment-responder, fresh-language drafter, or defined-terms auditor. Same `SubAgent`-with-`response_format` pattern (ADR 013), extending HOC's routing prompt (ADR 016) with one more entry.
(b) *Second playbook rule for accept-reject-reasoner* — triggers ADR 015's supersede (multi-rule specialist prompts get unwieldy; time to introduce rule-as-data).
(c) *Persistent playbook storage* — Postgres table or YAML-in-repo for rules. Turns rules into human-editable, versioned data. Partners with (b).
(d) *Real document input* — attach a short NDA plus the rule and see whether HOC can isolate the governing-law clause and route it, or whether a document-parsing layer needs to land first.

Carry-forwards explicitly open: (i) structured-output reliability on MiniMax — prompt-level discipline is 3/3 across two runs with the iteration-2 preamble, but Surprise 2's fallback path is still the right defensive posture when specialist count grows; (ii) `reasoning_details` multi-turn preservation (ADR 012) — still deferred, no sprint yet needs it; (iii) LangSmith tracing still off; (iv) HITL not wired — if needed, `CompiledSubAgent` won't inherit parent `interrupt_on`, so configure per level (ADR 014); (v) the three latent `general-purpose` subagents continue to require prompt-level enforcement.
