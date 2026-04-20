# TODO.md

Items we've deferred, flagged for later, or identified as worth revisiting. Each item has a trigger — a specific condition or event that should prompt return. Not a backlog; persistent context that spans sprints.

## Architectural decisions

1. **Multi-turn `reasoning_details` preservation for MiniMax specialists.** ADR 012 records a three-step plumbing plan (LangChain message-conversion extension, task-tool forwarding, `<think>`-wrapper reconstruction) explicitly deferred; today's fix discards the split field.
   - Trigger: first sprint that wires a multi-turn specialist conversation where chain-of-thought continuity matters.
   - Source: Sprint 8; ADR 012.

2. **Supersede ADR 015 — move playbook rules from inline system-prompt text to a registry.** Rule GL-001 lives hardcoded in `accept-reject-reasoner`'s prompt; multi-rule prompts become unwieldy.
   - Trigger: second playbook rule, or first request for a human-editable rule.
   - Source: Sprint 9; ADR 015.

3. **Persistent playbook storage layer (Postgres table or YAML-in-repo).** Partner decision to the ADR 015 supersede — turns rules into versioned, human-editable data.
   - Trigger: once ADR 015 is superseded.
   - Source: Sprint 9 next-sprint direction (c).

4. **HITL (`interrupt_on`) per-compile-site configuration pattern.** `CompiledSubAgent` does not inherit the parent's `interrupt_on`; every nested Deep Agent must configure HITL at its own compile site.
   - Trigger: first sprint that wires human-in-the-loop interrupts.
   - Source: Sprint 9 surprise 3; ADR 014 (caveat in `graph.py:388-392` docstring).

5. **Latent `general-purpose` subagent at every nesting level.** Currently three in the GC→HOC→specialist tree; enforcement is prompt-only. Building an agent without `SubAgentMiddleware` requires hand-constructing the middleware stack (no `subagents=False` switch).
   - Trigger: a routing incident where a GC/HOC/specialist delegates to `general-purpose`, OR a four-level tree compounds the surface.
   - Source: Sprint 6 surprise 3; Sprint 7 surprise 1; Sprint 9 surprise 5.

