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