6. **Default Deep Agents filesystem tools contaminate restricted-tool specialists.** `SubAgentMiddleware` appends `ls`, `read_file`, `write_file`, etc. regardless of the specialist's declared `tools=[...]`. OPERATING DISCIPLINE's "no filesystem access" line is prompt-level fiction — the tools exist and can be called (they just return empty / misleading results when the `.docx` isn't on disk where they look). Options: (a) prune the middleware's default tool injection (policy-level choice, may break planning elsewhere); (b) rewrite the preamble to match reality.
   - Trigger: second specialist exhibits the same confusion, OR an architectural requirement for strict tool restriction lands.
   - Source: Sprint 10G surprise 4, carry-forward (iv).

7. **Acknowledge broker-vs-direct sovereignty distinction in PROJECT.md § LLM Policy.** OpenRouter is a US broker fronting many upstreams — data-residency decisions move from provider-choice to model-slug-choice. Currently in `OpenRouterClient` docstring and `.env.example` only.
   - Trigger: second concrete client configuration that forces a residency decision, OR first client with PRC/EU/UK residency constraint.
   - Source: Sprint 4 surprise 3.

8. **HOC output-envelope hardening.** HOC currently paraphrases specialist output with occasional hallucinated bridging sentences. Options: tighten "relay verbatim" rule, OR have specialists return a JSON envelope (`status`, `output_path`, `summary`) that HOC reads literally.
   - Trigger: paraphrasing visibly bites in a user-facing context, OR a sprint that needs structured specialist output at GC level.
   - Source: Sprint 10D surprise 3, carry-forward (iii); Sprint 10E carry-forward (i); Sprint 10F (i); Sprint 10G carry-forward (i).

9. **Identification vs. execution — model-tier design space.** 10F showed MiniMax can identify clause-level but cannot decompose span-level. 10G falsified the planning-absence hypothesis: decomposition is a capability ceiling. Three candidate architectures remain under consideration: single-specialist-on-frontier (ruled out on cost); 2-LLM split (frontier plans, MiniMax executes — Sprint 10H tests); LLM+CODE executor (word-diff pipeline port from Claude-Plugin-MCP — Sprint 10I if 10H fails).
   - Trigger: Sprint 10H outcome; ADR candidate in 10H per planned ADRs 019-021.
   - Source: Sprint 10E scope boundary; Sprint 10F §10G proposal; Sprint 10G architectural-judgement section.

10. **Subagent tool-call surfacing to the outer message trace.** Deep Agents' `task` tool strips subagent messages; only the final `ToolMessage.content` reaches GC. Current workaround is the `_TOOL_CALL_CAPTURE` + `tool-calls.jsonl` pattern inside tool implementations; it now lives in three sprint directories (10E, 10F, 10G) and the "promote on second call site" bar has been met. Durable fix options: custom middleware that tees intermediate state, or direct second-pass invocation.
    - Trigger: next sprint that uses the pattern — promote to `src/experiments/common/`; OR an audit/compliance requirement for visible specialist reasoning forces a middleware-level fix.
    - Source: Sprint 9 surprise 4; Sprint 10E surprise 1; Sprint 10F; Sprint 10G.

11. **`structured_response` propagation through the `task` tool.** Specialist JSON is serialised into `ToolMessage.content` at HOC level but stripped from state before reaching GC. Three options mapped in Sprint 9: (a) second-pass direct invocation, (b) HOC's own `response_format` (forecloses multi-specialist composition), (c) middleware tee.
    - Trigger: a sprint needs specialist JSON available at GC level (e.g., audit log, gate on structured result).
    - Source: Sprint 9 surprise 4; ADRs 013, 016.

12. **MiniMax reasoning observability through LangChain.** `reasoning_split=True` (ADR 012 production default) produces `reasoning_content` / `reasoning_details` that LangChain's `_convert_dict_to_message` drops; neither `additional_kwargs` nor `response_metadata` carries them through. Today's 10G workaround is a local `reasoning_split=False` factory override per agent (routes reasoning back inline into `<think>...</think>` content). Production-clean route: custom MiniMax LangChain subclass that overrides dict-to-message conversion to preserve reasoning into `additional_kwargs`. Candidate location: `src/llm/chat_model.py` — a `preserve_reasoning: bool = False` flag on `_minimax_factory`.
    - Trigger: reasoning observability becomes a standing need (second sprint wanting MiniMax reasoning visible beyond a one-off `<think>` inline flip).
    - Source: Sprint 10G surprise 5, carry-forward (iii); ADR 012.

13. **Audit-trail protection above Adeu for cross-author rejection.** Adeu's `RejectChange` does NOT gate on author — a counterparty can cleanly reject Oscar's `Chg:N` edits. Qualifies Sprint 10A finding #6. Options: (a) document as known limitation; (b) lightweight facilitator checking author consistency before `RejectChange`; (c) raise upstream with Adeu maintainers.
    - Trigger: the behaviour bites in practice, OR Oscar begins accepting counterparty-signed redlines.
    - Source: Sprint 10C finding 5, Q1.

14. **Missing ADR — pin `adeu==1.1.0` and version-bump discipline.** Sprint 10A flagged "ADR to write in 10B" for pin + bump-budget posture; Sprint 10B wrote no ADRs. The 10C test battery (82 tests) is the de-facto regression mechanism.
    - Trigger: Adeu 1.2+ release, OR the first time a bump breaks the battery.
    - Source: Sprint 10A finding 2, risk R7; Sprint 10B "ADRs written: none".

15. **Internal-API reach-around policy for Adeu.** Prior art reaches into `adeu.anchor`, `adeu.redline.mapper.DocumentMapper`; Sprint 10A proposed an ADR committing Oscar to the public `__all__` surface "if it becomes a call-site concern." Not yet a call-site concern.
    - Trigger: a sprint needs a behaviour not in `adeu.__all__`.
    - Source: Sprint 10A finding 4 / surprise 4.

16. **Deployignore / build-time exclusion of non-runtime files.** PROJECT.md line 131 notes exclusion of PROJECT.md, CLAUDE.md, `docs/adr/` is a build-time concern handled when SIT is stood up.
    - Trigger: SIT stand-up / first packaging pipeline.
    - Source: PROJECT.md § Files in Project Root.

## Prompt and model findings

17. **Promote OPERATING DISCIPLINE preamble to a shared template.** Now on three call sites (HOC 10D iteration 2, redline-specialist 10F iteration 2, redline-specialist 10G — inherited from 10F). Same-shape fix each time — forbids file-missing claims, redirects to tool-only operation. 10G refines the finding: the preamble works at the *reply* layer but NOT the *reasoning* layer (visible with `reasoning_split=False`; MiniMax internally hallucinates "file doesn't exist" then overcomes it by re-reading the instruction and proceeding from priors). A prompt-level band-aid, not a full fix.
    - Trigger: third NEW specialist joins Oscar (pattern needs a reusable template), OR reasoning-level confusion becomes a systematic blocker.
    - Source: Sprint 10F carry-forward (iii); Sprint 10D iteration 2; Sprint 10F iteration 2; Sprint 10G carry-forward (v).

18. **Defensive fallback for MiniMax structured-output discipline.** Tool-call discipline was ~67% on first-pass prompts in Sprint 9; the preamble lifted it to 100% but remains prompt-level. Candidate: middleware that auto-strips markdown code fences when `structured_response` is missing, OR hard switch to a stronger specialist tier.
    - Trigger: specialist count grows, OR rules become less step-by-step, OR a new intermittent fence-wrapping incident.
    - Source: Sprint 9 surprise 2.

19. **Sub-agent response brevity discipline.** Short directional prompts do not produce terse sub-agent output — HOC returned markdown-formatted multi-section replies in Sprint 7. Needs `response_format` constraint or tighter prompt scaffolding.
    - Trigger: a substantive capability sprint that needs clean envelope output from sub-agents.
    - Source: Sprint 7 surprise 2.

20. **Planning-tracking is model-discretionary — augment `BASE_AGENT_PROMPT` where needed.** `write_todos` fires only when the system prompt explicitly asks for planning.
    - Trigger: a capability sprint whose work benefits from observable plan tracking.
    - Source: Sprint 6 "Whether and how `write_todos` fired" + next-sprint (a).

21. **Add a "nested-on-own-insertion" disqualifier test to the 10C battery.** 10D's duplicate-call produced a structurally-valid but audit-trail-broken redline; 10C's existing `test_edit_inside_existing_insertion` doesn't cover the full-length-match case.
    - Trigger: cheap to do — add on next touch of the battery.
    - Source: Sprint 10D surprise 2, carry-forward (ii).

22. **Document asymmetric narrow-del / wide-ins shape in `adeu-idioms.md`.** `trim_common_context` produces this shape when `new_text` includes new machinery the old text didn't have (10F's 12-word del + 33-word ins). Not covered by 10C's symmetric shared-prefix/suffix tests.
    - Trigger: cheap to do — next edit to the idioms doc.
    - Source: Sprint 10F surprise 4.

23. **Tool-level rejection of degenerate `target_text == new_text`.** 10F iteration 2's second call was a no-op on identical strings (harmless but diagnostic); 10G iteration 1's observability-failed run showed wasteful-retry shapes of similar flavour, and iteration 2 produced a single clean call with no retries. Not yet at the bar for wrapping.
    - Trigger: third clean-no-op occurrence.
    - Source: Sprint 10F carry-forward (v); Sprint 10G carry-forward (vi).

24. **Pick a comment-on-pure-deletion workaround for the redline specialist.** Adeu silently drops comments on deletions. Two ugly options: attach to a retained anchor, or use `new_text=" "` space-padded.
    - Trigger: first transformation that needs a standalone comment accompanying a deletion.
    - Source: Sprint 10C finding 3, Q2; Sprint 10D carry-forward (iv); Sprint 10E carry-forward (iv).

25. **Internationalisation: comment-discipline prompt is English / common-law-culture-specific.** Prior-art prompting disciplines imported from Claude-Plugin-MCP assume an English commercial-law drafting register.
    - Trigger: first non-English-law client, OR first civil-law deployment.
    - Source: Sprint 10A risk R8.

## Infrastructure

26. **LangSmith tracing — add `LANGSMITH_API_KEY` + policy block for `smith.langchain.com` / `api.smith.langchain.com`.** Silently disabled since Sprint 6.
    - Trigger: first sprint that wants traces for debugging or observability.
    - Source: Sprint 6 surprise 5; Sprint 7/8/9 carry-forwards (ii/ii/vi).

27. **`langchain_docs` network policy block — `docs.langchain.com`, `python.langchain.com`, `api.python.langchain.com`.** Currently `docs.langchain.com` returns HTTP 403; sprints work from installed source per "code outranks docs."
    - Trigger: sprint whose brief genuinely depends on hosted docs (not resolvable from source alone).
    - Source: Sprint 2 surprise 1.

28. **OpenRouter `HTTP-Referer` / `X-Title` attribution for production.** Current requests are anonymous from OpenRouter's usage-dashboard perspective.
    - Trigger: first client-facing deployment so OpenRouter attributes calls to this workload.
    - Source: Sprint 4 surprise 4.

29. **Word UI rendering / Accept-All preview automation.** "Opens in Word" cannot be automated in the sandbox (no Word, no LibreOffice). Mechanical checks + clean-view extraction substitute today; no end-to-end gate for lawyer-shape.
    - Trigger: CI gate or regression harness that needs programmatic Word rendering.
    - Source: Sprint 10A risk R9.

30. **Automate per-provider key sanity check at sprint start.** `.env` is git-ignored; Sprint 6 lost ~15 minutes to a stale-key-from-prior-sprint surprise. `docs/secrets.md` documents but does not enforce.
    - Trigger: recurrence of the same surprise.
    - Source: Sprint 6 surprise 1, next-sprint (d).

31. **Investigate `sk-cp-...` broker-key prefix if billing or rate-limit behaviour looks unusual.** Not MiniMax's native `sk-...` format but authenticates. Worked; moved on.
    - Trigger: anomalous billing, rate-limit, or authentication signal.
    - Source: Sprint 3 surprise 4.

## Dependencies

32. **LangMem integration.** Explicitly excluded from Sprint 1's core install.
    - Trigger: first sprint landing long-term learning / cross-session memory capability (PROJECT.md § Learning).
    - Source: Sprint 1 surprise 5.

33. **Postgres variants: `langgraph-checkpoint-postgres`, `langgraph-store-postgres`, `langchain-postgres`.** Excluded from Sprint 1; today's checkpointer is in-memory only.
    - Trigger: first sprint needing checkpoint persistence across `invoke()` calls (e.g., HITL resume, long-running sessions).
    - Source: Sprint 1 surprise 5.

34. **LangGraph 2.x upgrade — `config_schema` → `context_schema` migration.** Soft-deprecated in 1.1.8 with removal in 2.0.0.
    - Trigger: LangGraph 2.x release or security advisory.
    - Source: Sprint 2 surprise 2.

35. **Adeu version-bump discipline.** `adeu==1.1.0` pinned; 0.9.0→1.0.0→1.1.0 was breaking. The 10C battery (82 tests) is the mechanism; run on any bump.
    - Trigger: Adeu 1.2+ release, dependabot signal, or security advisory.
    - Source: Sprint 10A finding 2, risk R7; Sprint 10C Part 2.

36. **`fastmcp[apps]` vendor-strip option.** 60 transitive packages pulled for a dormant-in-SDK-mode server stack; no runtime need.
    - Trigger: transitive dep conflict with a future package, OR security-review pushback on dormant install surface.
    - Source: Sprint 10A risk R2; Sprint 10B install diff.

37. **`langchain-perplexity` / LangChain PR #35530 watch.** If merged, the core tag-stripper becomes available as a generic `<think>`-handling utility; today Oscar uses `reasoning_split=True` (MiniMax-specific).
    - Trigger: second reasoning-trace provider joins the seam, OR the PR merges into an installed module.
    - Source: Sprint 8 surprise 4.

## Handoff items

38. **Arturs: sign off `docs/reference/adeu-lawyer-shape-criteria.md` (DRAFT).** Still unsigned; 10E/10F/10G self-verified against the respective sprint briefs directly.
    - Trigger: first sprint that needs a shared criteria reference across transformations (T1 "make mutual", T2 "add LoL").
    - Source: Sprint 10C Part 4; Sprint 10D (v); Sprint 10E (ii); Sprint 10F (ii); Sprint 10G (ii).

39. **Arturs: Word-level review of `src/experiments/sprint-10e/nda-output.docx`.** Mechanical checks pass; lawyer-shape review is the next gate.
    - Trigger: now — 10E marked output ready.
    - Source: Sprint 10E assessment.

40. **Arturs: decide Sprint 10F and Sprint 10G feature-branch merges.** Feature branches `sprint-10f-identification-test` and `sprint-10g-planning-prompt` contain partial results (10F: one wide substantive call + one no-op; 10G: one wide substantive call, reasoning visibly committing to a one-edit bundle). Merge decisions depend on whether the wider shape is acceptable for production given content correctness — if Arturs accepts 10F's shape, 10F/10G are both "successful at the shape level that matters" and 10H shifts from a capability question to a margin question.
    - Trigger: after 10H diagnostic, or on independent human review.
    - Source: Sprint 10F feature-branch commit + next-sprint (c); Sprint 10G feature-branch commit + next-sprint (c).

41. **Arturs: four open 10C questions.** (a) non-owning-author reject: document + proceed, or facilitator, or raise upstream? (b) comment-on-deletion workaround: anchor-attach or space-pad? (c) expose `apply_edits_to_markdown` to the agent: yes/no? (d) `adeu.sanitize` exposure: now or defer until counterparty-delivery sprint?
    - Trigger: before 10H, or the first sprint touching any of these surfaces.
    - Source: Sprint 10C §Questions.

42. **Sprint 10H execution.** Flip `OSCAR_LLM_REDLINE_SPECIALIST_{PROVIDER,MODEL}` to `openrouter` / `openai/gpt-5.4`; rerun 10F's prompt verbatim (NOT 10G's plan-before-act prompt — the goal is raw decomposition capability, not prompt-forced planning). Three-way diagnostic per Sprint 10G next-sprint (a): GPT-5.4 produces 10E-shape surgical decomposition → single-specialist-on-frontier suffices; GPT-5.4 also bundles → LLM + CODE-executor path (10I port of Claude-Plugin-MCP word-diff pipeline); GPT-5.4 in between → graduated design space.
    - Trigger: immediate — this is the named next sprint.
    - Source: Sprint 10G architectural-judgement section; Sprint 10G next-sprint (a).

43. **Run T1 (make-mutual) and T2 (add-LoL) transformations on their own synthetic NDAs.** Proposed in Sprint 10A §3.4 as shape only; never drafted or run. Different decomposition shapes — T1 stresses coordinated consistency (many narrow edits), T2 stresses novel-clause insertion.
    - Trigger: after identification-shape is settled on T3 (10H/10I resolution).
    - Source: Sprint 10A §3.4; Sprint 10E next-sprint (c); Sprint 10F (d); Sprint 10G (d).

44. **Real-document + real-playbook ingestion test.** Attach a genuine NDA + playbook and test whether HOC isolates the governing-law clause and routes correctly, or whether a document-parsing layer must land first.
    - Trigger: capability-readiness gate for a first pilot client.
    - Source: Sprint 7 next-sprint (c); Sprint 9 next-sprint (d).

45. **Second playbook rule for `accept-reject-reasoner`.** Stress-tests the specialist under multi-rule reasoning; triggers the ADR 015 supersede (item 2).
    - Trigger: capability expansion beyond governing-law.
    - Source: Sprint 9 next-sprint (b).

46. **Second functional specialist under HOC.** Candidates: comment-responder, fresh-language drafter, defined-terms auditor. Same `SubAgent`+`response_format` pattern (ADR 013); extends HOC's routing prompt (ADR 016).
    - Trigger: next capability build-out.
    - Source: Sprint 7 next-sprint (b); Sprint 9 next-sprint (a).

47. **Second department head under GC.** Company Secretariat, Data Protection, Employment, Property, or Litigation — stresses routing with more than one staffed option.
    - Trigger: capability expansion beyond commercial contracts.
    - Source: Sprint 7 next-sprint (a); PROJECT.md § Capability Stages.

48. **Counterparty-response workflow branch.** Oscar today has Claude-Plugin-MCP's "first-pass" branch only; the "counterparty-response" branch (CriticMarkup-detected, multi-round negotiation posture) is not ported.
    - Trigger: capability expansion to multi-round redline exchange.
    - Source: Sprint 10A finding 5.

49. **Sanitisation post-step using `adeu.sanitize`.** Relevant when Oscar ships counterparty-deliverable redlines (strip non-delivered comments, clean metadata). `accept_all_revisions()` also purges comments — more destructive than Word UI Accept All.
    - Trigger: first sprint that delivers a redline externally (vs. internal review only).
    - Source: Sprint 10C finding 9, Q4; Sprint 10A.
